# Reaper MCP Server

An [MCP](https://modelcontextprotocol.io) server for controlling the
[Reaper](https://www.reaper.fm/) DAW from Claude (or any MCP client).

## How it works

Reaper exposes no native external API — ReaScript only runs inside Reaper's main
(GUI) thread via a `defer()` loop. So this project bridges across that boundary
with files:

```
Claude (MCP client)
   │  stdio (MCP / JSON-RPC)
   ▼
Python MCP server  (server/, run with uv)
   │  writes  <id>.req.json   (atomic: tmp + rename)
   │  reads   <id>.resp.json
   ▼
~/Library/Application Support/REAPER/Scripts/mcp_bridge/
   ▲  reads request, writes response (atomic)
   │
Lua defer() loop  (bridge/reaper_mcp_bridge.lua, loaded in Reaper)
   │  reaper.<API>(...)
   ▼
Reaper DAW
```

- The Lua loop touches a `heartbeat` file every ~1s so the server can detect
  whether Reaper/the bridge is alive (clean errors instead of hangs).
- Requests carry a `calls` array, so a tool can batch several ReaScript calls
  into one round-trip — important because the defer loop caps throughput at
  ~30–60 round-trips/sec.

## Layout

| Path | What |
|------|------|
| `bridge/reaper_mcp_bridge.lua` | Persistent ReaScript loop run inside Reaper |
| `server/` | Python MCP server (uv project) |
| `server/reaper_mcp/bridge.py` | File transport (atomic IO, heartbeat, timeout) |
| `server/reaper_mcp/tools.py` | Tool implementations → ReaScript calls |
| `server/reaper_mcp/server.py` | MCP server (stdio), tool registration |

## Setup

See [`server/README.md`](server/README.md) for full setup and the client
config snippet. Quick version:

1. **Load the bridge in Reaper:** Actions → *Show action list* → *Load
   ReaScript…* → select `bridge/reaper_mcp_bridge.lua` → *Run*. A console
   message confirms it's running.
2. **Run the server:** `cd server && uv run reaper-mcp`
3. **Point your MCP client at it** (see `server/README.md`).

## Tools (40 and growing)

- **Escape hatch:** `call_reascript(fn, args)` — invoke any of the ~780 ReaScript
  functions directly (full API reachable).
- **Status/transport:** `reaper_status`, `transport_play/stop`, `get_play_state`,
  `set_tempo`, `set_time_selection`, `set_cursor`.
- **Tracks:** `list_tracks`, `add_track`, `delete_track`, `delete_all_tracks`,
  `get/set_track_name`, `set_track_volume` (dB), `set_track_mute`,
  `set_track_pan/solo/arm/color`, `move_track`, `set_folder_depth`.
- **Object model (Phase A):** `describe_project` (tree + GUIDs), `get_track_guid`.
  Track args accept an index **or** a GUID (GUIDs survive reorder/insert/delete).
- **Media items:** `set_item_bounds/fades`, `split_item`, `delete_item`,
  `move_item_to_track`.
- **MIDI:** `add_midi_clip`, `get_notes`, `add_notes`, `set_note`, `delete_note`.
- **FX:** `add_fx`.
- **Markers/regions:** `add_marker`, `delete_marker`, `list_markers`.
- **Render:** `render_mp3`.
- **Audio feedback:** `critique_render(path, ask?)` — Gemini "listens" and critiques.

Adding more tools is mostly Python-side work in `tools.py` / `server.py`. The Lua
bridge dispatches any `reaper.<fn>` dynamically; pointer-chaining operations live
as hot-reloadable composites in `bridge/mcp_helpers.lua` (reload via `MCP.reload`,
no Reaper restart). See `docs/ROADMAP.md` for what's next.
