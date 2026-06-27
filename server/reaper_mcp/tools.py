"""Vertical-slice tool implementations.

Each function maps an MCP tool to one or more ReaScript calls via the bridge.
Track references use a 0-based track INDEX; the Lua side resolves the index to a
MediaTrack* for functions that take a track (see TRACK_ARG_FNS in the Lua bridge).
"""

from __future__ import annotations

import math

from .bridge import Call, ReaperBridge


# Reaper's D_VOL is a linear amplitude factor (1.0 == 0 dB). Users think in dB,
# so we convert at the boundary.
def db_to_amp(db: float) -> float:
    return 10.0 ** (db / 20.0)


def amp_to_db(amp: float) -> float:
    if amp <= 0:
        return -math.inf
    return 20.0 * math.log10(amp)


def _first(result: list, default=None):
    """Return the first return value of a bridge result, or default."""
    return result[0] if result else default


def call_reascript(bridge: ReaperBridge, fn: str, args: list | None = None) -> list:
    """Escape hatch: invoke ANY reaper.* function by name and return its results.

    `fn` is the ReaScript function name without the `reaper.` prefix (e.g.
    "CountTracks", "SetMediaTrackInfo_Value"). `args` is the positional argument
    list. Returns the list of all Lua return values.

    Limitations:
      - Opaque pointers (MediaTrack*, MediaItem*, take, etc.) cannot cross the
        bridge: they come back as "<userdata>" and cannot be passed in. For
        functions that take a track, pass a 0-based track INDEX where the bridge
        knows to resolve it (see TRACK_ARG_FNS in the Lua bridge); for arbitrary
        pointer chaining, add a composite helper in mcp_helpers.lua instead.
    """
    return bridge.call(fn, *(args or []))


def list_tracks(bridge: ReaperBridge) -> list[dict]:
    """Return all tracks with index, name, volume (dB), and mute state."""
    count = _first(bridge.call("CountTracks", 0), 0)
    if not count:
        return []

    # One batched round-trip: name + volume + mute for every track.
    calls: list[Call] = []
    for i in range(count):
        calls.append(Call("GetSetMediaTrackInfo_String", [i, "P_NAME", "", False]))
        calls.append(Call("GetMediaTrackInfo_Value", [i, "D_VOL"]))
        calls.append(Call("GetMediaTrackInfo_Value", [i, "B_MUTE"]))
    results = bridge.call_many(calls)

    tracks = []
    for i in range(count):
        name_res = results[i * 3]          # [retval, stringNeedBig]
        vol_res = results[i * 3 + 1]       # [amp]
        mute_res = results[i * 3 + 2]      # [0|1]
        name = name_res[1] if len(name_res) > 1 else ""
        amp = _first(vol_res, 1.0)
        muted = bool(_first(mute_res, 0))
        tracks.append(
            {
                "index": i,
                "name": name,
                "volume_db": round(amp_to_db(amp), 2),
                "muted": muted,
            }
        )
    return tracks


def add_track(bridge: ReaperBridge, name: str | None = None) -> dict:
    """Append a new track at the end. Optionally set its name. Returns the track."""
    count = _first(bridge.call("CountTracks", 0), 0)
    new_index = count  # append at the end (0-based index == current count)

    calls: list[Call] = [
        Call("InsertTrackAtIndex", [new_index, True]),
        Call("TrackList_AdjustWindows", [False]),
    ]
    if name:
        calls.append(
            Call("GetSetMediaTrackInfo_String", [new_index, "P_NAME", name, True])
        )
    bridge.call_many(calls)
    return {"index": new_index, "name": name or ""}


def delete_track(bridge: ReaperBridge, index: int) -> dict:
    """Delete the track at the given 0-based index."""
    count = _first(bridge.call("CountTracks", 0), 0)
    if index < 0 or index >= count:
        raise ValueError(f"No track at index {index} (project has {count} tracks)")
    bridge.call("DeleteTrack", index)
    bridge.call("TrackList_AdjustWindows", False)
    return {"deleted_index": index, "remaining": count - 1}


def delete_all_tracks(bridge: ReaperBridge) -> dict:
    """Delete every track in the project (deletes from the end to keep indices stable)."""
    count = _first(bridge.call("CountTracks", 0), 0)
    for i in range(count - 1, -1, -1):
        bridge.call("DeleteTrack", i)
    bridge.call("TrackList_AdjustWindows", False)
    return {"deleted": count}


def get_track_name(bridge: ReaperBridge, index: int) -> str:
    res = bridge.call("GetSetMediaTrackInfo_String", index, "P_NAME", "", False)
    if len(res) < 2:
        raise ValueError(f"No track at index {index}")
    return res[1]


def set_track_name(bridge: ReaperBridge, index: int, name: str) -> dict:
    res = bridge.call("GetSetMediaTrackInfo_String", index, "P_NAME", name, True)
    ok = _first(res, False)
    if not ok:
        raise ValueError(f"No track at index {index}")
    return {"index": index, "name": name}


def set_track_volume(bridge: ReaperBridge, index: int, volume_db: float) -> dict:
    amp = db_to_amp(volume_db)
    res = bridge.call("SetMediaTrackInfo_Value", index, "D_VOL", amp)
    ok = _first(res, False)
    if not ok:
        raise ValueError(f"No track at index {index}")
    return {"index": index, "volume_db": volume_db}


def set_track_mute(bridge: ReaperBridge, index: int, muted: bool) -> dict:
    res = bridge.call("SetMediaTrackInfo_Value", index, "B_MUTE", 1.0 if muted else 0.0)
    ok = _first(res, False)
    if not ok:
        raise ValueError(f"No track at index {index}")
    return {"index": index, "muted": muted}


# Transport command IDs (Main_OnCommand)
_CMD_PLAY = 1007
_CMD_STOP = 1016

# GetPlayState bitmask: 0=stopped, 1=playing, 2=paused, 4=recording.
_PLAY_STATE = {0: "stopped", 1: "playing", 2: "paused", 4: "recording"}


def transport_play(bridge: ReaperBridge) -> dict:
    bridge.call("Main_OnCommand", _CMD_PLAY, 0)
    return {"state": "playing"}


def transport_stop(bridge: ReaperBridge) -> dict:
    bridge.call("Main_OnCommand", _CMD_STOP, 0)
    return {"state": "stopped"}


def get_play_state(bridge: ReaperBridge) -> dict:
    flags = int(_first(bridge.call("GetPlayState"), 0))
    # Compose a readable state; recording can coexist with playing.
    names = [name for bit, name in _PLAY_STATE.items() if bit and (flags & bit)]
    if not names:
        names = ["stopped"]
    return {"flags": flags, "state": "+".join(names)}


# -- composite / project-level operations (chained inside Lua via MCP.*) ------


def set_tempo(bridge: ReaperBridge, bpm: float) -> dict:
    """Set the project tempo in BPM."""
    bridge.call("MCP.set_tempo", bpm)
    return {"bpm": bpm}


def add_fx(bridge: ReaperBridge, index: int, fx_name: str) -> dict:
    """Add an FX (by name, e.g. 'ReaSynth' or 'VST:...') to a track. Returns its fx index."""
    fx_index = _first(bridge.call("MCP.add_fx", index, fx_name), -1)
    if fx_index is None or fx_index < 0:
        raise ValueError(f"FX not found or failed to add: {fx_name!r}")
    return {"track_index": index, "fx_name": fx_name, "fx_index": fx_index}


def add_midi_clip(
    bridge: ReaperBridge,
    index: int,
    start_qn: float,
    end_qn: float,
    notes: list[dict],
) -> dict:
    """Create a MIDI item on a track and fill it with notes.

    Each note is a dict: {"start_qn", "end_qn", "pitch", "vel"?, "chan"?}.
    Positions are in quarter notes from project start.
    """
    note_arrays = [
        [
            n["start_qn"],
            n["end_qn"],
            int(n["pitch"]),
            int(n.get("vel", 96)),
            int(n.get("chan", 0)),
        ]
        for n in notes
    ]
    res = bridge.call(
        "MCP.create_midi_item_with_notes", index, start_qn, end_qn, note_arrays
    )
    item_index = res[0] if res else None
    note_count = res[1] if len(res) > 1 else 0
    return {"track_index": index, "item_index": item_index, "notes": note_count}


def set_time_selection(bridge: ReaperBridge, start_sec: float, end_sec: float) -> dict:
    """Set the loop/time selection (used as render bounds for some workflows)."""
    bridge.call("MCP.set_time_selection", start_sec, end_sec)
    return {"start_sec": start_sec, "end_sec": end_sec}


def render_mp3(
    bridge: ReaperBridge, directory: str, filename: str, length_sec: float
) -> dict:
    """Render the project (0..length_sec) to an MP3 file. Returns the full path.

    `directory` must be an absolute path. `filename` should end in .mp3.
    """
    res = bridge.call("MCP.render_mp3", directory, filename, length_sec)
    path = res[0] if res else None
    return {"path": path}


# -- Phase A: introspection & addressing -------------------------------------
# A "track selector" (TSel) is either a 0-based integer index or a GUID string
# (from describe_project / get_track_guid). GUIDs survive reorder/insert/delete.


def describe_project(
    bridge: ReaperBridge, include_items: bool = True, include_fx: bool = True
) -> dict:
    """Return the full project tree (tracks→items/fx) with stable GUIDs.

    The cheapest way to give the model context about the current project state.
    """
    res = bridge.call("MCP.describe_project", include_items, include_fx)
    return res[0] if res else {}


def get_track_guid(bridge: ReaperBridge, track) -> str:
    """Get the stable GUID of a track (by index or existing GUID)."""
    return _first(bridge.call("MCP.get_track_guid", track), "")


# -- Phase B: track editing --------------------------------------------------


def set_track_color(bridge: ReaperBridge, track, r: int, g: int, b: int) -> dict:
    """Set a track's color from RGB (0-255 each)."""
    bridge.call("MCP.set_track_color", track, r, g, b)
    return {"track": track, "rgb": [r, g, b]}


def set_track_pan(bridge: ReaperBridge, track, pan: float) -> dict:
    """Set track pan (-1.0 left .. 0 center .. 1.0 right)."""
    bridge.call("MCP.set_track_value", track, "D_PAN", pan)
    return {"track": track, "pan": pan}


def set_track_solo(bridge: ReaperBridge, track, soloed: bool) -> dict:
    """Solo or unsolo a track."""
    bridge.call("MCP.set_track_value", track, "I_SOLO", 1.0 if soloed else 0.0)
    return {"track": track, "soloed": soloed}


def set_track_arm(bridge: ReaperBridge, track, armed: bool) -> dict:
    """Record-arm or disarm a track."""
    bridge.call("MCP.set_track_value", track, "I_RECARM", 1.0 if armed else 0.0)
    return {"track": track, "armed": armed}


def move_track(bridge: ReaperBridge, track, dest_index: int) -> dict:
    """Move a track to a new position (0-based index)."""
    bridge.call("MCP.move_track", track, dest_index)
    return {"track": track, "dest_index": dest_index}


def set_folder_depth(bridge: ReaperBridge, track, depth: int) -> dict:
    """Set folder depth: 1=start a folder, 0=normal, -1=close a folder."""
    bridge.call("MCP.set_folder_depth", track, depth)
    return {"track": track, "folder_depth": depth}


# -- Phase B: media item editing (item = track selector + item index) --------


def set_item_bounds(
    bridge: ReaperBridge, track, item_index: int,
    position: float | None = None, length: float | None = None,
) -> dict:
    """Set a media item's position and/or length (seconds)."""
    res = bridge.call("MCP.set_item_bounds", track, item_index, position, length)
    return {"position": res[0] if res else None,
            "length": res[1] if len(res) > 1 else None}


def set_item_fades(
    bridge: ReaperBridge, track, item_index: int,
    fadein_sec: float | None = None, fadeout_sec: float | None = None,
) -> dict:
    """Set a media item's fade-in/out lengths (seconds)."""
    bridge.call("MCP.set_item_fades", track, item_index, fadein_sec, fadeout_sec)
    return {"track": track, "item_index": item_index,
            "fadein": fadein_sec, "fadeout": fadeout_sec}


def split_item(bridge: ReaperBridge, track, item_index: int, position: float) -> dict:
    """Split a media item at a project-time position (seconds)."""
    ok = _first(bridge.call("MCP.split_item", track, item_index, position), False)
    return {"split": bool(ok), "position": position}


def delete_item(bridge: ReaperBridge, track, item_index: int) -> dict:
    """Delete a media item from a track."""
    bridge.call("MCP.delete_item", track, item_index)
    return {"track": track, "deleted_item": item_index}


def move_item_to_track(
    bridge: ReaperBridge, src_track, item_index: int, dest_track
) -> dict:
    """Move a media item to another track."""
    bridge.call("MCP.move_item_to_track", src_track, item_index, dest_track)
    return {"item_index": item_index, "dest_track": dest_track}


# -- Phase B: MIDI editing ---------------------------------------------------


def get_notes(bridge: ReaperBridge, track, item_index: int) -> list[dict]:
    """Read all MIDI notes from an item's active take (positions in quarter notes)."""
    return bridge.call("MCP.get_notes", track, item_index)


def add_notes(
    bridge: ReaperBridge, track, item_index: int, notes: list[dict]
) -> dict:
    """Append MIDI notes to an existing item. Each: {start_qn,end_qn,pitch,vel?,chan?}."""
    arrays = [
        [n["start_qn"], n["end_qn"], int(n["pitch"]),
         int(n.get("vel", 96)), int(n.get("chan", 0))]
        for n in notes
    ]
    count = _first(bridge.call("MCP.add_notes", track, item_index, arrays), 0)
    return {"added": count}


def set_note(
    bridge: ReaperBridge, track, item_index: int, note_index: int, fields: dict
) -> dict:
    """Edit a note. fields may include pitch, vel, start_qn, end_qn, chan, muted."""
    ok = _first(bridge.call("MCP.set_note", track, item_index, note_index, fields), False)
    return {"updated": bool(ok), "note_index": note_index}


def delete_note(
    bridge: ReaperBridge, track, item_index: int, note_index: int
) -> dict:
    """Delete a MIDI note by index."""
    ok = _first(bridge.call("MCP.delete_note", track, item_index, note_index), False)
    return {"deleted": bool(ok), "note_index": note_index}


# -- Phase B: markers & regions ----------------------------------------------


def add_marker(
    bridge: ReaperBridge, position: float, name: str = "",
    is_region: bool = False, region_end: float | None = None,
    rgb: list[int] | None = None,
) -> dict:
    """Add a marker (or region if is_region). Returns its index number."""
    idx = _first(
        bridge.call("MCP.add_marker", position, name, is_region,
                    region_end if region_end is not None else position, rgb),
        None,
    )
    return {"index": idx, "name": name, "is_region": is_region}


def delete_marker(bridge: ReaperBridge, index_number: int, is_region: bool = False) -> dict:
    """Delete a marker/region by its display index number."""
    ok = _first(bridge.call("MCP.delete_marker", index_number, is_region), False)
    return {"deleted": bool(ok), "index_number": index_number}


def list_markers(bridge: ReaperBridge) -> list[dict]:
    """List all markers and regions."""
    return bridge.call("MCP.list_markers")


def set_cursor(bridge: ReaperBridge, position: float, move_view: bool = False) -> dict:
    """Move the edit cursor to a project-time position (seconds)."""
    pos = _first(bridge.call("MCP.set_cursor", position, move_view), position)
    return {"cursor": pos}
