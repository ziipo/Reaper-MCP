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

## Audio feedback loop (cross-cutting — accelerates ALL phases)

Borrowed wholesale from `abletest/abletonosc_cli/gemini.py` → lives at
`server/reaper_mcp/gemini.py`. Sends rendered audio to Gemini's audio-understanding
model so the agent can **"hear" its own renders** and self-critique without waiting
for human feedback. `GEMINI_API_KEY` comes from repo-root `.env`.

- `critique_audio(path, ask=?)` — structured JSON critique, or a free-form answer
  to a specific question (e.g. "is the kick too loud?", "what key is this in?").
- Inline base64, 20 MB ceiling (our short MP3 renders are tiny). Default model
  `gemini-3.5-flash`; `gemini-3.1-flash-lite` for cheap qualitative passes.

Why cross-cutting: any phase that produces audio (render, FX, mix changes) can
close the loop — render → critique → adjust — autonomously. Use it as a
verification step in the test harness and in iterative composition workflows.
- [ ] Expose as an MCP tool `critique_render(path, ask?)` so the model can call it.
- [ ] Use it internally during dev to validate audio changes before asking the human.

## Phase 0 — Passthrough + test harness (DONE)

- [x] `call_reascript(fn, args)` generic tool → any `reaper.*` function.
      Documents the opaque-pointer limitation (use composites for chaining).
- [x] Promoted scratchpad fake-Lua responder into `server/tests/` (pytest):
      transport, tools, dB conversion, error/timeout paths. 18 tests passing.
- [x] `bridge/selftest.lua` — a ReaScript that exercises the live API + helpers
      on a throwaway tab and prints pass/fail (catches drift the fake can't).
- [x] Borrowed `gemini.py` audio-feedback module + exposed `critique_render` tool.
      Verified live against t001 render.
- [x] Test runner: `cd server && uv run pytest -q`.

## Phase A — Stable object model (DONE)

The enabler for everything else. Track references now survive insert/delete/reorder.

- [x] GUID-based handles: `resolve_track` accepts an index **or** a GUID string;
      `resolve_item` = {track_sel, item_index}. Verified live (GUID survives reorder).
- [x] Lua resolver layer (`mcp_helpers.lua: resolve_track/resolve_item`); bridge
      `resolve_args` now accepts GUIDs for raw track functions too.
- [x] `describe_project(include_items?, include_fx?)` — object tree with GUIDs,
      FX names, item positions/MIDI flags. Verified on the LoFi project.

## Phase B — Core editing breadth (DONE)

- [x] Tracks: move/reorder, color (RGB), folder depth, solo/arm/pan, get/set value.
- [x] Media items: position/length, fades, split, delete, move to track.
- [x] MIDI editing: read/edit/delete/add notes (QN positions). (CC events: TODO.)
- [x] Markers & regions: add/delete/list, edit cursor. (Region render matrix: Phase D.)
- [ ] Time/transport tempo map / time signatures / grid-snap — partial (tempo done);
      remainder reachable now via `call_reascript`, curate as needed.

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
