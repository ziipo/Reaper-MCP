"""MCP server (stdio) exposing Reaper control tools backed by the file bridge."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import gemini, tools
from .bridge import BridgeError, ReaperBridge

mcp = FastMCP("reaper")
bridge = ReaperBridge()


def _guard(fn, *args, **kwargs):
    """Run a tool, converting bridge failures into clean MCP tool errors."""
    try:
        return fn(bridge, *args, **kwargs)
    except BridgeError as e:
        # Surfaced to the model as a tool error it can reason about / report.
        raise RuntimeError(f"Reaper bridge error: {e}") from e
    except ValueError as e:
        raise RuntimeError(str(e)) from e


@mcp.tool()
def call_reascript(fn: str, args: list | None = None) -> list:
    """Invoke any ReaScript function by name (escape hatch for full API coverage).

    `fn`: function name without the `reaper.` prefix (e.g. "CountTracks").
    `args`: positional arguments. Returns all Lua return values as a list.

    Note: opaque pointers can't cross the bridge. Pass a 0-based track INDEX for
    track-taking functions; for pointer chaining add a composite in mcp_helpers.lua.
    """
    return _guard(tools.call_reascript, fn, args)


@mcp.tool()
def reaper_status() -> dict:
    """Check whether the Reaper bridge is running and reachable."""
    age = bridge.heartbeat_age()
    return {
        "alive": bridge.is_alive(),
        "heartbeat_age_seconds": round(age, 2) if age is not None else None,
        "bridge_dir": str(bridge.bridge_dir),
    }


@mcp.tool()
def list_tracks() -> list[dict]:
    """List all tracks in the current project with index, name, volume (dB), and mute."""
    return _guard(tools.list_tracks)


@mcp.tool()
def add_track(name: str | None = None) -> dict:
    """Append a new track to the project, optionally naming it."""
    return _guard(tools.add_track, name=name)


@mcp.tool()
def delete_track(index: int) -> dict:
    """Delete the track at the given 0-based index."""
    return _guard(tools.delete_track, index)


@mcp.tool()
def delete_all_tracks() -> dict:
    """Delete every track in the current project."""
    return _guard(tools.delete_all_tracks)


@mcp.tool()
def get_track_name(index: int) -> str:
    """Get the name of the track at the given 0-based index."""
    return _guard(tools.get_track_name, index)


@mcp.tool()
def set_track_name(index: int, name: str) -> dict:
    """Set the name of the track at the given 0-based index."""
    return _guard(tools.set_track_name, index, name)


@mcp.tool()
def set_track_volume(index: int, volume_db: float) -> dict:
    """Set a track's volume in decibels (0 dB = unity). Index is 0-based."""
    return _guard(tools.set_track_volume, index, volume_db)


@mcp.tool()
def set_track_mute(index: int, muted: bool) -> dict:
    """Mute or unmute the track at the given 0-based index."""
    return _guard(tools.set_track_mute, index, muted)


@mcp.tool()
def transport_play() -> dict:
    """Start playback."""
    return _guard(tools.transport_play)


@mcp.tool()
def transport_stop() -> dict:
    """Stop playback."""
    return _guard(tools.transport_stop)


@mcp.tool()
def get_play_state() -> dict:
    """Get the current transport state (stopped/playing/paused/recording)."""
    return _guard(tools.get_play_state)


@mcp.tool()
def set_tempo(bpm: float) -> dict:
    """Set the project tempo in BPM."""
    return _guard(tools.set_tempo, bpm)


@mcp.tool()
def add_fx(index: int, fx_name: str) -> dict:
    """Add an FX/instrument by name (e.g. 'ReaSynth', 'ReaEQ') to a track."""
    return _guard(tools.add_fx, index, fx_name)


@mcp.tool()
def add_midi_clip(
    index: int, start_qn: float, end_qn: float, notes: list[dict]
) -> dict:
    """Create a MIDI clip on a track and fill it with notes.

    Positions in quarter-notes from project start. Each note:
    {"start_qn", "end_qn", "pitch" (0-127), "vel"? (0-127), "chan"? (0-15)}.
    """
    return _guard(tools.add_midi_clip, index, start_qn, end_qn, notes)


@mcp.tool()
def set_time_selection(start_sec: float, end_sec: float) -> dict:
    """Set the loop/time selection in seconds."""
    return _guard(tools.set_time_selection, start_sec, end_sec)


@mcp.tool()
def render_mp3(directory: str, filename: str, length_sec: float) -> dict:
    """Render the project (0..length_sec) to an MP3 at directory/filename."""
    return _guard(tools.render_mp3, directory, filename, length_sec)


# -- Phase A: introspection & addressing -------------------------------------
# Track selectors accept a 0-based index OR a GUID string (from describe_project
# / get_track_guid). GUIDs survive reorder/insert/delete.


@mcp.tool()
def describe_project(include_items: bool = True, include_fx: bool = True) -> dict:
    """Get the full project tree (tracks, items, FX) with stable GUIDs.

    Best first call to understand current project state. GUIDs from here can be
    passed as the `track` argument to most tools and survive edits/reorders.
    """
    return _guard(tools.describe_project, include_items, include_fx)


@mcp.tool()
def get_track_guid(track: object) -> str:
    """Get a track's stable GUID (pass index or existing GUID)."""
    return _guard(tools.get_track_guid, track)


# -- Phase B: track editing --------------------------------------------------


@mcp.tool()
def set_track_color(track: object, r: int, g: int, b: int) -> dict:
    """Set a track's color from RGB (0-255)."""
    return _guard(tools.set_track_color, track, r, g, b)


@mcp.tool()
def set_track_pan(track: object, pan: float) -> dict:
    """Set track pan (-1 left .. 0 center .. 1 right)."""
    return _guard(tools.set_track_pan, track, pan)


@mcp.tool()
def set_track_solo(track: object, soloed: bool) -> dict:
    """Solo or unsolo a track."""
    return _guard(tools.set_track_solo, track, soloed)


@mcp.tool()
def set_track_arm(track: object, armed: bool) -> dict:
    """Record-arm or disarm a track."""
    return _guard(tools.set_track_arm, track, armed)


@mcp.tool()
def move_track(track: object, dest_index: int) -> dict:
    """Move a track to a new 0-based position."""
    return _guard(tools.move_track, track, dest_index)


@mcp.tool()
def set_folder_depth(track: object, depth: int) -> dict:
    """Set folder depth: 1=start folder, 0=normal, -1=close folder."""
    return _guard(tools.set_folder_depth, track, depth)


# -- Phase B: media item editing ---------------------------------------------


@mcp.tool()
def set_item_bounds(
    track: object, item_index: int,
    position: float | None = None, length: float | None = None,
) -> dict:
    """Set a media item's position and/or length (seconds)."""
    return _guard(tools.set_item_bounds, track, item_index, position, length)


@mcp.tool()
def set_item_fades(
    track: object, item_index: int,
    fadein_sec: float | None = None, fadeout_sec: float | None = None,
) -> dict:
    """Set a media item's fade-in/out lengths (seconds)."""
    return _guard(tools.set_item_fades, track, item_index, fadein_sec, fadeout_sec)


@mcp.tool()
def split_item(track: object, item_index: int, position: float) -> dict:
    """Split a media item at a project-time position (seconds)."""
    return _guard(tools.split_item, track, item_index, position)


@mcp.tool()
def delete_item(track: object, item_index: int) -> dict:
    """Delete a media item from a track."""
    return _guard(tools.delete_item, track, item_index)


@mcp.tool()
def move_item_to_track(src_track: object, item_index: int, dest_track: object) -> dict:
    """Move a media item to another track."""
    return _guard(tools.move_item_to_track, src_track, item_index, dest_track)


# -- Phase B: MIDI editing ---------------------------------------------------


@mcp.tool()
def get_notes(track: object, item_index: int) -> list[dict]:
    """Read all MIDI notes from an item (positions in quarter notes)."""
    return _guard(tools.get_notes, track, item_index)


@mcp.tool()
def add_notes(track: object, item_index: int, notes: list[dict]) -> dict:
    """Append MIDI notes to an item. Each: {start_qn,end_qn,pitch,vel?,chan?}."""
    return _guard(tools.add_notes, track, item_index, notes)


@mcp.tool()
def set_note(track: object, item_index: int, note_index: int, fields: dict) -> dict:
    """Edit a note. fields: pitch, vel, start_qn, end_qn, chan, muted (any subset)."""
    return _guard(tools.set_note, track, item_index, note_index, fields)


@mcp.tool()
def delete_note(track: object, item_index: int, note_index: int) -> dict:
    """Delete a MIDI note by index."""
    return _guard(tools.delete_note, track, item_index, note_index)


# -- Phase B: markers & regions ----------------------------------------------


@mcp.tool()
def add_marker(
    position: float, name: str = "", is_region: bool = False,
    region_end: float | None = None, rgb: list[int] | None = None,
) -> dict:
    """Add a marker, or a region if is_region=True. Returns its index number."""
    return _guard(tools.add_marker, position, name, is_region, region_end, rgb)


@mcp.tool()
def delete_marker(index_number: int, is_region: bool = False) -> dict:
    """Delete a marker/region by its display index number."""
    return _guard(tools.delete_marker, index_number, is_region)


@mcp.tool()
def list_markers() -> list[dict]:
    """List all markers and regions."""
    return _guard(tools.list_markers)


@mcp.tool()
def set_cursor(position: float, move_view: bool = False) -> dict:
    """Move the edit cursor to a project-time position (seconds)."""
    return _guard(tools.set_cursor, position, move_view)


# -- Phase C: FX, automation, routing ----------------------------------------


@mcp.tool()
def list_fx_params(track: object, fx_index: int) -> list[dict]:
    """List an FX's parameters (names, values, formatted text). Use to find param names."""
    return _guard(tools.list_fx_params, track, fx_index)


@mcp.tool()
def set_fx_param(track: object, fx_index: int, param_name: str, value_norm: float) -> dict:
    """Set an FX parameter by name to a normalized 0..1 value."""
    return _guard(tools.set_fx_param, track, fx_index, param_name, value_norm)


@mcp.tool()
def set_fx_enabled(track: object, fx_index: int, enabled: bool) -> dict:
    """Enable or bypass an FX."""
    return _guard(tools.set_fx_enabled, track, fx_index, enabled)


@mcp.tool()
def delete_fx(track: object, fx_index: int) -> dict:
    """Remove an FX from a track."""
    return _guard(tools.delete_fx, track, fx_index)


@mcp.tool()
def set_fx_preset(track: object, fx_index: int, preset_name: str) -> dict:
    """Apply a named preset to an FX."""
    return _guard(tools.set_fx_preset, track, fx_index, preset_name)


@mcp.tool()
def write_envelope(track: object, env_spec: list, points: list[dict]) -> dict:
    """Write automation points to an envelope, overwriting the spanned range.

    env_spec: ["fx", fx_index, param_name] or ["track", "Volume"|"Pan"|"Mute"].
    Each point: {"time": seconds, "value": native, "shape"?: 0}. Volume value is
    linear amplitude (1.0 = unity); FX-param values are 0..1.
    """
    return _guard(tools.write_envelope, track, env_spec, points)


@mcp.tool()
def read_envelope(track: object, env_spec: list) -> list[dict]:
    """Read all points of an envelope (see write_envelope for env_spec)."""
    return _guard(tools.read_envelope, track, env_spec)


@mcp.tool()
def add_send(src_track: object, dest_track: object) -> dict:
    """Create a send from one track to another."""
    return _guard(tools.add_send, src_track, dest_track)


@mcp.tool()
def set_send_value(src_track: object, send_index: int, parmname: str, value: float) -> dict:
    """Set a send parameter (D_VOL amplitude, D_PAN -1..1, B_MUTE, I_SRCCHAN, I_DSTCHAN)."""
    return _guard(tools.set_send_value, src_track, send_index, parmname, value)


@mcp.tool()
def list_sends(src_track: object) -> list[dict]:
    """List a track's sends (destination name, volume, pan)."""
    return _guard(tools.list_sends, src_track)


@mcp.tool()
def remove_send(src_track: object, send_index: int) -> dict:
    """Remove a send by index."""
    return _guard(tools.remove_send, src_track, send_index)


# -- Phase D: render, project & I/O ------------------------------------------


@mcp.tool()
def render(directory: str, filename: str, length_sec: float,
           fmt: str = "mp3", srate: int = 44100, channels: int = 2) -> dict:
    """Render the project (0..length_sec) to mp3/wav/flac, verifying the output.

    Returns {path, exists, targets}. Prefer this over render_mp3 (kept for
    compatibility). `directory` must be absolute; `filename` should match `fmt`.
    """
    return _guard(tools.render, directory, filename, length_sec, fmt, srate, channels)


@mcp.tool()
def file_exists(path: str) -> dict:
    """Check whether a file exists on disk (useful to poll a long render)."""
    return _guard(tools.file_exists, path)


@mcp.tool()
def save_project(path: str | None = None) -> dict:
    """Save the project. Pass a full .rpp path to save there (no dialog); omit to
    save in place. Untitled projects require a path (avoids a blocking dialog)."""
    return _guard(tools.save_project, path)


@mcp.tool()
def project_info() -> dict:
    """Get the current project's name, path, and state-change count."""
    return _guard(tools.project_info)


@mcp.tool()
def new_project() -> dict:
    """Open a new, empty project in a new tab."""
    return _guard(tools.new_project)


@mcp.tool()
def open_project(path: str, new_tab: bool = True, prompt_save: bool = False) -> dict:
    """Open a project file (.rpp). Defaults are dialog-safe (new tab, no prompt)."""
    return _guard(tools.open_project, path, new_tab, prompt_save)


@mcp.tool()
def select_track(track: object) -> dict:
    """Exclusively select a track (by index or GUID)."""
    return _guard(tools.select_track, track)


@mcp.tool()
def insert_media(file_path: str, track: object = None, mode: int = 0) -> dict:
    """Insert a media file at the edit cursor, optionally onto a specific track."""
    return _guard(tools.insert_media, file_path, track, mode)


@mcp.tool()
def critique_render(path: str, ask: str | None = None) -> dict:
    """Send a rendered audio file to Gemini to "listen" and critique it.

    Without `ask`, returns a structured production critique (mix issues,
    arrangement, suggestions). With `ask`, answers a specific question about the
    audio (e.g. "is the kick too loud?", "what key is this in?").
    """
    try:
        return gemini.critique_audio(path, ask=ask)
    except gemini.GeminiError as e:
        raise RuntimeError(f"Gemini critique error: {e}") from e


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
