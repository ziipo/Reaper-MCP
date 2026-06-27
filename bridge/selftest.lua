--[[
  selftest.lua

  Run this inside Reaper (Actions > Load ReaScript) to verify that the ReaScript
  functions and composite helpers the MCP bridge relies on actually exist and
  behave as expected against the LIVE Reaper API. This catches API drift that the
  Python fake-Lua test suite cannot (e.g. a renamed function, a changed return
  shape, a missing FX).

  It works on a SCRATCH project tab so it never touches your real work: it opens
  a new project tab, runs its checks, then closes that tab without saving.

  Output goes to the ReaScript console (pass/fail per check + a summary).
]]--

local SEP = package.config:sub(1, 1)
local SCRIPT_DIR = ({ reaper.get_action_context() })[2]:match("^(.*[/\\])") or ""

local passed, failed = 0, 0
local function log(s) reaper.ShowConsoleMsg(s .. "\n") end
local function check(name, ok, detail)
  if ok then
    passed = passed + 1
    log("  PASS  " .. name)
  else
    failed = failed + 1
    log("  FAIL  " .. name .. (detail and ("  -- " .. tostring(detail)) or ""))
  end
end

-- Load the composite helpers exactly as the bridge does.
local function load_helpers()
  local path = SCRIPT_DIR .. "mcp_helpers.lua"
  local ok, result = pcall(dofile, path)
  if not ok or type(result) ~= "table" then
    return nil, tostring(result)
  end
  return result
end

reaper.ClearConsole()
log("=== Reaper MCP bridge self-test ===")

-- 1) Core API functions exist
local CORE = {
  "CountTracks", "GetTrack", "InsertTrackAtIndex", "DeleteTrack",
  "GetSetMediaTrackInfo_String", "SetMediaTrackInfo_Value",
  "GetMediaTrackInfo_Value", "Main_OnCommand", "GetPlayState",
  "TimeMap2_QNToTime", "CreateNewMIDIItemInProj", "GetActiveTake",
  "MIDI_GetPPQPosFromProjQN", "MIDI_InsertNote", "MIDI_Sort",
  "CountTrackMediaItems", "TrackFX_AddByName", "SetCurrentBPM",
  "GetSet_LoopTimeRange2", "GetSetProjectInfo", "GetSetProjectInfo_String",
  "RecursiveCreateDirectory", "EnumerateFiles", "time_precise",
}
for _, fn in ipairs(CORE) do
  check("reaper." .. fn .. " exists", type(reaper[fn]) == "function")
end

-- 2) Helpers load and expose the expected names
local MCP, herr = load_helpers()
check("mcp_helpers.lua loads", MCP ~= nil, herr)
if MCP then
  for _, h in ipairs({ "create_midi_item_with_notes", "add_fx", "set_tempo",
                       "set_time_selection", "render_mp3", "set_fx_param" }) do
    check("MCP." .. h .. " present", type(MCP[h]) == "function")
  end
end

-- 3) Behavioural checks on a SCRATCH project tab.
reaper.Main_OnCommand(40859, 0) -- New project tab
local scratch_ok = (reaper.CountTracks(0) == 0)
check("scratch tab is empty", scratch_ok)

-- insert a track and name it
reaper.InsertTrackAtIndex(0, true)
check("track inserted", reaper.CountTracks(0) == 1)
local tr = reaper.GetTrack(0, 0)
reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "selftest", true)
local _, nm = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
check("track name round-trips", nm == "selftest", nm)

-- volume set/get
reaper.SetMediaTrackInfo_Value(tr, "D_VOL", 0.5)
local v = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
check("D_VOL set/get", math.abs(v - 0.5) < 1e-6, v)

-- composite: MIDI item with notes
if MCP then
  local ok, res = pcall(MCP.create_midi_item_with_notes,
    { 0, 0.0, 4.0, { { 0.0, 1.0, 60, 96, 0 }, { 1.0, 2.0, 64, 90, 0 } } })
  check("MCP.create_midi_item_with_notes runs", ok, res)
  if ok then
    check("item created with 2 notes", res[2] == 2, res[2])
  end

  -- composite: add ReaSynth (stock instrument, should exist)
  local ok2, res2 = pcall(MCP.add_fx, { 0, "ReaSynth" })
  check("MCP.add_fx ReaSynth", ok2 and res2[1] and res2[1] >= 0, res2 and res2[1])

  -- composite: set tempo
  local ok3 = pcall(MCP.set_tempo, { 90 })
  check("MCP.set_tempo runs", ok3 and math.abs(reaper.Master_GetTempo() - 90) < 0.5)
end

-- 4) Close the scratch tab WITHOUT saving (40860 = Close current project tab).
reaper.Main_OnCommand(40860, 0)

log(string.format("\n=== %d passed, %d failed ===", passed, failed))
if failed == 0 then
  log("ALL GOOD — the live API matches what the bridge expects.")
else
  log("DRIFT DETECTED — fix the failing items before relying on the bridge.")
end
