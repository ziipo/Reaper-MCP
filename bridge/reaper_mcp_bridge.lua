--[[
  reaper_mcp_bridge.lua

  Persistent ReaScript defer loop that bridges an external MCP server to Reaper.

  Transport: file-based JSON in <Reaper resource>/Scripts/mcp_bridge/
    - <id>.req.json   : request written by the Python server (atomic via tmp+rename)
    - <id>.resp.json  : response written by this script (atomic via tmp+rename)
    - heartbeat       : touched every tick so the server can detect liveness

  Request  : { "id": "<str>", "calls": [ { "fn": "GetPlayState", "args": [...] }, ... ] }
  Response : { "id": "<str>", "ok": true,  "results": [ [r1, r2, ...], ... ] }
           | { "id": "<str>", "ok": false, "error": "<message>", "results": [...] }

  Each call's result is the list of ALL Lua return values for that function
  (e.g. GetSetMediaTrackInfo_String returns {retval, stringNeedBig}).

  Track references: pass a track INDEX (integer, 0-based). The dispatcher resolves
  it to a MediaTrack* only for known track-taking functions (see TRACK_ARG below).

  Load once via: Actions > Show action list > Load ReaScript... > pick this file > Run.
  Stop via: Actions list > find this script > Terminate, or close Reaper.
]]--

------------------------------------------------------------------------
-- Paths
------------------------------------------------------------------------
local SEP = package.config:sub(1, 1) -- "/" on macOS/Linux
local BRIDGE_DIR = reaper.GetResourcePath() .. SEP .. "Scripts" .. SEP .. "mcp_bridge"
local HEARTBEAT = BRIDGE_DIR .. SEP .. "heartbeat"
local POLL_GLOB_EXT = ".req.json"

-- Ensure the bridge dir exists.
reaper.RecursiveCreateDirectory(BRIDGE_DIR, 0)

------------------------------------------------------------------------
-- Minimal JSON (encode + decode). Tailored to the simple request/response
-- contract above: objects, arrays, strings, numbers, booleans, null.
------------------------------------------------------------------------
local json = {}

do
  local escape_map = {
    ['"'] = '\\"', ['\\'] = '\\\\', ['\b'] = '\\b',
    ['\f'] = '\\f', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t',
  }
  local function escape_str(s)
    return (s:gsub('[%z\1-\31\\"]', function(c)
      return escape_map[c] or string.format('\\u%04x', c:byte())
    end))
  end

  -- Is this Lua table an array (1..n contiguous integer keys)?
  local function is_array(t)
    local n = 0
    for k in pairs(t) do
      if type(k) ~= "number" then return false end
      n = n + 1
    end
    return n == #t
  end

  local encode_value
  encode_value = function(v)
    local tv = type(v)
    if v == nil then
      return "null"
    elseif tv == "boolean" then
      return v and "true" or "false"
    elseif tv == "number" then
      -- Reaper handles doubles; keep integers clean, guard non-finite.
      if v ~= v or v == math.huge or v == -math.huge then return "null" end
      if math.type and math.type(v) == "integer" then return tostring(v) end
      if v == math.floor(v) and math.abs(v) < 1e15 then
        return string.format("%d", v)
      end
      return string.format("%.17g", v)
    elseif tv == "string" then
      return '"' .. escape_str(v) .. '"'
    elseif tv == "table" then
      if is_array(v) then
        local parts = {}
        for i = 1, #v do parts[i] = encode_value(v[i]) end
        return "[" .. table.concat(parts, ",") .. "]"
      else
        local parts = {}
        for k, val in pairs(v) do
          parts[#parts + 1] = '"' .. escape_str(tostring(k)) .. '":' .. encode_value(val)
        end
        return "{" .. table.concat(parts, ",") .. "}"
      end
    end
    return "null"
  end
  json.encode = encode_value
end

do
  -- Recursive-descent decoder. Returns value or (nil, errmsg).
  local decode_value
  local function skip_ws(s, i)
    local _, j = s:find("^[ \t\r\n]*", i)
    return (j or i - 1) + 1
  end

  local function decode_string(s, i)
    -- assumes s:sub(i,i) == '"'
    local buf, j = {}, i + 1
    while j <= #s do
      local c = s:sub(j, j)
      if c == '"' then
        return table.concat(buf), j + 1
      elseif c == "\\" then
        local nxt = s:sub(j + 1, j + 1)
        local m = { ['"'] = '"', ['\\'] = '\\', ['/'] = '/', b = '\b',
                    f = '\f', n = '\n', r = '\r', t = '\t' }
        if m[nxt] then
          buf[#buf + 1] = m[nxt]; j = j + 2
        elseif nxt == "u" then
          local hex = s:sub(j + 2, j + 5)
          local cp = tonumber(hex, 16) or 0
          -- Basic BMP handling; good enough for our payloads.
          if cp < 0x80 then
            buf[#buf + 1] = string.char(cp)
          elseif cp < 0x800 then
            buf[#buf + 1] = string.char(0xC0 + math.floor(cp / 0x40), 0x80 + cp % 0x40)
          else
            buf[#buf + 1] = string.char(
              0xE0 + math.floor(cp / 0x1000),
              0x80 + math.floor(cp / 0x40) % 0x40,
              0x80 + cp % 0x40)
          end
          j = j + 6
        else
          return nil, "bad escape"
        end
      else
        buf[#buf + 1] = c; j = j + 1
      end
    end
    return nil, "unterminated string"
  end

  decode_value = function(s, i)
    i = skip_ws(s, i)
    local c = s:sub(i, i)
    if c == '"' then
      return decode_string(s, i)
    elseif c == "{" then
      local obj = {}
      i = skip_ws(s, i + 1)
      if s:sub(i, i) == "}" then return obj, i + 1 end
      while true do
        i = skip_ws(s, i)
        local key, ni = decode_string(s, i)
        if not key then return nil, ni end
        ni = skip_ws(s, ni)
        if s:sub(ni, ni) ~= ":" then return nil, "expected ':'" end
        local val, nj = decode_value(s, ni + 1)
        if val == nil and nj and type(nj) == "string" then return nil, nj end
        obj[key] = val
        nj = skip_ws(s, nj)
        local d = s:sub(nj, nj)
        if d == "," then i = nj + 1
        elseif d == "}" then return obj, nj + 1
        else return nil, "expected ',' or '}'" end
      end
    elseif c == "[" then
      local arr = {}
      i = skip_ws(s, i + 1)
      if s:sub(i, i) == "]" then return arr, i + 1 end
      while true do
        local val, nj = decode_value(s, i)
        if val == nil and nj and type(nj) == "string" then return nil, nj end
        arr[#arr + 1] = val
        nj = skip_ws(s, nj)
        local d = s:sub(nj, nj)
        if d == "," then i = nj + 1
        elseif d == "]" then return arr, nj + 1
        else return nil, "expected ',' or ']'" end
      end
    elseif c == "t" then
      if s:sub(i, i + 3) == "true" then return true, i + 4 end
      return nil, "bad literal"
    elseif c == "f" then
      if s:sub(i, i + 4) == "false" then return false, i + 5 end
      return nil, "bad literal"
    elseif c == "n" then
      if s:sub(i, i + 3) == "null" then return json.null, i + 4 end
      return nil, "bad literal"
    else
      -- number
      local num = s:match("^%-?%d+%.?%d*[eE]?[%+%-]?%d*", i)
      if num and #num > 0 then
        return tonumber(num), i + #num
      end
      return nil, "unexpected char '" .. c .. "'"
    end
  end

  -- Sentinel so decoded JSON null is distinguishable from "missing key".
  json.null = setmetatable({}, { __tostring = function() return "null" end })

  json.decode = function(s)
    local ok, val, _ = pcall(decode_value, s, 1)
    if not ok then return nil, tostring(val) end
    if val == nil then return nil, "empty" end
    return val
  end
end

------------------------------------------------------------------------
-- File IO helpers (atomic write via tmp + os.rename)
------------------------------------------------------------------------
local function read_file(path)
  local f = io.open(path, "rb")
  if not f then return nil end
  local data = f:read("*a")
  f:close()
  return data
end

local function write_file_atomic(path, data)
  local tmp = path .. ".tmp"
  local f = io.open(tmp, "wb")
  if not f then return false end
  f:write(data)
  f:close()
  -- os.rename is atomic on the same filesystem; overwrite target if present.
  os.remove(path)
  return os.rename(tmp, path)
end

------------------------------------------------------------------------
-- Composite helpers (MCP.*) — HOT-RELOADABLE
--
-- The actual helper functions live in mcp_helpers.lua (next to this file) so
-- they can be reloaded without restarting the main defer loop. We dofile() it
-- on startup and again whenever the MCP.reload command is received (or, if
-- watch is enabled, when the helpers file's mtime changes).
------------------------------------------------------------------------
local SCRIPT_DIR = ({ reaper.get_action_context() })[2]:match("^(.*[/\\])") or ""
local HELPERS_PATH = SCRIPT_DIR .. "mcp_helpers.lua"

local MCP = {}

local function load_helpers()
  local ok, result = pcall(dofile, HELPERS_PATH)
  if not ok then
    reaper.ShowConsoleMsg("[mcp_bridge] helpers load FAILED: " .. tostring(result) .. "\n")
    return false, tostring(result)
  end
  if type(result) ~= "table" then
    return false, "mcp_helpers.lua did not return a table"
  end
  MCP = result
  reaper.ShowConsoleMsg("[mcp_bridge] helpers loaded from " .. HELPERS_PATH .. "\n")
  return true
end

-- Built-in commands that are NOT in the helpers file (so reload always works).
local BUILTIN = {}

-- Reload the helpers file. args: (none). Returns { "reloaded" } or errors.
function BUILTIN.reload(_)
  local ok, err = load_helpers()
  if not ok then error(err) end
  return { "reloaded" }
end

-- Liveness/info probe. Returns { helper_names... }
function BUILTIN.ping(_)
  local names = {}
  for k in pairs(MCP) do names[#names + 1] = k end
  table.sort(names)
  return { "pong", names }
end

load_helpers()

------------------------------------------------------------------------
-- Dispatch
------------------------------------------------------------------------
-- Functions whose Nth argument is a track index that must be resolved to a
-- MediaTrack*. Index is 0-based; nil/false means "no resolution" for that arg.
-- For our slice, the track is always the first argument when present.
local TRACK_ARG_FNS = {
  GetSetMediaTrackInfo_String = 1,
  SetMediaTrackInfo_Value = 1,
  GetMediaTrackInfo_Value = 1,
  GetTrackName = 1,
  DeleteTrack = 1,
  TrackFX_AddByName = 1,
  CreateNewMIDIItemInProj = 1,
}

local function resolve_track_sel(sel)
  -- Prefer the GUID-aware resolver from helpers; fall back to plain index.
  if type(MCP.resolve_track) == "function" then
    return MCP.resolve_track(sel)
  end
  if type(sel) == "number" then return reaper.GetTrack(0, sel) end
  return nil
end

local function resolve_args(fn, args)
  local idx = TRACK_ARG_FNS[fn]
  if not idx then return args end
  local n = args.n or #args
  local resolved = { n = n }
  for i = 1, n do resolved[i] = args[i] end
  local sel = resolved[idx]
  -- Accept an integer index OR a GUID string for the track argument.
  if type(sel) == "number" or type(sel) == "string" then
    resolved[idx] = resolve_track_sel(sel)
  end
  return resolved
end

-- Execute a single {fn=..., args=...} call. Returns ok, results_table_or_errmsg.
-- Convert any JSON-null sentinels in an args array to real Lua nil. Python sends
-- optional/omitted args as null; without this they arrive as a truthy sentinel
-- table and break `if args[n]` / `args[n] ~= nil` checks in helpers. We track the
-- original length in `.n` so trailing nils don't get lost to the `#` operator.
local function normalize_args(args)
  local n = 0
  for k in pairs(args) do
    if type(k) == "number" and k > n then n = k end
  end
  local out = { n = n }
  for i = 1, n do
    local v = args[i]
    if v ~= json.null then out[i] = v end -- leave nil for null/missing
  end
  return out
end

local function dispatch(call)
  local fn = call.fn
  if type(fn) ~= "string" then return false, "missing 'fn'" end

  local args = call.args or {}
  if type(args) ~= "table" then return false, "'args' must be an array" end
  args = normalize_args(args)

  -- Composite helpers (MCP.*) run pointer-chaining internally and return
  -- JSON-safe values. Checked before raw reaper.* lookup. BUILTIN commands
  -- (reload/ping) take precedence so reload works even if helpers are broken.
  local composite = fn:match("^MCP%.(.+)$")
  if composite then
    local cf = BUILTIN[composite] or MCP[composite]
    if type(cf) ~= "function" then return false, "unknown composite: " .. fn end
    local packed = table.pack(pcall(cf, args))
    if not packed[1] then return false, tostring(packed[2]) end
    return true, packed[2] or {}
  end

  local f = reaper[fn]
  if type(f) ~= "function" then return false, "unknown function: " .. fn end
  args = resolve_args(fn, args)

  -- table.pack captures all return values (incl. multi-return + trailing nils).
  local packed = table.pack(pcall(f, table.unpack(args, 1, args.n or #args)))
  local ok = packed[1]
  if not ok then
    return false, tostring(packed[2])
  end
  local results = {}
  for i = 2, packed.n do
    local v = packed[i]
    -- Drop userdata/opaque pointers from results (not JSON-serializable);
    -- callers reference tracks by index, not pointer.
    if type(v) == "userdata" then
      results[i - 1] = "<userdata>"
    else
      results[i - 1] = v
    end
  end
  return true, results
end

------------------------------------------------------------------------
-- Process one request file
------------------------------------------------------------------------
local function process_request_file(name)
  local req_path = BRIDGE_DIR .. SEP .. name
  local raw = read_file(req_path)
  os.remove(req_path) -- consume regardless of outcome to avoid reprocessing
  if not raw then return end

  local req, derr = json.decode(raw)
  local id = (type(req) == "table" and req.id) or name:gsub("%.req%.json$", "")
  local resp = { id = id }

  if not req or type(req) ~= "table" then
    resp.ok = false
    resp.error = "invalid request JSON: " .. tostring(derr)
  else
    local calls = req.calls
    if type(calls) ~= "table" then
      resp.ok = false
      resp.error = "request missing 'calls' array"
    else
      local results, ok_all, first_err = {}, true, nil
      for i = 1, #calls do
        local ok, res = dispatch(calls[i])
        if ok then
          results[i] = res
        else
          ok_all = false
          first_err = first_err or res
          results[i] = json.null
        end
      end
      resp.ok = ok_all
      resp.results = results
      if not ok_all then resp.error = first_err end
    end
  end

  local resp_path = BRIDGE_DIR .. SEP .. id .. ".resp.json"
  write_file_atomic(resp_path, json.encode(resp))
end

------------------------------------------------------------------------
-- Directory scan: list *.req.json files. Uses reaper.EnumerateFiles.
------------------------------------------------------------------------
local function scan_requests()
  local found = {}
  local i = 0
  while true do
    local fname = reaper.EnumerateFiles(BRIDGE_DIR, i)
    if not fname then break end
    if fname:sub(-#POLL_GLOB_EXT) == POLL_GLOB_EXT then
      found[#found + 1] = fname
    end
    i = i + 1
  end
  return found
end

------------------------------------------------------------------------
-- Main defer loop
------------------------------------------------------------------------
local last_heartbeat = 0

local function tick()
  -- Heartbeat (cheap; write at most ~once/sec to limit disk churn).
  local now = reaper.time_precise()
  if now - last_heartbeat >= 1.0 then
    write_file_atomic(HEARTBEAT, string.format("%.3f", now))
    last_heartbeat = now
  end

  -- Process any pending requests this tick (batch-drain the directory).
  local reqs = scan_requests()
  for _, name in ipairs(reqs) do
    local ok, err = pcall(process_request_file, name)
    if not ok then
      reaper.ShowConsoleMsg("[mcp_bridge] error processing " .. name .. ": " .. tostring(err) .. "\n")
    end
  end

  reaper.defer(tick)
end

local function shutdown()
  os.remove(HEARTBEAT)
end

reaper.atexit(shutdown)
reaper.ShowConsoleMsg("[mcp_bridge] running. dir=" .. BRIDGE_DIR .. "\n")
tick()
