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

return M
