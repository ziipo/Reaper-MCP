# Lessons Learned

A living log of tips, gotchas, and hard-won knowledge for the Reaper MCP project.
Two kinds of entries:

1. **Tooling** — how to use/build the MCP server effectively (architecture
   constraints, API quirks, workflow tips).
2. **Composition** — what we learn from actually trying to make music with the
   tool (what sounds good, what the tool makes easy/hard, Gemini feedback themes).

Add entries as we learn. Keep each one short, concrete, and dated. Newest first
within each section.

---

## Tooling lessons

### Bridge & architecture

- **Reaper has no native external API.** ReaScript only runs in Reaper's main GUI
  thread via a `defer()` loop. Everything caps at ~30–60 round-trips/sec. Batch
  calls (the bridge accepts a `calls` array) instead of chatty one-at-a-time.

- **Opaque pointers can't cross the file bridge.** MediaItem*, take, FX pointers
  serialize to `"<userdata>"`. Any operation that chains pointers must run
  entirely inside one Lua call — put it in `bridge/mcp_helpers.lua` as an `MCP.*`
  composite, and reference objects across the bridge by index/GUID, never pointer.

- **Two files, two reload rules:**
  - `bridge/mcp_helpers.lua` (composites) is **hot-reloadable** — call the
    `MCP.reload` bridge command, no Reaper restart. Put new logic here when you can.
  - `bridge/reaper_mcp_bridge.lua` (main loop) is **NOT** hot-reloadable —
    changing it requires the user to terminate + re-run the script in Reaper's
    Actions list. Batch main-file changes and ask for a single reload.

- **Heartbeat = liveness.** The Lua loop touches a `heartbeat` file ~1/sec. If
  it's stale/missing the Python side raises a clean "bridge not running" error
  instead of hanging. Call `reaper_status` first if anything seems off.

- **Async actions need polling, not fire-and-forget.** `render_mp3` triggers
  action 42230 and returns optimistically; it happened to be ready on our short
  renders, but large renders won't be. Render observability is a TODO (Phase D/E):
  poll `RENDER_TARGETS` / file existence before trusting completion.

- **Modal dialogs FREEZE the entire bridge** (2026-06-27). Any call that can pop a
  blocking dialog stalls Reaper's GUI thread → the defer loop stops → heartbeat
  goes stale → every subsequent call times out until a human dismisses the dialog.
  Hit live with:
  - `open_project` → "Save changes to current project?" prompt (froze the bridge).
  - `save_project` on an UNTITLED project → save-as dialog (now guarded: we require
    an explicit path and use `Main_SaveProjectEx`, which is dialog-free).
  Guidance: prefer dialog-free APIs (`Main_SaveProjectEx`). For `open_project`,
  save/clear the current project first, or open in a NEW tab (action 40859 then
  load) so there's nothing to prompt about. Treat any project-lifecycle op as
  potentially-blocking.
  - **Closing an UNSAVED tab also prompts** (action 40860 "Close project tab" →
    "save changes?"). Same freeze. Hit again during Phase F scratch cleanup. The
    Phase E watchdog (now live) caught it correctly and fast-failed with
    `BridgeFrozenError`. TODO: a dialog-free `close_tab` (mark project clean via
    `Main_SaveProjectEx(0,"",..)` or set the no-prompt flag before closing).
  - **The watchdog works:** instead of a generic timeout, mid-call freezes now
    raise `BridgeFrozenError` immediately with "dismiss the dialog" guidance.
  - **`IsProjectDirty()` LIES about unsaved edits** (2026-06-27). It returned 0
    right after inserting a track, yet closing the tab still prompted. So you
    cannot gate "is it safe to close?" on `IsProjectDirty`. The working
    `close_tab` (discard=true) therefore ALWAYS saves to a throwaway .rpp in
    `Scripts/mcp_bridge/scratch_tabs/` first (guaranteeing a clean close, no
    prompt), then deletes the throwaway after closing. This is the safe pattern
    for any scratch-tab teardown: save → close → delete. (Cost me several repeated
    freezes by trusting the dirty flag — diagnose by isolating the assumption
    next time instead of re-running the action that freezes.)

### Testing & verification

- **The fake-Lua responder does NOT catch real-API bugs.** Green pytest only
  proves the Python wrapper logic + arg plumbing; the fake is hand-written to
  match my *assumptions*. Two real bugs slipped past green tests and only showed
  up in a live sweep: the volume-envelope auto-create, and the JSON-null-arg bug
  below. **Always do a live sweep on a scratch tab before claiming a tool works.**

- **JSON `null` (from a Python `None` optional arg) was a truthy sentinel in Lua**
  (2026-06-27). Optional args sent as `None` arrived as a non-nil sentinel table,
  so `if args[n]` / `args[n] ~= nil` checks in helpers were wrong → e.g.
  `set_item_bounds(position=1.0)` (length omitted) crashed, and `add_marker`
  without `rgb` crashed in `ColorToNative`. Fixed systemically in the MAIN bridge
  via `normalize_args` (converts null sentinels to real Lua nil, tracks length in
  `.n`). Lesson: the fake passes real Python `None`, so it never reproduced this —
  only live did.

### API quirks discovered

- **`move_track` (ReorderSelectedTracks) is off-by-one moving downward.** The
  `beforeTrackIdx` arg is the slot the track is inserted *before*; when moving a
  track *down*, its own removal shifts later indices, so the landing spot can be
  one off. For deterministic absolute ordering, sequence `move_track` calls
  **front-to-back** (set index 0, then 1, then 2…). Documented in
  `mcp_helpers.lua: M.move_track`.

- **`D_VOL` is a linear amplitude factor, not dB** (1.0 == 0 dB). The curated
  `set_track_volume` tool takes dB and converts; raw `SetMediaTrackInfo_Value`
  with `D_VOL` does not.

- **`GetSetMediaTrackInfo_String` returns `(retval, string)`** (multi-return).
  The bridge captures all return values via `table.pack`, so results come back as
  a list — index `[1]` is the string for name reads.

- **`RENDER_FORMAT` accepts a 4-byte sink id for defaults** — `"l3pm"` = MP3
  (LAME) with default settings, no base64 config needed. Other formats: `"evaw"`
  (WAV). For non-default quality/bitrate you must build the base64 config (TODO).

- **MIDI positions: API speaks PPQ, we speak QN.** Notes are stored in PPQ
  internally; convert with `MIDI_GetPPQPosFromProjQN` / `MIDI_GetProjQNFromPPQPos`.
  Our tools expose quarter-note (QN) positions, which are tempo-independent and
  far easier to reason about. 1 bar of 4/4 = 4 QN.

### Robustness (Phase E)

- **Every mutating composite is now wrapped in an undo block** (dispatcher-level,
  via `Undo_BeginBlock2`/`EndBlock2`). So each tool action = one named, atomic
  Ctrl+Z step in Reaper. Read-only composites are listed in `READONLY_COMPOSITES`
  and skip undo. When adding a read-only composite, add it to that set.

- **Dialog watchdog:** `bridge.py` now watches the heartbeat *during* a call; if
  it goes stale mid-flight it raises `BridgeFrozenError` ("Reaper is likely
  showing a dialog — dismiss it") instead of waiting out the full timeout.

- **Structured error codes:** tool errors are prefixed with a code
  (`[NOT_FOUND]`, `[INVALID_ARG]`, `[BRIDGE_FROZEN]`, `[BRIDGE_DOWN]`,
  `[TIMEOUT]`, `[NEEDS_PATH]`, `[REAPER_ERROR]`) so the model can branch on the
  class instead of parsing prose.

- **Destructive ops are gated:** `delete_all_tracks` requires `confirm=True` and
  otherwise returns a preview of what would be deleted. Value ranges are clamped
  (pan -1..1, fx param 0..1) with a small-overshoot tolerance.

### Composition tools (Phase F)

- **Write music, not note numbers.** Prefer `add_chord_progression`
  (roman numerals in a key → diatonic chords), `add_scale_run`, `get_chord`,
  `get_scale` over hand-placing pitches. `quantize_notes` and `apply_swing`
  reshape an existing clip. Theory lives in `music.py` (pure, no Reaper).

- **C4 = 60** (Cockos convention). 1 bar of 4/4 = 4 QN.

### Workflow tips

- **`describe_project()` is the best first call** — one batched read returns the
  whole tree (tracks→items→fx) with GUIDs. Cheap context before doing anything.

- **Address tracks by GUID for anything that survives edits.** Indices shift on
  insert/delete/reorder; GUIDs don't. Get one via `get_track_guid` or from
  `describe_project`. Verified: a GUID still resolves correctly after a reorder.

- **Use `critique_render` to close the loop autonomously.** Render → send to
  Gemini → read its structured critique → adjust, without waiting for a human.
  Good for verifying audio changes before asking for human ears.

- **`call_reascript(fn, args)` is the escape hatch** for any of the ~780 API
  functions not yet wrapped. Track args accept index or GUID. For pointer
  chaining, add a composite instead.

---

## Composition lessons

*(Filled in as we actually make music with the tool.)*

- **The render→critique→adjust→verify loop genuinely works (2026-06-27).** Closed
  it fully: Gemini critiqued t001 (150–250 Hz mud, lacked high air) → applied the
  exact fixes with `set_fx_param` on ReaEQ (cut Gain-Band 2 to -1.9 dB, moved
  Band 3 to 6.4 kHz at +4.1 dB) → re-rendered (t005) → Gemini confirmed the mud
  cleared and high-end air improved "while preserving the warm lofi character."
  Takeaway: trust Gemini's frequency-specific suggestions; they map cleanly onto
  ReaEQ band moves. `list_fx_params` first to find the band names/indices.

- **ReaEQ band naming is predictable.** Params come as "Freq-/Gain-/BW-" per band
  ("Low Shelf", "Band 2", "Band 3", ...). `set_fx_param` matches by substring, so
  "Gain-Band 2" etc. work directly. Gain norm 0.5 = 0 dB; Freq is logarithmic.

- **Pitched ReaSynth hits make weak "drums."** In the first LoFi test (t001) we
  emulated a kit with single-pitch ReaSynth notes (kick=36, snare=38, hat=78).
  Gemini correctly heard them as synthy/beepy with soft transients. For
  believable drums, use a drum sampler (e.g. `ReaSamplOmatic5000` loaded with
  samples) or a drum VSTi — not a synth playing low notes.

- **Gemini's ears are usable and specific.** On t001 it accurately identified the
  warm pad character, the dark/muffled tone (our ReaEQ lowpass + ReaSynth), weak
  low-end transients, and 150–250 Hz mud — with concrete fixes (HPF at 100 Hz,
  6 kHz shelf, transient shaping). Trust it for mix-direction; it flags when it's
  unsure about exact pitch/tuning rather than guessing.

- **A static 4-bar loop reads as static.** Gemini noted t001 was very repetitive.
  Even subtle variation (fills, filter movement, a dropped element) helps the loop
  feel like music rather than a test pattern.
