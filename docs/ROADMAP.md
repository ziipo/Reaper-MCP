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

## Phase C — Mixing, FX & automation (DONE)

- [x] FX graph: `list_fx_params` (names/values/formatted), `set_fx_param` BY NAME
      (substring match), `set_fx_enabled` (bypass), `delete_fx`, `set_fx_preset`.
- [x] Automation envelopes: `write_envelope`/`read_envelope` for FX-param and
      built-in track envelopes (Volume/Pan/Mute, auto-created via toggle action).
- [x] Routing: `add_send`/`set_send_value`/`list_sends`/`remove_send`. (Sidechain
      = a send + the receiving FX's input; reachable now, curate a helper later.)
- [x] Verified the full render→critique→adjust→verify loop live (t005): applied
      Gemini's EQ suggestions via set_fx_param, Gemini confirmed the improvement.
- [ ] Instrument/plugin discovery enumeration — reachable via call_reascript; TODO.

## Verification status

**Full live sweep complete (2026-06-27):** all 61 tools tested against real
Reaper 7.75, not just the fake responder. The sweep caught 3 real bugs the unit
tests missed (JSON-null optional args, save_project dialog, open_project freeze) —
all fixed, with regression tests added. Lesson: modal dialogs freeze the entire
bridge; project-lifecycle ops now use dialog-free APIs. See `lessonsLearned.md`.

## Phase D — Render, project & I/O (DONE)

- [x] Render with format control: `render(dir, file, len, fmt)` for mp3/wav/flac
      (4-byte sink ids l3pm/evaw/calf — all verified on disk as t002/t003/t004).
- [x] Render **observability**: returns `exists` (file confirmed on disk) +
      `RENDER_TARGETS`; `file_exists` poll helper for long renders.
- [x] Project lifecycle: `save_project`, `project_info`, `new_project`,
      `open_project`. (save_project_as needs a dialog — TODO/deferred.)
- [x] Media import: `insert_media`.
- [ ] Stems / region rendering / bitrate via base64 RENDER_FORMAT — TODO (defaults
      only for now); reachable via call_reascript + GetSetProjectInfo.

## Phase E — Robustness & safety (DONE)

- [x] Undo integration: mutating composites wrapped in `Undo_BeginBlock2/EndBlock2`
      at the dispatcher (read-only ones in `READONLY_COMPOSITES` skip it).
- [x] Error taxonomy: tool errors prefixed with codes (`[NOT_FOUND]`,
      `[INVALID_ARG]`, `[BRIDGE_FROZEN]`, `[BRIDGE_DOWN]`, `[TIMEOUT]`, ...).
- [x] Dialog watchdog: `bridge.py` detects a stale heartbeat mid-call →
      `BridgeFrozenError` with "dismiss the dialog" (proven live).
- [x] Safety rails: `delete_all_tracks` needs `confirm=True` (+preview); pan/fx
      params clamped. Dialog-free `close_tab` (save-to-scratch → close → delete).
- [ ] Throughput auto-coalescing — deferred (batching is available manually).

## Phase F — Higher-level musical affordances (DONE)

- [x] Theory engine `music.py`: note/scale/chord/progression, humanize, swing.
- [x] Composition tools: `add_chord_progression`, `add_scale_run`, `get_chord`,
      `get_scale`, `quantize_notes`, `apply_swing`.
- [x] Validated live: generated ii-V-I-vi in F major; Gemini independently named
      the exact chords (Gm7-C7-Fmaj7-Dm7) and confirmed the voice leading (t006).
- [ ] Genre/template macros ("make a lofi kit") — natural next step on this base.

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
