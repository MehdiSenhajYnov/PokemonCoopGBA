-- Minimal connection test script
console:log("[TestConnect] Starting...")

local sock = nil
local connected = false
local frameCount = 0

local function tryConnect()
  console:log("[TestConnect] Attempting TCP connect to 127.0.0.1:8080...")
  sock = socket.connect("127.0.0.1", 8080)
  if sock then
    console:log("[TestConnect] Socket created, adding callbacks...")
    sock:add("received", function(data)
      console:log("[TestConnect] Received: " .. tostring(data))
    end)
    sock:add("error", function(err)
      console:log("[TestConnect] Socket error: " .. tostring(err))
    end)
    -- Send register message
    local msg = '{"type":"register","playerId":"test_connect_' .. tostring(os.clock()) .. '"}\n'
    sock:send(msg)
    console:log("[TestConnect] Sent register message")
    connected = true
  else
    console:log("[TestConnect] Failed to create socket")
  end
end

tryConnect()

callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount % 60 == 0 then
    console:log("[TestConnect] Frame " .. frameCount .. " connected=" .. tostring(connected))
  end
  -- Write file to prove script is running
  if frameCount == 30 then
    local f = io.open("test_connect_status.txt", "w")
    if f then
      f:write("alive at frame " .. frameCount .. " connected=" .. tostring(connected) .. "\n")
      f:close()
    end
  end
  if frameCount == 300 then
    local f = io.open("test_connect_status.txt", "a")
    if f then
      f:write("alive at frame " .. frameCount .. " connected=" .. tostring(connected) .. "\n")
      f:close()
    end
  end
end)

console:log("[TestConnect] Script loaded, frame callback registered")
