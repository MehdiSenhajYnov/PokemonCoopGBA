--[[
  Pokémon Co-op Framework - Client Script (mGBA Lua)

  Main entry point for the co-op client
  Handles initialization, main loop, and coordination

  Adapted for mGBA development build (2026-02-02)
]]

-- Add parent directory to Lua path (to find config/ folder)
local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then
  scriptDir = scriptPath:match("(.*\\)")
end
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?/init.lua"
end

-- Load modules
local HAL = require("hal")
local Network = require("network")
local Render = require("render")
-- GameConfig will be loaded dynamically via ROM detection

-- Configuration
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 8080
local UPDATE_RATE = 60 -- Frames between position updates
local MAX_MESSAGES_PER_FRAME = 10 -- Limit messages processed per frame
local ENABLE_DEBUG = true

-- State
local State = {
  playerId = nil,
  connected = false,
  roomId = "default",
  frameCounter = 0,
  lastPosition = {
    x = 0,
    y = 0,
    mapId = 0,
    mapGroup = 0,
    facing = 0
  },
  otherPlayers = {},
  showGhosts = true
}

-- Canvas and painter for overlay
local overlay = nil
local painter = nil
local W = 240
local H = 160

-- ROM Detection
local detectedRomId = nil

--[[
  Debug logging
]]
local function log(message)
  if ENABLE_DEBUG then
    console:log("[PokéCoop] " .. message)
  end
end

--[[
  Generate unique player ID
  TODO: Make this more unique when we figure out what APIs mGBA has
]]
local function generatePlayerId()
  return "player_2"
end

--[[
  Detect ROM from header
  Returns config module for the detected ROM
]]
local function detectROM()
  -- Read game code from ROM header (0x080000AC)
  local success, gameId = pcall(function()
    local code = ""
    for i = 0, 3 do
      local byte = emu.memory.cart0:read8(0x000000AC + i)
      if byte and byte ~= 0 then
        code = code .. string.char(byte)
      end
    end
    return code
  end)

  -- Read game title from ROM header (0x080000A0)
  local title = ""
  pcall(function()
    for i = 0, 11 do
      local byte = emu.memory.cart0:read8(0x000000A0 + i)
      if byte and byte ~= 0 then
        title = title .. string.char(byte)
      end
    end
  end)

  if success and gameId then
    log("Detected ROM ID: " .. gameId)
    log("Detected ROM Title: " .. title)

    -- Detect Run & Bun by title (adjust pattern if needed)
    if title:upper():find("RUN") or title:upper():find("BUN") then
      log("Loading Run & Bun config")
      return require("config.run_and_bun")
    end

    -- BPEE = Emerald engine. Run & Bun uses the same game ID,
    -- so default to Run & Bun config for now (our primary target).
    -- Change this to emerald_us if you're testing vanilla Emerald.
    if gameId == "BPEE" then
      log("Loading Run & Bun config (BPEE detected)")
      return require("config.run_and_bun")
    end

    log("Unknown ROM ID: " .. gameId)
  else
    log("Failed to detect ROM")
  end

  return nil
end

-- Forward declarations
local readPlayerPosition

--[[
  Initialize client
]]
local function initialize()
  log("Initializing Pokémon Co-op Framework...")

  -- Validate configuration
  if UPDATE_RATE <= 0 then
    log("ERROR: UPDATE_RATE must be > 0, using default 60")
    UPDATE_RATE = 60
  end

  -- Detect ROM and load appropriate config
  local detectedConfig = detectROM()

  if not detectedConfig then
    log("ERROR: Could not detect ROM or load config")
    log("Loading default Emerald US config as fallback")
    detectedConfig = require("config.emerald_us")
  end

  -- Initialize HAL with detected config
  HAL.init(detectedConfig)
  log("Using config: " .. (detectedConfig.name or "Unknown"))

  -- Initialize rendering
  Render.init(detectedConfig)

  -- Generate player ID
  State.playerId = generatePlayerId()
  log("Player ID: " .. State.playerId)

  -- Connect to TCP server
  log("Connecting to server " .. SERVER_HOST .. ":" .. SERVER_PORT .. "...")

  local success = Network.connect(SERVER_HOST, SERVER_PORT)

  if success then
    State.connected = true
    log("Connected to server!")

    -- Send registration message
    Network.send({
      type = "register",
      playerId = State.playerId
    })

    -- Join default room
    Network.send({
      type = "join",
      roomId = State.roomId
    })

    -- Send initial position so other players see us immediately
    local initPos = readPlayerPosition()
    if initPos then
      Network.send({
        type = "position",
        data = initPos
      })
      State.lastPosition = initPos
    end

    -- Flush register + join + initial position immediately
    Network.flush()
  else
    log("Failed to connect to server")
    log("Make sure server is running on " .. SERVER_HOST .. ":" .. SERVER_PORT)
  end

  log("Initialization complete!")
end

--[[
  Read current player position
  Returns table with position data or nil on error
]]
readPlayerPosition = function()
  local pos = {
    x = HAL.readPlayerX(),
    y = HAL.readPlayerY(),
    mapId = HAL.readMapId(),
    mapGroup = HAL.readMapGroup(),
    facing = HAL.readFacing()
  }

  -- Validate all values are not nil
  if pos.x and pos.y and pos.mapId and pos.mapGroup and pos.facing then
    return pos
  end

  return nil
end

--[[
  Check if position has changed
]]
local function positionChanged(pos1, pos2)
  return pos1.x ~= pos2.x or
         pos1.y ~= pos2.y or
         pos1.mapId ~= pos2.mapId or
         pos1.mapGroup ~= pos2.mapGroup or
         pos1.facing ~= pos2.facing
end

--[[
  Send position update to server
]]
local function sendPositionUpdate(position)
  -- Send position to server if connected
  if State.connected then
    Network.send({
      type = "position",
      data = position
    })
  end

  -- Debug log occasionally
  if ENABLE_DEBUG and State.frameCounter % 180 == 0 then -- Every 3 seconds at 60fps
    log(string.format("Position: X=%d Y=%d Map=%d:%d Facing=%d",
      position.x, position.y, position.mapGroup, position.mapId, position.facing))
  end
end

--[[
  Initialize canvas overlay
]]
local function initOverlay()
  if not canvas then
    log("ERROR: canvas not available")
    return false
  end

  overlay = canvas:newLayer(W, H)
  overlay:setPosition(0, 0)
  painter = image.newPainter(overlay.image)
  painter:setFill(true)
  painter:setStrokeWidth(0)
  painter:setBlend(true)

  -- Load font (required for drawText to work)
  local fontLoaded = pcall(function()
    painter:loadFont("C:/Windows/Fonts/consola.ttf")
    painter:setFontSize(10)
  end)

  if not fontLoaded then
    log("WARNING: Could not load system font, text overlay will not work")
  end

  log("Overlay initialized!")
  return true
end

--[[
  Draw overlay with player information
]]
local function drawOverlay(currentPos)
  if not painter or not overlay then
    return
  end

  -- Clear overlay
  painter:setBlend(false)
  painter:setFillColor(0x00000000)
  painter:drawRectangle(0, 0, W, H)
  painter:setBlend(true)

  -- Count other players
  local playerCount = 0
  for _ in pairs(State.otherPlayers) do
    playerCount = playerCount + 1
  end

  -- Draw top bar if there are other players
  if playerCount > 0 or ENABLE_DEBUG then
    -- Semi-transparent black bar at top
    painter:setFillColor(0xA0000000)
    painter:drawRectangle(0, 0, W, 14)

    -- Player count
    painter:setFillColor(0xFF00FF00)
    painter:drawText(string.format("Players: %d", playerCount + 1), 4, 1)

    -- Connection status
    if State.connected then
      painter:setFillColor(0xFF00FF00)
      painter:drawText("ONLINE", 80, 1)
    else
      painter:setFillColor(0xFFFF0000)
      painter:drawText("OFFLINE", 80, 1)
    end

    -- Debug: Current position
    if ENABLE_DEBUG and currentPos then
      painter:setFillColor(0xFFFFFFFF)
      painter:drawText(string.format("X:%d Y:%d M:%d:%d",
        currentPos.x, currentPos.y, currentPos.mapGroup, currentPos.mapId), 130, 1)
    end
  end

  -- Draw ghost players on the game screen
  if State.showGhosts and playerCount > 0 and currentPos then
    local currentMap = {
      mapId = currentPos.mapId,
      mapGroup = currentPos.mapGroup
    }

    Render.drawAllGhosts(painter, State.otherPlayers, currentPos, currentMap)
  end

  overlay:update()
end

--[[
  Main update loop (called every frame)
]]
local function update()
  State.frameCounter = State.frameCounter + 1

  -- Read current position
  local currentPos = readPlayerPosition()

  -- Receive messages from server (limit per frame to avoid lag)
  if State.connected then
    for i = 1, MAX_MESSAGES_PER_FRAME do
      local message = Network.receive()
      if not message then break end

      -- Handle different message types
      if message.type == "position" then
        -- Update other player's position
        State.otherPlayers[message.playerId] = message.data

      elseif message.type == "registered" then
        log("Registered with ID: " .. message.playerId)
        State.playerId = message.playerId

      elseif message.type == "joined" then
        log("Joined room: " .. message.roomId)

      elseif message.type == "ping" then
        -- Respond to heartbeat
        Network.send({ type = "pong" })

      elseif message.type == "pong" then
        -- Heartbeat acknowledged

      end
    end
  end

  if currentPos then
    -- Send update at configured rate
    if State.frameCounter % UPDATE_RATE == 0 then
      if positionChanged(currentPos, State.lastPosition) then
        sendPositionUpdate(currentPos)
        State.lastPosition = currentPos
      end
    end

    -- Draw overlay
    drawOverlay(currentPos)
  else
    -- Position read failed
    if State.frameCounter % 300 == 0 then -- Every 5 seconds
      log("Warning: Failed to read player position")
    end
  end

  -- Flush outgoing messages to file (once per frame)
  if State.connected then
    Network.flush()
  end
end

--[[
  Main entry point
]]
log("======================================")
log("Pokémon Co-op Framework v0.2.0")
log("======================================")

-- Initialize
initialize()

-- Initialize overlay
initOverlay()

-- Register frame callback
callbacks:add("frame", update)

-- Cleanup on exit
callbacks:add("shutdown", function()
  if State.connected then
    log("Disconnecting from server...")
    Network.disconnect()
  end
end)

log("Script loaded successfully!")
log("Press Ctrl+R to reload this script")
