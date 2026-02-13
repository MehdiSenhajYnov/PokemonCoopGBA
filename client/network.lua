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

-- Reconnection / connection state machine
local CONNECT_STATE = {
  DISCONNECTED = "disconnected",
  CONNECTING = "connecting",
  CONNECTED = "connected",
  RETRY_WAIT = "retry_wait"
}
local connectionState = CONNECT_STATE.DISCONNECTED
local reconnectAttempts = 0
local maxReconnectAttempts = 10
local reconnectBaseDelay = 1000  -- ms (1 second)
local reconnectMaxDelay = 8000   -- ms cap
local reconnectJitterMs = 200
local reconnectNextTime = 0     -- timeMs at which next reconnect attempt is allowed
local reconnecting = false
local lastHost = nil
local lastPort = nil
local connectTimeoutSeconds = 0.25

local function setConnectionState(nextState)
  connectionState = nextState
  reconnecting = (nextState == CONNECT_STATE.CONNECTING or nextState == CONNECT_STATE.RETRY_WAIT)
end

local function markDisconnected()
  connected = false
  receiveBuffer = ""
  incomingMessages = {}
  outgoingBuffer = {}
  if connectionState ~= CONNECT_STATE.RETRY_WAIT then
    setConnectionState(CONNECT_STATE.DISCONNECTED)
  end
end

local function closeSocket()
  if sock then
    pcall(function()
      sock:close()
    end)
    sock = nil
  end
end

local function registerSocketCallbacks(activeSock)
  if not activeSock then return end

  -- Register receive callback (fires once per frame when data available)
  activeSock:add("received", function()
    if activeSock ~= sock then
      return
    end
    local okRecv, data, recvErr = pcall(function()
      return activeSock:receive(4096)
    end)
    if not okRecv then
      markDisconnected()
      return
    end
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
    elseif recvErr and (not socket or not socket.ERRORS or recvErr ~= socket.ERRORS.AGAIN) then
      -- Connection lost during receive (ignore AGAIN/no-data)
      markDisconnected()
    end
  end)

  -- Register error callback for socket failures
  activeSock:add("error", function()
    if activeSock ~= sock then
      return
    end
    markDisconnected()
  end)
end

local function createSocketAndConnect(host, port)
  local candidate = nil

  local okTcp, tcpSock = pcall(function()
    if socket and socket.tcp then
      return socket.tcp()
    end
    return nil
  end)
  if okTcp and tcpSock then
    candidate = tcpSock
    pcall(function()
      if candidate.settimeout then
        candidate:settimeout(connectTimeoutSeconds)
      end
    end)

    local okConnect, connectedNow = pcall(function()
      return candidate:connect(host, port)
    end)
    if okConnect and connectedNow then
      return candidate
    end

    pcall(function()
      candidate:close()
    end)
  end

  -- Fallback for mGBA builds that expose only socket.connect()
  local okFallback, fallbackSock = pcall(function()
    return socket.connect(host, port)
  end)
  if okFallback and fallbackSock then
    return fallbackSock
  end
  return nil
end

local function connectInternal(host, port, resetReconnectCounters)
  if not host or not port then
    return false
  end

  setConnectionState(CONNECT_STATE.CONNECTING)
  closeSocket()
  receiveBuffer = ""

  local connectedSock = createSocketAndConnect(host, port)
  if not connectedSock then
    connected = false
    setConnectionState(CONNECT_STATE.DISCONNECTED)
    return false
  end

  sock = connectedSock
  connected = true
  setConnectionState(CONNECT_STATE.CONNECTED)
  registerSocketCallbacks(sock)

  if resetReconnectCounters then
    reconnectAttempts = 0
    reconnectNextTime = 0
  end

  return true
end

--[[
  Connect to TCP server using mGBA built-in socket API
  Uses a state-machine friendly path so reconnects can be scheduled with backoff.
]]
function Network.connect(host, port)
  lastHost = host
  lastPort = port
  return connectInternal(host, port, true)
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
        markDisconnected()
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
  return reconnecting and not connected
end

--[[
  Get reconnection attempt count
]]
function Network.getReconnectAttempts()
  return reconnectAttempts
end

--[[
  Get current connection state for UI/debug:
  disconnected | connecting | connected | retry_wait
]]
function Network.getConnectionState()
  return connectionState
end

--[[
  Attempt reconnection with exponential backoff.
  Call once per frame from main loop. Uses timeMs to schedule retries.
  Returns true if reconnected, false otherwise.

  @param timeMs  number  Current elapsed time in ms
]]
function Network.tryReconnect(timeMs)
  if connected then
    setConnectionState(CONNECT_STATE.CONNECTED)
    return true
  end

  if not lastHost or not lastPort then
    setConnectionState(CONNECT_STATE.DISCONNECTED)
    return false
  end

  if reconnectAttempts >= maxReconnectAttempts then
    setConnectionState(CONNECT_STATE.DISCONNECTED)
    return false
  end

  -- Check if enough time has passed for next attempt
  if timeMs < reconnectNextTime then
    setConnectionState(CONNECT_STATE.RETRY_WAIT)
    return false
  end

  reconnectAttempts = reconnectAttempts + 1

  -- Attempt connection
  local success = connectInternal(lastHost, lastPort, false)

  if success then
    reconnectAttempts = 0
    reconnectNextTime = 0
    return true
  end

  -- Schedule next attempt with exponential backoff
  local delay = reconnectBaseDelay * (2 ^ (reconnectAttempts - 1))
  if delay > reconnectMaxDelay then delay = reconnectMaxDelay end
  local jitter = reconnectJitterMs > 0 and ((reconnectAttempts * 131) % reconnectJitterMs) or 0
  reconnectNextTime = timeMs + delay + jitter
  setConnectionState(CONNECT_STATE.RETRY_WAIT)

  return false
end

--[[
  Reset reconnection state (call after giving up or manual reconnect)
]]
function Network.resetReconnect()
  reconnectAttempts = 0
  reconnectNextTime = 0
  if connected then
    setConnectionState(CONNECT_STATE.CONNECTED)
  else
    setConnectionState(CONNECT_STATE.DISCONNECTED)
  end
end

--[[
  Disconnect from server
]]
function Network.disconnect()
  closeSocket()
  connected = false
  setConnectionState(CONNECT_STATE.DISCONNECTED)
  receiveBuffer = ""
  incomingMessages = {}
  outgoingBuffer = {}
  reconnectAttempts = 0
  reconnectNextTime = 0
end

return Network
