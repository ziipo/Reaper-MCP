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

## Tools (initial slice)

`reaper_status`, `list_tracks`, `add_track`, `get_track_name`,
`set_track_name`, `set_track_volume` (dB), `set_track_mute`, `transport_play`,
`transport_stop`, `get_play_state`.

This is a deliberately thin vertical slice that proves the whole pipeline.
Adding more tools is mostly Python-side work in `tools.py` / `server.py` — the
Lua bridge dispatches any `reaper.<fn>` dynamically, so it rarely needs changes.
