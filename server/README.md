# reaper-mcp (server)

Python MCP server that controls Reaper through the file-based ReaScript bridge.

## Requirements

- Reaper, running.
- [`uv`](https://docs.astral.sh/uv/). The server needs Python ≥ 3.13; `uv`
  provisions it automatically (the macOS system Python 3.9 is too old).

## 1. Load the bridge inside Reaper

1. In Reaper: **Actions → Show action list → Load ReaScript…**
2. Select `bridge/reaper_mcp_bridge.lua` from this repo and **Run** it.
3. You should see `[mcp_bridge] running. dir=…/Scripts/mcp_bridge` in the
   ReaScript console. Keep Reaper open; the loop runs until you terminate the
   script or quit Reaper.

The bridge creates and watches:
`~/Library/Application Support/REAPER/Scripts/mcp_bridge/`

## 2. Install & run the server

```bash
cd server
uv sync            # creates the venv, installs the mcp SDK
uv run reaper-mcp  # starts the stdio MCP server
```

### Try it without a client (MCP Inspector)

```bash
cd server
uv run mcp dev reaper_mcp/server.py
```

This opens the Inspector UI where you can call `reaper_status`, `list_tracks`,
`transport_play`, etc. and watch Reaper respond.

## 3. Configure your MCP client

### Claude Code

```bash
claude mcp add reaper -- uv --directory /Users/kenburleson/Projects/reaperTest/server run reaper-mcp
```

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "reaper": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/kenburleson/Projects/reaperTest/server",
        "run",
        "reaper-mcp"
      ]
    }
  }
}
```

## Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `REAPER_MCP_BRIDGE_DIR` | `~/Library/Application Support/REAPER/Scripts/mcp_bridge` | Override the bridge data directory (must match what the Lua loop uses). |

## Troubleshooting

- **"Reaper bridge is not running (no heartbeat)"** — the Lua script isn't
  loaded/running. Re-run step 1 and check the ReaScript console.
- **"heartbeat is stale"** — the script was terminated or Reaper is frozen.
- **Timeouts** — Reaper is busy; the default per-call timeout is 5s.
- Call `reaper_status` first to confirm connectivity before other tools.

## Tests (no Reaper required)

The transport and tool layers are validated against a fake Lua responder in
`../scratchpad` test scripts during development. The real-Reaper checks are in
the repo's verification guide (top-level README + plan).
