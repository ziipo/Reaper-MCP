--[[
  mcp_helpers.lua

  Composite ReaScript helpers exposed under the "MCP." namespace and dispatched
  by reaper_mcp_bridge.lua. Split into its own file so the bridge can HOT-RELOAD
  it (via the MCP.reload command) without restarting the main defer loop.

  Each helper takes a plain Lua args array (decoded from JSON) and returns a
  JSON-safe table of values (no opaque userdata pointers).

  Operations that chain opaque pointers (MediaItem*, take) MUST live here so the
  pointer never has to cross the file bridge.

  This file returns a table M of helper functions.
]]--

local M = {}

------------------------------------------------------------------------
-- Object resolution
--
-- A track selector may be:
--   * an integer  -> 0-based track index (GetTrack)
--   * "guid:{...}" -> resolved by matching GetTrackGUID across all tracks
--   * "{...}"      -> a bare GUID string (same matching)
-- GUIDs make track references survive insert/delete/reorder, which integer
-- indices do not. Returns a MediaTrack* or nil.
------------------------------------------------------------------------
function M.resolve_track(sel)
  if type(sel) == "number" then
    return reaper.GetTrack(0, sel)
  end
  if type(sel) == "string" then
    local guid = sel:gsub("^guid:", "")
    -- master?
    local mtr = reaper.GetMasterTrack(0)
    if reaper.GetTrackGUID(mtr) == guid then return mtr end
    local n = reaper.CountTracks(0)
    for i = 0, n - 1 do
      local tr = reaper.GetTrack(0, i)
      if reaper.GetTrackGUID(tr) == guid then return tr end
    end
    return nil
  end
  return nil
end

-- Resolve an item selector { track_sel, item_index } -> MediaItem* or nil.
function M.resolve_item(track_sel, item_index)
  local tr = M.resolve_track(track_sel)
  if not tr then return nil end
  return reaper.GetTrackMediaItem(tr, item_index)
end

-- Create a MIDI item on a track and insert a list of notes.
-- args: { track_index, start_qn, end_qn, notes }
--   notes = array of { start_qn, end_qn, pitch, vel?, chan? }
-- Returns: { item_index_on_track, note_count }
function M.create_midi_item_with_notes(args)
  local tidx, start_qn, end_qn, notes = args[1], args[2], args[3], args[4]
  local track = reaper.GetTrack(0, tidx)
  if not track then error("no track at index " .. tostring(tidx)) end
  notes = notes or {}

  local start_t = reaper.TimeMap2_QNToTime(0, start_qn)
  local end_t = reaper.TimeMap2_QNToTime(0, end_qn)
  local item = reaper.CreateNewMIDIItemInProj(track, start_t, end_t, false)
  if not item then error("failed to create MIDI item") end
  local take = reaper.GetActiveTake(item)
  if not take then error("MIDI item has no take") end

  for _, n in ipairs(notes) do
    local n_start = n[1]
    local n_end = n[2]
    local pitch = n[3]
    local vel = n[4] or 96
    local chan = n[5] or 0
    local sppq = reaper.MIDI_GetPPQPosFromProjQN(take, n_start)
    local eppq = reaper.MIDI_GetPPQPosFromProjQN(take, n_end)
    reaper.MIDI_InsertNote(take, false, false, sppq, eppq, chan, pitch, vel, true)
  end
  reaper.MIDI_Sort(take)

  return { reaper.CountTrackMediaItems(track) - 1, #notes }
end

-- Add an FX (by name) to a track. args: { track_index, fx_name }
-- Returns: { fx_index } (>=0 on success, -1 if not found)
function M.add_fx(args)
  local tidx, name = args[1], args[2]
  local track = reaper.GetTrack(0, tidx)
  if not track then error("no track at index " .. tostring(tidx)) end
  local fx = reaper.TrackFX_AddByName(track, name, false, 1)
  return { fx }
end

-- Set an FX parameter by (normalized 0..1) value.
-- args: { track_index, fx_index, param_index, value }
function M.set_fx_param(args)
  local tidx, fxi, pidx, val = args[1], args[2], args[3], args[4]
  local track = reaper.GetTrack(0, tidx)
  if not track then error("no track at index " .. tostring(tidx)) end
  local ok = reaper.TrackFX_SetParamNormalized(track, fxi, pidx, val)
  return { ok }
end

-- Set the project tempo. args: { bpm }
function M.set_tempo(args)
  reaper.SetCurrentBPM(0, args[1], false)
  return { args[1] }
end

-- Set a loop/time selection. args: { start_sec, end_sec }
function M.set_time_selection(args)
  reaper.GetSet_LoopTimeRange2(0, true, false, args[1], args[2], false)
  return { args[1], args[2] }
end

-- Render the project to an MP3 file (no dialog).
-- args: { directory, filename, end_sec }
-- Returns: { full_path }
function M.render_mp3(args)
  local dir, fname, end_sec = args[1], args[2], args[3]
  reaper.RecursiveCreateDirectory(dir, 0)

  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", dir, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", fname, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", "l3pm", true) -- MP3 (LAME)
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)           -- master mix
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true)         -- custom bounds
  reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", 0.0, true)
  reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", end_sec, true)
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", 44100, true)
  reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", 2, true)
  reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0, true)

  reaper.Main_OnCommand(42230, 0) -- Render to disk, most recent settings

  local sep = package.config:sub(1, 1)
  return { dir .. sep .. fname }
end

------------------------------------------------------------------------
-- Phase A: project introspection (GUID-stamped object tree)
------------------------------------------------------------------------

-- Read the FX list for a track. Returns array of { index, name, enabled }.
local function track_fx_list(tr)
  local fx = {}
  local n = reaper.TrackFX_GetCount(tr)
  for i = 0, n - 1 do
    local _, name = reaper.TrackFX_GetFXName(tr, i, "")
    fx[#fx + 1] = {
      index = i,
      name = name,
      enabled = reaper.TrackFX_GetEnabled(tr, i),
    }
  end
  return fx
end

-- Read the media items for a track. Returns array of item descriptors.
local function track_items(tr)
  local items = {}
  local n = reaper.CountTrackMediaItems(tr)
  for i = 0, n - 1 do
    local it = reaper.GetTrackMediaItem(tr, i)
    local take = reaper.GetActiveTake(it)
    local take_name = ""
    local is_midi = false
    if take then
      local _, tn = reaper.GetSetMediaItemTakeInfo_String(take, "P_NAME", "", false)
      take_name = tn
      is_midi = reaper.TakeIsMIDI(take)
    end
    items[#items + 1] = {
      index = i,
      position = reaper.GetMediaItemInfo_Value(it, "D_POSITION"),
      length = reaper.GetMediaItemInfo_Value(it, "D_LENGTH"),
      muted = reaper.GetMediaItemInfo_Value(it, "B_MUTE") ~= 0,
      take_name = take_name,
      is_midi = is_midi,
    }
  end
  return items
end

-- Describe the whole project as a JSON-safe tree. args: { include_items?, include_fx? }
-- Defaults: both true. Each track carries its GUID for stable addressing.
function M.describe_project(args)
  args = args or {}
  local include_items = args[1]
  local include_fx = args[2]
  if include_items == nil then include_items = true end
  if include_fx == nil then include_fx = true end

  local _, proj_name = reaper.GetSetProjectInfo_String(0, "PROJECT_NAME", "", false)
  local tracks = {}
  local n = reaper.CountTracks(0)
  for i = 0, n - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    local amp = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
    local t = {
      index = i,
      guid = reaper.GetTrackGUID(tr),
      name = name,
      volume = amp,
      pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN"),
      muted = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE") ~= 0,
      soloed = reaper.GetMediaTrackInfo_Value(tr, "I_SOLO") ~= 0,
      armed = reaper.GetMediaTrackInfo_Value(tr, "I_RECARM") ~= 0,
      item_count = reaper.CountTrackMediaItems(tr),
      fx_count = reaper.TrackFX_GetCount(tr),
    }
    if include_items then t.items = track_items(tr) end
    if include_fx then t.fx = track_fx_list(tr) end
    tracks[#tracks + 1] = t
  end

  return { {
    name = proj_name,
    tempo = reaper.Master_GetTempo(),
    play_state = reaper.GetPlayState(),
    track_count = n,
    tracks = tracks,
  } }
end

-- Get a track's GUID by selector. args: { track_sel }
function M.get_track_guid(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  return { reaper.GetTrackGUID(tr) }
end

------------------------------------------------------------------------
-- Phase B: track editing
------------------------------------------------------------------------

-- Set a numeric track attribute. args: { track_sel, parmname, value }
function M.set_track_value(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  return { reaper.SetMediaTrackInfo_Value(tr, args[2], args[3]) }
end

-- Get a numeric track attribute. args: { track_sel, parmname }
function M.get_track_value(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  return { reaper.GetMediaTrackInfo_Value(tr, args[2]) }
end

-- Set track color from RGB. args: { track_sel, r, g, b }
function M.set_track_color(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  reaper.SetTrackColor(tr, reaper.ColorToNative(args[2], args[3], args[4]))
  return { true }
end

-- Move a track to a new index. args: { track_sel, dest_index }
-- Implemented via select-only + ReorderSelectedTracks.
-- NOTE: ReorderSelectedTracks' beforeTrackIdx is the slot the track is inserted
-- *before*, which behaves slightly differently when moving a track downward (the
-- removal shifts later indices). For deterministic absolute ordering, callers
-- can sequence move_track calls front-to-back (see set order in tests).
function M.move_track(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  reaper.SetOnlyTrackSelected(tr)
  reaper.ReorderSelectedTracks(args[2], 0)
  reaper.TrackList_AdjustWindows(false)
  return { true }
end

-- Set folder depth (1=start folder, 0=normal, -1=end folder). args: { track_sel, depth }
function M.set_folder_depth(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  reaper.SetMediaTrackInfo_Value(tr, "I_FOLDERDEPTH", args[2])
  reaper.TrackList_AdjustWindows(false)
  return { true }
end

------------------------------------------------------------------------
-- Phase B: media item editing (item addressed by { track_sel, item_index })
------------------------------------------------------------------------

-- Set item position+length. args: { track_sel, item_index, position?, length? }
function M.set_item_bounds(args)
  local it = M.resolve_item(args[1], args[2])
  if not it then error("no item at track/index") end
  if args[3] ~= nil then reaper.SetMediaItemPosition(it, args[3], false) end
  if args[4] ~= nil then reaper.SetMediaItemLength(it, args[4], false) end
  reaper.UpdateArrange()
  return { reaper.GetMediaItemInfo_Value(it, "D_POSITION"),
           reaper.GetMediaItemInfo_Value(it, "D_LENGTH") }
end

-- Set item fades. args: { track_sel, item_index, fadein_sec?, fadeout_sec? }
function M.set_item_fades(args)
  local it = M.resolve_item(args[1], args[2])
  if not it then error("no item at track/index") end
  if args[3] ~= nil then reaper.SetMediaItemInfo_Value(it, "D_FADEINLEN", args[3]) end
  if args[4] ~= nil then reaper.SetMediaItemInfo_Value(it, "D_FADEOUTLEN", args[4]) end
  reaper.UpdateArrange()
  return { true }
end

-- Split an item at a project-time position. args: { track_sel, item_index, position }
function M.split_item(args)
  local it = M.resolve_item(args[1], args[2])
  if not it then error("no item at track/index") end
  local right = reaper.SplitMediaItem(it, args[3])
  reaper.UpdateArrange()
  return { right ~= nil }
end

-- Delete an item. args: { track_sel, item_index }
function M.delete_item(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  local it = reaper.GetTrackMediaItem(tr, args[2])
  if not it then error("no item at index " .. tostring(args[2])) end
  reaper.DeleteTrackMediaItem(tr, it)
  reaper.UpdateArrange()
  return { true }
end

-- Move an item to another track. args: { src_track_sel, item_index, dest_track_sel }
function M.move_item_to_track(args)
  local it = M.resolve_item(args[1], args[2])
  if not it then error("no item at source track/index") end
  local dest = M.resolve_track(args[3])
  if not dest then error("no destination track") end
  reaper.MoveMediaItemToTrack(it, dest)
  reaper.UpdateArrange()
  return { true }
end

------------------------------------------------------------------------
-- Phase B: MIDI read/edit (operates on an item's active take)
------------------------------------------------------------------------

local function item_take(track_sel, item_index)
  local it = M.resolve_item(track_sel, item_index)
  if not it then error("no item at track/index") end
  local take = reaper.GetActiveTake(it)
  if not take or not reaper.TakeIsMIDI(take) then error("item take is not MIDI") end
  return take
end

-- Read all notes. args: { track_sel, item_index }
-- Returns array of { index, start_qn, end_qn, pitch, vel, chan, muted, selected }.
function M.get_notes(args)
  local take = item_take(args[1], args[2])
  local _, notecnt = reaper.MIDI_CountEvts(take)
  local notes = {}
  for i = 0, notecnt - 1 do
    local ok, sel, mute, sppq, eppq, chan, pitch, vel = reaper.MIDI_GetNote(take, i)
    if ok then
      notes[#notes + 1] = {
        index = i,
        start_qn = reaper.MIDI_GetProjQNFromPPQPos(take, sppq),
        end_qn = reaper.MIDI_GetProjQNFromPPQPos(take, eppq),
        pitch = pitch, vel = vel, chan = chan,
        muted = mute, selected = sel,
      }
    end
  end
  return notes
end

-- Delete a note by index. args: { track_sel, item_index, note_index }
function M.delete_note(args)
  local take = item_take(args[1], args[2])
  local ok = reaper.MIDI_DeleteNote(take, args[3])
  reaper.MIDI_Sort(take)
  return { ok }
end

-- Edit a note's pitch/vel/timing. args: { track_sel, item_index, note_index, fields }
-- fields = { pitch?, vel?, start_qn?, end_qn?, chan?, muted? } (nil = leave unchanged)
function M.set_note(args)
  local take = item_take(args[1], args[2])
  local idx = args[3]
  local f = args[4] or {}
  local sppq = f.start_qn and reaper.MIDI_GetPPQPosFromProjQN(take, f.start_qn) or nil
  local eppq = f.end_qn and reaper.MIDI_GetPPQPosFromProjQN(take, f.end_qn) or nil
  local ok = reaper.MIDI_SetNote(take, idx, f.selected, f.muted, sppq, eppq,
                                 f.chan, f.pitch, f.vel, true)
  reaper.MIDI_Sort(take)
  return { ok }
end

-- Add notes to an existing MIDI item. args: { track_sel, item_index, notes }
-- notes = array of { start_qn, end_qn, pitch, vel?, chan? }
function M.add_notes(args)
  local take = item_take(args[1], args[2])
  for _, n in ipairs(args[3] or {}) do
    local sppq = reaper.MIDI_GetPPQPosFromProjQN(take, n[1])
    local eppq = reaper.MIDI_GetPPQPosFromProjQN(take, n[2])
    reaper.MIDI_InsertNote(take, false, false, sppq, eppq, n[5] or 0, n[3], n[4] or 96, true)
  end
  reaper.MIDI_Sort(take)
  return { #(args[3] or {}) }
end

------------------------------------------------------------------------
-- Phase B: markers & regions
------------------------------------------------------------------------

-- Add a marker or region. args: { pos, name, is_region?, rgn_end?, color_rgb? }
-- Returns { marker_index }.
function M.add_marker(args)
  local pos = args[1]
  local name = args[2] or ""
  local is_rgn = args[3] or false
  local rgn_end = args[4] or pos
  local color = 0
  -- args[5] may be a real {r,g,b} array, or the JSON-null sentinel (a truthy
  -- empty table). Only treat it as a color if it actually has numeric channels.
  local c = args[5]
  if type(c) == "table" and type(c[1]) == "number" then
    color = reaper.ColorToNative(c[1], c[2], c[3]) | 0x1000000
  end
  local idx = reaper.AddProjectMarker2(0, is_rgn, pos, rgn_end, name, -1, color)
  return { idx }
end

-- Delete a marker/region by its display index number. args: { index_number, is_region? }
function M.delete_marker(args)
  return { reaper.DeleteProjectMarker(0, args[1], args[2] or false) }
end

-- List all markers and regions. Returns array of descriptors.
function M.list_markers(args)
  local out = {}
  local i = 0
  while true do
    local retval, isrgn, pos, rgnend, name, idx = reaper.EnumProjectMarkers(i)
    if retval == 0 then break end
    out[#out + 1] = {
      enum_index = i, number = idx, name = name,
      position = pos, region_end = rgnend, is_region = isrgn,
    }
    i = i + 1
  end
  return out
end

-- Move the edit cursor. args: { position, move_view? }
function M.set_cursor(args)
  reaper.SetEditCurPos(args[1], args[2] or false, false)
  return { reaper.GetCursorPosition() }
end

------------------------------------------------------------------------
-- Phase C: FX parameter control
------------------------------------------------------------------------

-- Find a parameter index by (case-insensitive substring) name. Returns -1 if
-- not found. Used so callers address params by name, not opaque index.
local function find_param(tr, fx, name)
  local lname = name:lower()
  local n = reaper.TrackFX_GetNumParams(tr, fx)
  for p = 0, n - 1 do
    local ok, pname = reaper.TrackFX_GetParamName(tr, fx, p, "")
    if ok and pname:lower():find(lname, 1, true) then
      return p, pname
    end
  end
  return -1, nil
end

-- List a track's FX with their parameters (names + current values).
-- args: { track_sel, fx_index }  -> { { index, name, value_norm, value, formatted } ... }
function M.list_fx_params(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  local fx = args[2]
  local n = reaper.TrackFX_GetNumParams(tr, fx)
  local params = {}
  for p = 0, n - 1 do
    local _, pname = reaper.TrackFX_GetParamName(tr, fx, p, "")
    local _, fmt = reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")
    local val, minv, maxv = reaper.TrackFX_GetParam(tr, fx, p)
    params[#params + 1] = {
      index = p, name = pname,
      value = val, min = minv, max = maxv,
      value_norm = reaper.TrackFX_GetParamNormalized(tr, fx, p),
      formatted = fmt,
    }
  end
  return params
end

-- Set an FX parameter by name (normalized 0..1).
-- args: { track_sel, fx_index, param_name, value_norm }
function M.set_fx_param_by_name(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  local pidx, pname = find_param(tr, args[2], args[3])
  if pidx < 0 then error("no param matching '" .. tostring(args[3]) .. "'") end
  reaper.TrackFX_SetParamNormalized(tr, args[2], pidx, args[4])
  local _, fmt = reaper.TrackFX_GetFormattedParamValue(tr, args[2], pidx, "")
  return { pidx, pname, fmt }
end

-- Enable/bypass an FX. args: { track_sel, fx_index, enabled }
function M.set_fx_enabled(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  reaper.TrackFX_SetEnabled(tr, args[2], args[3])
  return { reaper.TrackFX_GetEnabled(tr, args[2]) }
end

-- Delete an FX. args: { track_sel, fx_index }
function M.delete_fx(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  return { reaper.TrackFX_Delete(tr, args[2]) }
end

-- Apply a named preset. args: { track_sel, fx_index, preset_name }
function M.set_fx_preset(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  return { reaper.TrackFX_SetPreset(tr, args[2], args[3]) }
end

------------------------------------------------------------------------
-- Phase C: automation envelopes
--
-- Envelopes are addressed as the FX-param envelope on a track (the most common
-- case) or a named track envelope ("Volume", "Pan", "Mute"). The TrackEnvelope
-- pointer never crosses the bridge; we resolve + write points in one call.
-- Point times are in PROJECT SECONDS; values are envelope-native (e.g. 0..1
-- normalized for FX params; for Volume the value is the linear amplitude).
------------------------------------------------------------------------

-- Built-in track envelopes don't auto-create via GetTrackEnvelopeByName. Map the
-- common ones to the action that makes them visible (which creates them), then
-- fetch by name. FX-param envelopes DO auto-create via GetFXEnvelope.
local BUILTIN_ENV_ACTION = {
  Volume = 40406,  -- Track: Toggle track volume envelope visible
  Pan = 40407,     -- Track: Toggle track pan envelope visible
  Mute = 40867,    -- Track: Toggle track mute envelope visible
}

local function resolve_env(track_sel, spec)
  local tr = M.resolve_track(track_sel)
  if not tr then error("no track for selector " .. tostring(track_sel)) end
  -- spec = { "fx", fx_index, param_name } | { "track", name }
  if spec[1] == "fx" then
    local fx = spec[2]
    local pname = spec[3]
    local pidx = find_param(tr, fx, pname)
    if pidx < 0 then error("no param matching '" .. tostring(pname) .. "'") end
    return reaper.GetFXEnvelope(tr, fx, pidx, true) -- create if missing
  else
    local name = spec[2]
    local env = reaper.GetTrackEnvelopeByName(tr, name)
    if not env and BUILTIN_ENV_ACTION[name] then
      -- Create it by toggling visibility on this track.
      reaper.SetOnlyTrackSelected(tr)
      reaper.Main_OnCommand(BUILTIN_ENV_ACTION[name], 0)
      env = reaper.GetTrackEnvelopeByName(tr, name)
    end
    return env
  end
end

-- Write a set of automation points to an envelope (replacing the time range
-- they span). args: { track_sel, env_spec, points }
--   env_spec: { "fx", fx_index, param_name } or { "track", "Volume" }
--   points: array of { time_sec, value, shape? } (shape default 0 = linear)
function M.write_envelope(args)
  local env = resolve_env(args[1], args[2])
  if not env then error("envelope not found/creatable") end
  local pts = args[3] or {}
  if #pts == 0 then return { 0 } end
  -- clear the spanned range first for a clean overwrite
  local tmin, tmax = pts[1][1], pts[1][1]
  for _, p in ipairs(pts) do
    if p[1] < tmin then tmin = p[1] end
    if p[1] > tmax then tmax = p[1] end
  end
  reaper.DeleteEnvelopePointRange(env, tmin - 1e-9, tmax + 1e-9)
  for _, p in ipairs(pts) do
    reaper.InsertEnvelopePoint(env, p[1], p[2], p[3] or 0, 0, false, true)
  end
  reaper.Envelope_SortPoints(env)
  return { #pts }
end

-- Read all points of an envelope. args: { track_sel, env_spec }
function M.read_envelope(args)
  local env = resolve_env(args[1], args[2])
  if not env then error("envelope not found") end
  local n = reaper.CountEnvelopePoints(env)
  local pts = {}
  for i = 0, n - 1 do
    local ok, t, v, shape = reaper.GetEnvelopePoint(env, i)
    if ok then pts[#pts + 1] = { index = i, time = t, value = v, shape = shape } end
  end
  return pts
end

------------------------------------------------------------------------
-- Phase C: sends / routing
-- category: 0=track send, -1=receive, 1=hardware output.
------------------------------------------------------------------------

-- Create a send from src track to dest track. args: { src_sel, dest_sel }
-- Returns { send_index }.
function M.add_send(args)
  local src = M.resolve_track(args[1])
  local dest = M.resolve_track(args[2])
  if not src or not dest then error("source or dest track not found") end
  return { reaper.CreateTrackSend(src, dest) }
end

-- Set a send parameter. args: { src_sel, send_index, parmname, value }
-- common parms: D_VOL (amp), D_PAN (-1..1), B_MUTE, I_SRCCHAN, I_DSTCHAN.
function M.set_send_value(args)
  local src = M.resolve_track(args[1])
  if not src then error("source track not found") end
  return { reaper.SetTrackSendInfo_Value(src, 0, args[2], args[3], args[4]) }
end

-- List sends on a track. args: { src_sel } -> { { index, name, volume, pan } ... }
function M.list_sends(args)
  local src = M.resolve_track(args[1])
  if not src then error("source track not found") end
  local n = reaper.GetTrackNumSends(src, 0)
  local sends = {}
  for i = 0, n - 1 do
    local _, name = reaper.GetTrackSendName(src, i)
    sends[#sends + 1] = {
      index = i, name = name,
      volume = reaper.GetTrackSendInfo_Value(src, 0, i, "D_VOL"),
      pan = reaper.GetTrackSendInfo_Value(src, 0, i, "D_PAN"),
    }
  end
  return sends
end

-- Remove a send. args: { src_sel, send_index }
function M.remove_send(args)
  local src = M.resolve_track(args[1])
  if not src then error("source track not found") end
  return { reaper.RemoveTrackSend(src, 0, args[2]) }
end

------------------------------------------------------------------------
-- Phase D: render (format control + observability) and project I/O
------------------------------------------------------------------------

-- 4-byte sink ids for "default settings" of each format.
local FORMAT_SINK = {
  mp3 = "l3pm",   -- MP3 (LAME)
  wav = "evaw",   -- WAV
  flac = "calf",  -- FLAC
}

-- Render the project to a file with a chosen format, then verify the output
-- exists (render is otherwise fire-and-forget). args:
--   { directory, filename, end_sec, format, srate?, channels? }
-- Returns { full_path, exists, targets } so callers don't have to guess success.
function M.render(args)
  local dir, fname, end_sec = args[1], args[2], args[3]
  local format = (args[4] or "mp3"):lower()
  local sink = FORMAT_SINK[format]
  if not sink then error("unsupported format: " .. tostring(format)) end
  local srate = args[5] or 44100
  local channels = args[6] or 2

  reaper.RecursiveCreateDirectory(dir, 0)
  reaper.GetSetProjectInfo_String(0, "RENDER_FILE", dir, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_PATTERN", fname, true)
  reaper.GetSetProjectInfo_String(0, "RENDER_FORMAT", sink, true)
  reaper.GetSetProjectInfo(0, "RENDER_SETTINGS", 0, true)   -- master mix
  reaper.GetSetProjectInfo(0, "RENDER_BOUNDSFLAG", 0, true) -- custom bounds
  reaper.GetSetProjectInfo(0, "RENDER_STARTPOS", 0.0, true)
  reaper.GetSetProjectInfo(0, "RENDER_ENDPOS", end_sec, true)
  reaper.GetSetProjectInfo(0, "RENDER_SRATE", srate, true)
  reaper.GetSetProjectInfo(0, "RENDER_CHANNELS", channels, true)
  reaper.GetSetProjectInfo(0, "RENDER_ADDTOPROJ", 0, true)

  -- What files WILL be written (observability before/after).
  local _, targets = reaper.GetSetProjectInfo_String(0, "RENDER_TARGETS", "", false)

  -- 42230 = File: Render project to disk, using the most recent render settings.
  reaper.Main_OnCommand(42230, 0)

  local sep = package.config:sub(1, 1)
  local full = dir .. sep .. fname
  -- Verify the file now exists on disk (render is synchronous for our short
  -- jobs; for long renders a caller can poll file existence separately).
  local f = io.open(full, "rb")
  local exists = f ~= nil
  if f then f:close() end
  return { full, exists, targets }
end

-- Check whether a path exists on disk (poll helper for long renders).
-- args: { path }
function M.file_exists(args)
  local f = io.open(args[1], "rb")
  if f then f:close(); return { true } end
  return { false }
end

-- Save the current project. args: { path? }
-- If `path` (a full .rpp path) is given, saves there WITHOUT a dialog via
-- Main_SaveProjectEx. If omitted and the project already has a file, saves in
-- place. If omitted and the project is untitled, we DO NOT call the API (that
-- would pop a blocking save-as dialog and hang the bridge) — we error instead so
-- the caller supplies a path.
function M.save_project(args)
  local path = args[1]
  if path and #path > 0 then
    reaper.Main_SaveProjectEx(0, path, 0)
  else
    local cur = reaper.GetProjectName(0, "")
    if cur == "" then
      error("project is untitled; pass an explicit .rpp path to save (an " ..
            "in-place save would open a blocking dialog)")
    end
    reaper.Main_SaveProjectEx(0, "", 0) -- save in place, no dialog
  end
  return { reaper.GetProjectName(0, ""), reaper.GetProjectPath("") }
end

-- List all open project tabs (so callers can navigate without poking opaque
-- pointers across the bridge). Returns array of { tab, name, track_count }.
function M.list_tabs(args)
  local out = {}
  local i = 0
  while true do
    local proj = reaper.EnumProjects(i)
    if not proj then break end
    out[#out + 1] = {
      tab = i,
      name = reaper.GetProjectName(proj, ""),
      track_count = reaper.CountTracks(proj),
    }
    i = i + 1
  end
  return out
end

-- Switch the active project tab by index. args: { tab_index }
function M.switch_tab(args)
  local proj = reaper.EnumProjects(args[1])
  if not proj then error("no project tab " .. tostring(args[1])) end
  reaper.SelectProjectInstance(proj)
  return { reaper.GetProjectName(0, "") }
end

-- Close a project tab WITHOUT a save-changes dialog (which would freeze the
-- bridge). args: { tab_index?, discard? }
--   tab_index: which tab (default current/active).
--   discard:   if true (default), a DIRTY project is auto-handled: save it to a
--              throwaway .rpp in the bridge's scratch area, close the now-clean
--              tab (no prompt), then DELETE the throwaway file. A clean project
--              just closes. If false and the project is dirty, we error rather
--              than risk a freeze.
function M.close_tab(args)
  local idx = args[1]
  local discard = args[2]
  if discard == nil then discard = true end
  if idx ~= nil then
    local proj = reaper.EnumProjects(idx)
    if not proj then error("no project tab " .. tostring(idx)) end
    reaper.SelectProjectInstance(proj)
  end

  -- IMPORTANT: IsProjectDirty() does NOT reliably report unsaved edits (it
  -- returned 0 right after inserting a track in testing), yet the close action
  -- still prompts. So when discard=true we UNCONDITIONALLY save to a throwaway
  -- .rpp first — that guarantees the project has a saved file and closes silently
  -- — then delete the throwaway after closing.
  local scratch_files = nil
  if discard then
    local sep = package.config:sub(1, 1)
    local dir = reaper.GetResourcePath() .. sep .. "Scripts" .. sep ..
                "mcp_bridge" .. sep .. "scratch_tabs"
    reaper.RecursiveCreateDirectory(dir, 0)
    local base = dir .. sep .. "close_" ..
                 tostring(reaper.time_precise()):gsub("%.", "_")
    local rpp = base .. ".rpp"
    reaper.Main_SaveProjectEx(0, rpp, 0)
    scratch_files = { rpp, base .. "-prox.rpp" }
  end

  reaper.Main_OnCommand(40860, 0) -- Close current tab (saved → no prompt)

  -- Delete the throwaway save artifacts (best-effort; ignore failures).
  if scratch_files then
    for _, f in ipairs(scratch_files) do os.remove(f) end
  end
  return { true }
end

-- Get project name + path + change count. args: {}
function M.project_info(args)
  return { {
    name = reaper.GetProjectName(0, ""),
    path = reaper.GetProjectPath(""),
    change_count = reaper.GetProjectStateChangeCount(0),
  } }
end

-- Create a new empty project in a new tab. args: {}
function M.new_project(args)
  reaper.Main_OnCommand(40859, 0) -- New project tab
  return { true }
end

-- Open a project file. args: { full_path, new_tab?, prompt_save? }
-- IMPORTANT: by default we prefix 'noprompt:' so opening never pops a blocking
-- "save changes?" dialog (which would freeze the bridge). Set prompt_save=true to
-- restore the prompt. new_tab=true opens in a fresh tab (also avoids prompting).
function M.open_project(args)
  local path = args[1]
  local new_tab = args[2]
  local prompt_save = args[3]
  if new_tab then
    reaper.Main_OnCommand(40859, 0) -- New project tab first
  end
  local name = path
  if not prompt_save then name = "noprompt:" .. name end
  reaper.Main_openProject(name)
  return { reaper.GetProjectName(0, "") }
end

-- Select only the given track (exclusive). args: { track_sel }
function M.select_track(args)
  local tr = M.resolve_track(args[1])
  if not tr then error("no track for selector " .. tostring(args[1])) end
  reaper.SetOnlyTrackSelected(tr)
  return { true }
end

-- Insert a media file at the edit cursor. args: { file_path, track_sel?, mode? }
-- If track_sel is given, that track is selected first so the media lands there.
-- mode 0 = add to current track (default).
function M.insert_media(args)
  if args[2] ~= nil then
    local tr = M.resolve_track(args[2])
    if tr then reaper.SetOnlyTrackSelected(tr) end
  end
  return { reaper.InsertMedia(args[1], args[3] or 0) }
end

return M
