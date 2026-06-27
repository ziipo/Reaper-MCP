# Reaper MCP — Development Roadmap

From the proven vertical slice to full Reaper control.

## Foundation (done)

- File-based JSON bridge: Python MCP server ⇄ Lua `defer()` loop in Reaper.
- Atomic IO, heartbeat liveness, bounded timeouts, request batching.
- Dynamic dispatch (`reaper.<fn>`) + composite helpers (`mcp_helpers.lua`) for
  pointer-chaining, hot-reloadable via `MCP.reload`.
- Slice tools: tracks (list/add/delete/name/vol/mute), transport, tempo, FX add,
  MIDI clip insert, time selection, MP3 render. Verified end-to-end (built a
  LoFi track + rendered `t001_lofi_test.mp3`).

## Decided strategy

- **Coverage:** generic passthrough (`call_reascript`) for 100% reachability
  **plus** a curated high-level layer for ergonomics. Not auto-generating all
  ~780 wrappers.
- **Priority domains:** (1) stable object model, (2) mixing/FX/automation.
- **Testing:** formalize a `tests/` suite now (pytest + fake-Lua responder +
  self-check ReaScript), grow it as tools are added.
- **Test outputs:** numbered `tNNN_` in `testProjects/`.

---

## Phase 0 — Passthrough + test harness (immediate)

- [ ] `call_reascript(fn, args)` generic tool → any `reaper.*` function.
      Document the opaque-pointer limitation (use composites for chaining).
- [ ] Promote scratchpad fake-Lua responder into `server/tests/` (pytest):
      transport, tools, dB conversion, error/timeout paths.
- [ ] `bridge/selftest.lua` — a ReaScript that exercises the bridge in-process
      and prints pass/fail to the console (catches API drift the fake can't).
- [ ] CI-style runner script (`make test` / `uv run pytest`).

## Phase A — Stable object model (foundational)

The enabler for everything else. Today references are integer indices that break
on insert/delete/reorder.

- [ ] GUID-based handles: resolve a reference by index **or** GUID server-side
      (`GetTrackGUID`, item/FX GUIDs). Selector grammar like
      `track[2].item[0].take[0].fx[1]` or `{"track":"guid:..."}`.
- [ ] Lua resolver layer that dereferences selectors → pointers; replaces the
      ad-hoc `TRACK_ARG_FNS` index map.
- [ ] `describe_project()` — one batched read returning the object tree
      (tracks→items→takes→fx, with GUIDs). Gives the LLM context cheaply.

## Phase B — Core editing breadth (mostly passthrough + thin composites)

- [ ] Tracks: reorder, color, folder depth, solo/arm/phase/pan/width, freeze.
- [ ] Media items: position/length/fades/gain, split, glue, move, loop, takes.
- [ ] MIDI editing: read/edit/delete notes, CC events, velocity, quantize, swing.
- [ ] Markers & regions: add/move/delete/enumerate, region render matrix.
- [ ] Time/transport: tempo map, time signatures, loop points, grid/snap, goto.

## Phase C — Mixing, FX & automation (priority; composite-heavy)

- [ ] FX graph: enumerate, get/set params **by name**, presets, chains, bypass.
- [ ] Instrument loading (VSTi), plugin discovery.
- [ ] Automation envelopes: create/read/write points, automation modes.
- [ ] Routing: full send/receive matrix, sidechain wiring (enables real
      LoFi-style sidechain pumping).

## Phase D — Render, project & I/O

- [ ] Render: format/bitrate control (build base64 `RENDER_FORMAT`), WAV/FLAC/
      stems, region rendering, normalization, render queue.
- [ ] Render **observability**: poll `RENDER_TARGETS`/file existence, detect
      in-progress, surface errors (current render returns optimistically).
- [ ] Project lifecycle: new/open/save/save-as, settings, `.rpp`, multi-tab.
- [ ] Media import: insert audio files, record-arm workflows.

## Phase E — Robustness & safety (woven through B–D)

- [ ] Undo integration: wrap mutating composites in `Undo_BeginBlock/EndBlock`.
- [ ] Error taxonomy: structured codes (not-found / invalid-arg / reaper-error).
- [ ] Throughput: auto-coalesce a tool's calls into batches; tune per-tick drain.
- [ ] Safety rails: confirm destructive ops (delete-all, render overwrite); clamp
      value ranges.

## Phase F — Higher-level musical affordances (high value for AI use)

- [ ] Theory helpers: chord/scale → MIDI, progressions, humanize/swing/quantize.
- [ ] Template macros: "make a lofi kit", "set up a vocal chain".
- [ ] Richer introspection built on `describe_project`.

---

## Sequencing

**Phase 0 → A → (B + E together) → C (priority) → D → F.**
E is ongoing, not a final pass. A unblocks everything; C is the stated priority
domain once addressing is stable.

## Known hard problems to keep in view

- **Opaque pointers** can't cross the file bridge → anything chaining them needs
  a composite in `mcp_helpers.lua`.
- **30–60 calls/sec ceiling** (Reaper's defer tick) → batch aggressively.
- **Async actions** (render, some commands) need polling, not fire-and-forget.
- **Index instability** → why Phase A (GUIDs) comes first.
