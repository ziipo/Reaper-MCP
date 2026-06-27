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
