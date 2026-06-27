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
