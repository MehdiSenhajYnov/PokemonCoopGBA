--[[
  Pokémon Co-op Framework - Network Module (File-Based Version)

  Handles communication with the relay server via file I/O
  - No socket dependency required
  - Works with proxy.js that bridges files <-> TCP server
  - Same API as socket version for compatibility
]]

-- Simple JSON encoder/decoder for Lua
local JSON = {}

function JSON.encode(obj)
  local function encodeValue(val)
    local valType = type(val)

    if valType == "string" then
      -- Escape backslash FIRST, then other sequences
      return '"' .. val:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r'):gsub('\t', '\\t') .. '"'
    elseif valType == "number" then
      return tostring(val)
    elseif valType == "boolean" then
      return val and "true" or "false"
    elseif valType == "table" then
      local isArray = #val > 0
      local result = {}

      if isArray then
        for i, v in ipairs(val) do
          table.insert(result, encodeValue(v))
        end
        return "[" .. table.concat(result, ",") .. "]"
      else
        for k, v in pairs(val) do
          table.insert(result, '"' .. k .. '":' .. encodeValue(v))
        end
        return "{" .. table.concat(result, ",") .. "}"
      end
    elseif valType == "nil" then
      return "null"
    else
      error("Cannot encode type: " .. valType)
    end
  end

  return encodeValue(obj)
end

function JSON.decode(str)
  -- Remove leading/trailing whitespace
  str = str:match("^%s*(.-)%s*$")

  local pos = 1

  local function skip_whitespace()
    while pos <= #str and str:sub(pos, pos):match("%s") do
      pos = pos + 1
    end
  end

  local function decode_value()
    skip_whitespace()

    local char = str:sub(pos, pos)

    -- String
    if char == '"' then
      pos = pos + 1
      local start = pos
      while pos <= #str do
        if str:sub(pos, pos) == '"' and str:sub(pos - 1, pos - 1) ~= '\\' then
          local result = str:sub(start, pos - 1)
          -- Unescape in reverse order of encoding
          result = result:gsub('\\t', '\t'):gsub('\\r', '\r'):gsub('\\n', '\n'):gsub('\\"', '"'):gsub('\\\\', '\\')
          pos = pos + 1
          return result
        end
        pos = pos + 1
      end
      error("Unterminated string")

    -- Number
    elseif char:match("[%-0-9]") then
      local start = pos
      while pos <= #str and str:sub(pos, pos):match("[%-0-9.eE+]") do
        pos = pos + 1
      end
      return tonumber(str:sub(start, pos - 1))

    -- Boolean/null
    elseif str:sub(pos, pos + 3) == "true" then
      pos = pos + 4
      return true
    elseif str:sub(pos, pos + 4) == "false" then
      pos = pos + 5
      return false
    elseif str:sub(pos, pos + 3) == "null" then
      pos = pos + 4
      return nil

    -- Object
    elseif char == "{" then
      local obj = {}
      pos = pos + 1
      skip_whitespace()

      if str:sub(pos, pos) == "}" then
        pos = pos + 1
        return obj
      end

      while true do
        skip_whitespace()

        -- Key
        if str:sub(pos, pos) ~= '"' then
          error("Expected string key")
        end
        local key = decode_value()

        skip_whitespace()
        if str:sub(pos, pos) ~= ":" then
          error("Expected colon")
        end
        pos = pos + 1

        -- Value
        local value = decode_value()
        obj[key] = value

        skip_whitespace()
        local separator = str:sub(pos, pos)
        if separator == "}" then
          pos = pos + 1
          return obj
        elseif separator == "," then
          pos = pos + 1
        else
          error("Expected comma or closing brace")
        end
      end

    -- Array
    elseif char == "[" then
      local arr = {}
      pos = pos + 1
      skip_whitespace()

      if str:sub(pos, pos) == "]" then
        pos = pos + 1
        return arr
      end

      while true do
        table.insert(arr, decode_value())

        skip_whitespace()
        local separator = str:sub(pos, pos)
        if separator == "]" then
          pos = pos + 1
          return arr
        elseif separator == "," then
          pos = pos + 1
        else
          error("Expected comma or closing bracket")
        end
      end

    else
      error("Unexpected character: " .. char)
    end
  end

  return decode_value()
end

-- Network Module
local Network = {}

-- Resolve script directory for absolute file paths
local _scriptPath = debug.getinfo(1, "S").source:sub(2)
local _scriptDir = _scriptPath:match("(.*[/\\])") or ""

-- File paths (absolute, based on script location)
local OUTGOING_FILE = _scriptDir .. "client_outgoing.json"
local INCOMING_FILE = _scriptDir .. "client_incoming.json"
local STATUS_FILE = _scriptDir .. "client_status.json"

-- Internal state
local connected = false
local playerId = nil
local lastIncomingCheck = 0
local incomingBuffer = {}
local outgoingBuffer = {}

--[[
  Connect to server (via proxy)
  @param host string - Server hostname/IP (ignored, for API compatibility)
  @param port number - Server port (ignored, for API compatibility)
  @return boolean - True if connection successful
]]
function Network.connect(host, port)
  -- Create status file to signal proxy we want to connect
  local success = pcall(function()
    local file = io.open(STATUS_FILE, "w")
    if file then
      file:write(JSON.encode({
        action = "connect",
        host = host,
        port = port,
        timestamp = os.time()
      }))
      file:close()
    end
  end)

  if success then
    connected = true
    return true
  end

  return false
end

--[[
  Send message to server (via file)
  @param message table - Lua table to encode as JSON
  @return boolean - True if sent successfully
]]
function Network.send(message)
  if not connected then
    return false
  end

  -- Add to outgoing buffer (flushed by Network.flush())
  table.insert(outgoingBuffer, message)
  return true
end

--[[
  Flush outgoing buffer to file (call once per frame)
  Writes all queued messages as a JSON array for the proxy to read
  @return boolean - True if flushed successfully
]]
function Network.flush()
  if #outgoingBuffer == 0 then
    return true
  end

  -- Encode buffer to JSON array
  local success, jsonStr = pcall(function()
    return JSON.encode(outgoingBuffer)
  end)

  if not success then
    return false
  end

  -- Write to outgoing file (proxy will read it)
  local writeSuccess = pcall(function()
    local file = io.open(OUTGOING_FILE, "w")
    if file then
      file:write(jsonStr)
      file:close()
    else
      error("Cannot open outgoing file")
    end
  end)

  if writeSuccess then
    outgoingBuffer = {}
  end

  return writeSuccess
end

--[[
  Receive message from server (via file)
  @return table|nil - Decoded message or nil if no message available
]]
function Network.receive()
  if not connected then
    return nil
  end

  -- If buffer has messages, return next one
  if #incomingBuffer > 0 then
    return table.remove(incomingBuffer, 1)
  end

  -- Read incoming file (written by proxy as JSON array)
  local success, data = pcall(function()
    local file = io.open(INCOMING_FILE, "r")
    if not file then
      return nil
    end

    local content = file:read("*all")
    file:close()

    if content and #content > 0 then
      return content
    end
    return nil
  end)

  if not success or not data then
    return nil
  end

  -- Clear the file immediately (so we don't re-read)
  pcall(function()
    local file = io.open(INCOMING_FILE, "w")
    if file then
      file:write("")
      file:close()
    end
  end)

  -- Decode JSON
  local decodeSuccess, messages = pcall(function()
    return JSON.decode(data)
  end)

  if not decodeSuccess or not messages then
    return nil
  end

  -- If it's an array, buffer all messages
  if type(messages) == "table" and #messages > 0 then
    for _, msg in ipairs(messages) do
      table.insert(incomingBuffer, msg)
    end
  elseif type(messages) == "table" then
    -- Single object (backward compat)
    table.insert(incomingBuffer, messages)
  end

  -- Return first message from buffer
  if #incomingBuffer > 0 then
    return table.remove(incomingBuffer, 1)
  end

  return nil
end

--[[
  Check if connected to server
  @return boolean - True if connection active
]]
function Network.isConnected()
  return connected
end

--[[
  Disconnect from server
]]
function Network.disconnect()
  if connected then
    -- Write disconnect status
    pcall(function()
      local file = io.open(STATUS_FILE, "w")
      if file then
        file:write(JSON.encode({
          action = "disconnect",
          timestamp = os.time()
        }))
        file:close()
      end
    end)
  end

  connected = false
  playerId = nil

  -- Clean up files
  pcall(function()
    os.remove(OUTGOING_FILE)
    os.remove(INCOMING_FILE)
  end)
end

return Network
