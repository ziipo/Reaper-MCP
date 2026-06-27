# Tests

Two layers:

## 1. Python suite (no Reaper required)

`pytest` tests run the real transport (`bridge.py`) and tool (`tools.py`) code
against a **fake Lua responder** (`conftest.py`) that models ReaScript in Python.
Fast, deterministic, runs in CI.

```bash
cd server
uv run pytest -q
```

Covers: transport (single/batch/error/timeout/down-detection/orphan cleanup),
all curated tools, dB conversion, and the `call_reascript` passthrough.

## 2. Live Lua self-test (requires Reaper)

`bridge/selftest.lua` runs **inside Reaper** to verify the live ReaScript API and
composite helpers actually match what the bridge expects — catching API drift the
Python fake can't (renamed functions, changed return shapes, missing stock FX).

It operates on a throwaway project tab and closes it without saving, so your work
is untouched. Output (pass/fail + summary) goes to the ReaScript console.

Run it: Reaper → Actions → Load ReaScript… → `bridge/selftest.lua` → Run.
Run it after changing `mcp_helpers.lua` or after a Reaper version update.
