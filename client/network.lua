--[[
  Pokémon Co-op Framework - Network Module (Direct TCP)

  Uses mGBA's built-in socket API (socket.tcp / socket.connect)
  No external proxy or file I/O needed.
  Protocol: JSON messages delimited by newline (\n)
]]

-- Simple JSON encoder/decoder for Lua
local JSON = {}

function JSON.encode(obj)
  local function encodeValue(val)
    local valType = type(val)

    if valType == "string" then
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

    if char == '"' then
      pos = pos + 1
      local start = pos
      while pos <= #str do
        if str:sub(pos, pos) == '"' and str:sub(pos - 1, pos - 1) ~= '\\' then
          local result = str:sub(start, pos - 1)
          result = result:gsub('\\t', '\t'):gsub('\\r', '\r'):gsub('\\n', '\n'):gsub('\\"', '"'):gsub('\\\\', '\\')
          pos = pos + 1
          return result
        end
        pos = pos + 1
      end
      error("Unterminated string")

    elseif char:match("[%-0-9]") then
      local start = pos
      while pos <= #str and str:sub(pos, pos):match("[%-0-9.eE+]") do
        pos = pos + 1
      end
      return tonumber(str:sub(start, pos - 1))

    elseif str:sub(pos, pos + 3) == "true" then
      pos = pos + 4
      return true
    elseif str:sub(pos, pos + 4) == "false" then
      pos = pos + 5
      return false
    elseif str:sub(pos, pos + 3) == "null" then
      pos = pos + 4
      return nil

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

        if str:sub(pos, pos) ~= '"' then
          error("Expected string key")
        end
        local key = decode_value()

        skip_whitespace()
        if str:sub(pos, pos) ~= ":" then
          error("Expected colon")
        end
        pos = pos + 1

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

-- Internal state
local sock = nil
local connected = false
local receiveBuffer = ""      -- Raw bytes buffer for incomplete lines
local incomingMessages = {}   -- Decoded messages ready to be consumed
local outgoingBuffer = {}     -- Messages queued for sending

-- Reconnection state
local reconnectAttempts = 0
local maxReconnectAttempts = 10
local reconnectBaseDelay = 1000  -- ms (1 second)
local reconnectNextTime = 0     -- timeMs at which next reconnect attempt is allowed
local reconnecting = false
local lastHost = nil
local lastPort = nil

--[[
  Connect to TCP server using mGBA built-in socket API
  Note: socket.connect() is BLOCKING - mGBA freezes until connected or timeout
]]
function Network.connect(host, port)
  lastHost = host
  lastPort = port

  local success, err = pcall(function()
    sock = socket.connect(host, port)
  end)

  if success and sock then
    connected = true
    reconnectAttempts = 0
    reconnecting = false

    -- Register receive callback (fires once per frame when data available)
    sock:add("received", function()
      local data, recvErr = sock:receive(4096)
      if data then
        receiveBuffer = receiveBuffer .. data

        -- Process complete lines (newline-delimited JSON)
        local lineEnd = receiveBuffer:find("\n")
        while lineEnd do
          local line = receiveBuffer:sub(1, lineEnd - 1):match("^%s*(.-)%s*$")
          receiveBuffer = receiveBuffer:sub(lineEnd + 1)

          if #line > 0 then
            local ok, message = pcall(JSON.decode, line)
            if ok and message then
              table.insert(incomingMessages, message)
            end
          end

          lineEnd = receiveBuffer:find("\n")
        end
      elseif recvErr then
        -- Connection lost during receive
        connected = false
      end
    end)

    -- Register error callback for socket failures
    sock:add("error", function()
      connected = false
    end)

    return true
  end

  return false
end

--[[
  Queue a message to be sent on next flush
]]
function Network.send(message)
  if not connected then
    return false
  end

  table.insert(outgoingBuffer, message)
  return true
end

--[[
  Flush all queued messages over the socket
  Call once per frame
]]
function Network.flush()
  if not connected or not sock or #outgoingBuffer == 0 then
    return true
  end

  for _, message in ipairs(outgoingBuffer) do
    local ok, jsonStr = pcall(JSON.encode, message)
    if ok then
      local sendOk, sendErr = pcall(function()
        sock:send(jsonStr .. "\n")
      end)
      if not sendOk then
        -- Send failed — connection lost
        connected = false
        return false
      end
    end
  end

  outgoingBuffer = {}
  return true
end

--[[
  Return next received message, or nil if none available
]]
function Network.receive()
  if #incomingMessages > 0 then
    return table.remove(incomingMessages, 1)
  end
  return nil
end

--[[
  Check if connected
]]
function Network.isConnected()
  return connected
end

--[[
  Check if currently attempting reconnection
]]
function Network.isReconnecting()
  return reconnecting
end

--[[
  Get reconnection attempt count
]]
function Network.getReconnectAttempts()
  return reconnectAttempts
end

--[[
  Attempt reconnection with exponential backoff.
  Call once per frame from main loop. Uses timeMs to schedule retries.
  Returns true if reconnected, false otherwise.

  @param timeMs  number  Current elapsed time in ms
]]
function Network.tryReconnect(timeMs)
  if connected then
    return true
  end

  if reconnectAttempts >= maxReconnectAttempts then
    reconnecting = false
    return false
  end

  if not lastHost or not lastPort then
    return false
  end

  -- Check if enough time has passed for next attempt
  if timeMs < reconnectNextTime then
    reconnecting = true
    return false
  end

  reconnecting = true
  reconnectAttempts = reconnectAttempts + 1

  -- Clean up old socket
  if sock then
    pcall(function() sock:close() end)
    sock = nil
  end
  receiveBuffer = ""

  -- Attempt connection
  local success = Network.connect(lastHost, lastPort)

  if success then
    -- reconnectAttempts is reset inside connect()
    return true
  end

  -- Schedule next attempt with exponential backoff
  local delay = reconnectBaseDelay * (2 ^ (reconnectAttempts - 1))
  if delay > 30000 then delay = 30000 end  -- Cap at 30 seconds
  reconnectNextTime = timeMs + delay

  return false
end

--[[
  Reset reconnection state (call after giving up or manual reconnect)
]]
function Network.resetReconnect()
  reconnectAttempts = 0
  reconnectNextTime = 0
  reconnecting = false
end

--[[
  Disconnect from server
]]
function Network.disconnect()
  if sock then
    pcall(function() sock:close() end)
    sock = nil
  end
  connected = false
  reconnecting = false
  receiveBuffer = ""
  incomingMessages = {}
  outgoingBuffer = {}
end

return Network
