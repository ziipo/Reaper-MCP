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

    def __init__(self) -> None:
        # each track: {"name", "vol" (amp), "mute", "items": [..], "fx": [..]}
        self.tracks: list[dict] = []
        self.play_state = 0
        self.bpm = 120.0

    # -- ReaScript function model ------------------------------------------

    def call(self, fn: str, args: list):
        if fn == "CountTracks":
            return [len(self.tracks)]
        if fn == "GetNumTracks":
            return [len(self.tracks)]
        if fn == "InsertTrackAtIndex":
            idx = int(args[0])
            self.tracks.insert(idx, {"name": "", "vol": 1.0, "mute": 0.0,
                                     "items": [], "fx": []})
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
            idx, _s, _e, notes = args
            if idx >= len(self.tracks):
                raise RuntimeError("no track at index %s" % idx)
            self.tracks[idx]["items"].append({"notes": notes})
            return [len(self.tracks[idx]["items"]) - 1, len(notes)]
        if fn == "MCP.render_mp3":
            d, fname, _end = args
            return [os.path.join(d, fname)]
        if fn == "MCP.ping":
            return ["pong", ["add_fx", "create_midi_item_with_notes",
                             "render_mp3", "set_tempo"]]
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
