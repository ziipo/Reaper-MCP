"""Shared pytest fixtures: a fake Lua bridge responder for tests without Reaper.

The FakeLua thread mimics reaper_mcp_bridge.lua: it polls a bridge dir for
*.req.json, runs a Python model of the relevant ReaScript functions, and writes
*.resp.json atomically — exactly the contract bridge.py expects.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from reaper_mcp.bridge import ReaperBridge


class FakeReaper:
    """A tiny in-memory model of a Reaper project for deterministic tests."""

    _guid_counter = 0

    def __init__(self) -> None:
        # each track: {"name", "vol", "mute", "pan", "solo", "arm", "guid",
        #              "items": [{"notes":[...], "position","length","mute"}], "fx": []}
        self.tracks: list[dict] = []
        self.play_state = 0
        self.bpm = 120.0
        self.markers: list[dict] = []
        self.cursor = 0.0

    def _new_track(self) -> dict:
        FakeReaper._guid_counter += 1
        return {"name": "", "vol": 1.0, "mute": 0.0, "pan": 0.0, "solo": 0.0,
                "arm": 0.0, "guid": "{GUID-%d}" % FakeReaper._guid_counter,
                "items": [], "fx": []}

    def _resolve_track_idx(self, sel):
        """A selector is an int index or a GUID string -> index, or None."""
        if isinstance(sel, int):
            return sel if 0 <= sel < len(self.tracks) else None
        if isinstance(sel, str):
            g = sel.replace("guid:", "")
            for i, t in enumerate(self.tracks):
                if t["guid"] == g:
                    return i
        return None

    # -- ReaScript function model ------------------------------------------

    def call(self, fn: str, args: list):
        if fn == "CountTracks":
            return [len(self.tracks)]
        if fn == "GetNumTracks":
            return [len(self.tracks)]
        if fn == "InsertTrackAtIndex":
            idx = int(args[0])
            self.tracks.insert(idx, self._new_track())
            return []
        if fn == "DeleteTrack":
            idx = int(args[0])
            if 0 <= idx < len(self.tracks):
                self.tracks.pop(idx)
            return []
        if fn == "TrackList_AdjustWindows":
            return []
        if fn == "GetSetMediaTrackInfo_String":
            idx, parm, val, setnew = args
            if idx >= len(self.tracks):
                return [False, ""]
            if parm == "P_NAME":
                if setnew:
                    self.tracks[idx]["name"] = val
                    return [True, val]
                return [True, self.tracks[idx]["name"]]
            return [False, ""]
        if fn == "GetMediaTrackInfo_Value":
            idx, parm = args
            if idx >= len(self.tracks):
                return [0.0]
            t = self.tracks[idx]
            return [t["vol"] if parm == "D_VOL" else t["mute"]]
        if fn == "SetMediaTrackInfo_Value":
            idx, parm, val = args
            if idx >= len(self.tracks):
                return [False]
            self.tracks[idx]["vol" if parm == "D_VOL" else "mute"] = val
            return [True]
        if fn == "Main_OnCommand":
            cmd = args[0]
            if cmd == 1007:
                self.play_state = 1
            elif cmd == 1016:
                self.play_state = 0
            return []
        if fn == "GetPlayState":
            return [self.play_state]
        if fn == "GetAppVersion":
            return ["fake/test"]
        if fn == "Master_GetTempo":
            return [self.bpm]
        # composites
        if fn == "MCP.set_tempo":
            self.bpm = args[0]
            return [args[0]]
        if fn == "MCP.add_fx":
            idx, name = args
            if idx >= len(self.tracks):
                raise RuntimeError("no track at index %s" % idx)
            self.tracks[idx]["fx"].append(name)
            return [len(self.tracks[idx]["fx"]) - 1]
        if fn == "MCP.create_midi_item_with_notes":
            sel, start, end, notes = args
            idx = self._resolve_track_idx(sel)
            if idx is None:
                raise RuntimeError("no track at %s" % sel)
            self.tracks[idx]["items"].append(
                {"notes": list(notes), "position": start, "length": end - start})
            return [len(self.tracks[idx]["items"]) - 1, len(notes)]
        if fn == "MCP.render_mp3":
            d, fname, _end = args
            return [os.path.join(d, fname)]
        if fn == "MCP.ping":
            return ["pong", ["add_fx", "create_midi_item_with_notes",
                             "render_mp3", "set_tempo"]]
        if fn == "MCP.reload":
            return ["reloaded"]

        # -- Phase A --
        if fn == "MCP.describe_project":
            include_items = args[0] if args else True
            include_fx = args[1] if len(args) > 1 else True
            tracks = []
            for i, t in enumerate(self.tracks):
                d = {"index": i, "guid": t["guid"], "name": t["name"],
                     "volume": t["vol"], "pan": t["pan"],
                     "muted": t["mute"] != 0, "soloed": t["solo"] != 0,
                     "armed": t["arm"] != 0, "item_count": len(t["items"]),
                     "fx_count": len(t["fx"])}
                if include_items:
                    d["items"] = [{"index": j, "position": it.get("position", 0),
                                   "length": it.get("length", 0),
                                   "muted": False, "take_name": "",
                                   "is_midi": True}
                                  for j, it in enumerate(t["items"])]
                if include_fx:
                    d["fx"] = [{"index": k, "name": nm, "enabled": True}
                               for k, nm in enumerate(t["fx"])]
                tracks.append(d)
            return [{"name": "test", "tempo": self.bpm,
                     "play_state": self.play_state,
                     "track_count": len(self.tracks), "tracks": tracks}]
        if fn == "MCP.get_track_guid":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            return [self.tracks[idx]["guid"]]

        # -- Phase B: track editing --
        if fn == "MCP.set_track_value":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            key = {"D_PAN": "pan", "I_SOLO": "solo", "I_RECARM": "arm",
                   "D_VOL": "vol", "B_MUTE": "mute"}.get(args[1])
            if key:
                self.tracks[idx][key] = args[2]
            return [True]
        if fn == "MCP.get_track_value":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            key = {"D_PAN": "pan", "I_SOLO": "solo", "I_RECARM": "arm",
                   "D_VOL": "vol", "B_MUTE": "mute"}.get(args[1], "pan")
            return [self.tracks[idx][key]]
        if fn == "MCP.set_track_color":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            return [True]
        if fn == "MCP.move_track":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            t = self.tracks.pop(idx)
            self.tracks.insert(args[1], t)
            return [True]
        if fn == "MCP.set_folder_depth":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            return [True]

        # -- Phase B: items --
        if fn == "MCP.set_item_bounds":
            idx = self._resolve_track_idx(args[0])
            it = self.tracks[idx]["items"][args[1]]
            if args[2] is not None:
                it["position"] = args[2]
            if args[3] is not None:
                it["length"] = args[3]
            return [it.get("position", 0), it.get("length", 0)]
        if fn == "MCP.set_item_fades":
            return [True]
        if fn == "MCP.split_item":
            return [True]
        if fn == "MCP.delete_item":
            idx = self._resolve_track_idx(args[0])
            self.tracks[idx]["items"].pop(args[1])
            return [True]
        if fn == "MCP.move_item_to_track":
            si = self._resolve_track_idx(args[0])
            di = self._resolve_track_idx(args[2])
            it = self.tracks[si]["items"].pop(args[1])
            self.tracks[di]["items"].append(it)
            return [True]

        # -- Phase B: MIDI --
        if fn == "MCP.get_notes":
            idx = self._resolve_track_idx(args[0])
            notes = self.tracks[idx]["items"][args[1]]["notes"]
            return [[{"index": j, "start_qn": n[0], "end_qn": n[1],
                      "pitch": n[2], "vel": n[3] if len(n) > 3 else 96,
                      "chan": n[4] if len(n) > 4 else 0,
                      "muted": False, "selected": False}
                     for j, n in enumerate(notes)]][0]
        if fn == "MCP.add_notes":
            idx = self._resolve_track_idx(args[0])
            self.tracks[idx]["items"][args[1]]["notes"].extend(args[2])
            return [len(args[2])]
        if fn == "MCP.set_note":
            idx = self._resolve_track_idx(args[0])
            note = self.tracks[idx]["items"][args[1]]["notes"][args[2]]
            f = args[3] or {}
            if "pitch" in f:
                note[2] = f["pitch"]
            return [True]
        if fn == "MCP.delete_note":
            idx = self._resolve_track_idx(args[0])
            self.tracks[idx]["items"][args[1]]["notes"].pop(args[2])
            return [True]

        # -- Phase B: markers --
        if fn == "MCP.add_marker":
            num = len(self.markers) + 1
            self.markers.append({"number": num, "name": args[1],
                                 "position": args[0],
                                 "is_region": bool(args[2])})
            return [num]
        if fn == "MCP.delete_marker":
            before = len(self.markers)
            self.markers = [m for m in self.markers if m["number"] != args[0]]
            return [len(self.markers) < before]
        if fn == "MCP.list_markers":
            return [[dict(m, enum_index=i, region_end=m["position"])
                     for i, m in enumerate(self.markers)]][0]
        if fn == "MCP.set_cursor":
            self.cursor = args[0]
            return [self.cursor]

        # -- Phase C: FX params --
        if fn == "MCP.list_fx_params":
            return [[{"index": 0, "name": "Gain-Band 2", "value": 0.0,
                      "min": -24.0, "max": 24.0, "value_norm": 0.5,
                      "formatted": "0.0"}]][0]
        if fn == "MCP.set_fx_param_by_name":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            if "nomatch" in str(args[2]).lower():
                raise RuntimeError("no param matching '%s'" % args[2])
            return [4, args[2], "-1.5"]
        if fn == "MCP.set_fx_enabled":
            return [args[2]]
        if fn == "MCP.delete_fx":
            return [True]
        if fn == "MCP.set_fx_preset":
            return [True]

        # -- Phase C: envelopes --
        if fn == "MCP.write_envelope":
            idx = self._resolve_track_idx(args[0])
            if idx is None:
                raise RuntimeError("no track")
            self.tracks[idx].setdefault("_env", {})[str(args[1])] = list(args[2])
            return [len(args[2])]
        if fn == "MCP.read_envelope":
            idx = self._resolve_track_idx(args[0])
            pts = self.tracks[idx].get("_env", {}).get(str(args[1]), [])
            return [{"index": i, "time": p[0], "value": p[1],
                     "shape": p[2] if len(p) > 2 else 0}
                    for i, p in enumerate(pts)]

        # -- Phase C: sends --
        if fn == "MCP.add_send":
            si = self._resolve_track_idx(args[0])
            di = self._resolve_track_idx(args[1])
            if si is None or di is None:
                raise RuntimeError("track not found")
            self.tracks[si].setdefault("_sends", []).append(
                {"dest": di, "vol": 1.0, "pan": 0.0})
            return [len(self.tracks[si]["_sends"]) - 1]
        if fn == "MCP.set_send_value":
            si = self._resolve_track_idx(args[0])
            s = self.tracks[si]["_sends"][args[1]]
            if args[2] == "D_VOL":
                s["vol"] = args[3]
            elif args[2] == "D_PAN":
                s["pan"] = args[3]
            return [True]
        if fn == "MCP.list_sends":
            si = self._resolve_track_idx(args[0])
            sends = self.tracks[si].get("_sends", [])
            return [{"index": i, "name": self.tracks[s["dest"]]["name"],
                     "volume": s["vol"], "pan": s["pan"]}
                    for i, s in enumerate(sends)]
        if fn == "MCP.remove_send":
            si = self._resolve_track_idx(args[0])
            self.tracks[si]["_sends"].pop(args[1])
            return [True]

        # -- Phase D: render/project --
        if fn == "MCP.render":
            d, fname = args[0], args[1]
            path = os.path.join(d, fname)
            return [path, True, path]
        if fn == "MCP.file_exists":
            return [os.path.exists(args[0])]
        if fn == "MCP.save_project":
            path = args[0] if args else None
            return ["proj", path or "/tmp/proj"]
        if fn == "MCP.select_track":
            return [True]
        if fn == "MCP.list_tabs":
            return [{"tab": 0, "name": "test", "track_count": len(self.tracks)}]
        if fn == "MCP.switch_tab":
            return ["test"]
        if fn == "MCP.close_tab":
            return [True]
        if fn == "MCP.project_info":
            return [{"name": "proj", "path": "/tmp", "change_count": 1}]
        if fn == "MCP.new_project":
            return [True]
        if fn == "MCP.open_project":
            return ["opened"]
        if fn == "MCP.insert_media":
            return [1]

        # unknown
        raise RuntimeError("unknown function: %s" % fn)


class FakeLua(threading.Thread):
    def __init__(self, bridge_dir: Path, model: FakeReaper) -> None:
        super().__init__(daemon=True)
        self.bridge_dir = bridge_dir
        self.model = model
        self.running = True

    def run(self) -> None:
        while self.running:
            (self.bridge_dir / "heartbeat").write_text(str(time.time()))
            for req in list(self.bridge_dir.glob("*.req.json")):
                try:
                    data = json.loads(req.read_text())
                except Exception:
                    continue
                req.unlink(missing_ok=True)
                results, ok_all, err = [], True, None
                for c in data["calls"]:
                    try:
                        results.append(self.model.call(c["fn"], c.get("args", [])))
                    except Exception as e:  # noqa: BLE001
                        ok_all = False
                        err = err or str(e)
                        results.append(None)
                resp = {"id": data["id"], "ok": ok_all, "results": results}
                if err:
                    resp["error"] = err
                tmp = self.bridge_dir / f"{data['id']}.resp.json.tmp"
                tmp.write_text(json.dumps(resp))
                os.replace(tmp, self.bridge_dir / f"{data['id']}.resp.json")
            time.sleep(0.003)


@pytest.fixture
def fake_reaper() -> FakeReaper:
    return FakeReaper()


@pytest.fixture
def bridge(tmp_path: Path, fake_reaper: FakeReaper):
    """A ReaperBridge wired to a FakeLua responder in a temp dir."""
    bdir = tmp_path / "mcp_bridge"
    bdir.mkdir()
    lua = FakeLua(bdir, fake_reaper)
    lua.start()
    # wait for first heartbeat
    for _ in range(100):
        if (bdir / "heartbeat").exists():
            break
        time.sleep(0.01)
    b = ReaperBridge(bridge_dir=bdir, timeout=3.0)
    yield b
    lua.running = False
