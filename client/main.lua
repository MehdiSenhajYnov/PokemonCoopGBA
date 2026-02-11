--[[
  Pokémon Co-op Framework - Client Script (mGBA Lua)

  Main entry point for the co-op client
  Handles initialization, main loop, and coordination

  Adapted for mGBA development build (2026-02-02)
]]

-- Auto-duel mode for automated 2-player testing.
-- Set to "request" on instance 1 (sends duel_request), "accept" on instance 2 (auto-accepts).
-- Set to nil for normal manual operation.
_G.AUTO_DUEL = _G.AUTO_DUEL or nil  -- "request" | "accept" | nil

-- Add script directory + parent to Lua path (for modules + config/ folder)
local scriptPath = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptPath:match("(.*/)")
if not scriptDir then
  scriptDir = scriptPath:match("(.*\\)")
end
local configDir = ""
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "?.lua"
  package.path = package.path .. ";" .. scriptDir .. "?/init.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?/init.lua"
  configDir = scriptDir .. "../config/"
end

-- Force reload of all project modules to ensure updates apply immediately on script reload
local modulesToUnload = {
  "hal", "network", "render", "interpolate", "sprite",
  "duel", "textbox", "battle", "core", "run_and_bun", "emerald_us"
}
for _, mod in ipairs(modulesToUnload) do
  package.loaded[mod] = nil
end

-- Load modules
local HAL = require("hal")
local Network = require("network")
local Render = require("render")
local Interpolate = require("interpolate")
local Sprite = require("sprite")
local Duel = require("duel")
local Textbox = require("textbox")
local Battle = require("battle")
-- GameConfig will be loaded dynamically via ROM detection

-- Detected config (set during initialize, used for character name reading)
local gameConfig = nil
local localMapMetaCache = {}
local localMapMetaPending = {}

-- Configuration
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 3333
local SEND_RATE_MOVING = 1     -- Send on exact frame position changes (tiles change ~once per walk anim)
local SEND_RATE_IDLE = 30      -- Send every 30 frames (~2x/sec) in idle for correction
local IDLE_THRESHOLD = 30      -- Frames without movement to consider idle (~0.5sec)
local MAX_MESSAGES_PER_FRAME = 10 -- Limit messages processed per frame
local ENABLE_DEBUG = true
local POSITION_HEARTBEAT_IDLE = 60 -- Force a periodic idle position refresh (~1/sec)
local SPRITE_HEARTBEAT = 120        -- Force sprite refresh (~2/sec) if packets were missed

-- Early detection constants
local INPUT_CAMERA_MAX_GAP = 3     -- Max frames between input and camera for validation
local INPUT_TIMEOUT = 5            -- Frames before abandoning input without camera confirm

-- Direction delta table (direction name -> tile offset)
local DIR_DELTA = {
  up    = { dx = 0, dy = -1 },
  down  = { dx = 0, dy =  1 },
  left  = { dx = -1, dy = 0 },
  right = { dx =  1, dy = 0 },
}

-- Convert camera pixel delta to direction string
local function cameraDeltaToDir(dcx, dcy)
  if dcy < 0 then return "up" end
  if dcy > 0 then return "down" end
  if dcx < 0 then return "left" end
  if dcx > 0 then return "right" end
  return nil
end

-- State
local State = {
  playerId = nil,
  connected = false,
  roomId = "default",
  frameCounter = 0,
  timeMs = 0,  -- Elapsed time in ms (incremented ~16.67ms per frame at 60fps)
  lastPosition = {
    x = 0,
    y = 0,
    mapId = 0,
    mapGroup = 0,
    facing = 0
  },
  otherPlayers = {},
  showGhosts = true,
  lastRenderPosition = nil, -- Last known-good local position for rendering fallback (menus/non-overworld)
  isOverworld = true,
  isMoving = false,
  lastMoveFrame = 0,
  sendCooldown = 0,
  lastSentPosition = nil,
  -- Duel warp state machine
  inputsLocked = false,
  unlockClock = 0,       -- os.clock() deadline for waiting_party timeout (real-time, speedhack-safe)
  warpPhase = nil,       -- nil / "waiting_party" / "preparing_battle" / "in_battle" / "waiting_master_outcome"
  duelPending = nil,     -- {isMaster} when duel is pending
  opponentParty = nil,   -- 600-byte party data from opponent
  opponentName = nil,    -- Opponent player name (GBA encoded bytes from TCP)
  opponentGender = 0,    -- Opponent gender (0=male, 1=female)
  opponentTrainerId = 0, -- Opponent trainer ID (u32)
  localReady = false,    -- We sent duel_ready (have all opponent data)
  opponentReady = false, -- Opponent sent duel_ready
  prevInBattle = 0,      -- Previous inBattle value for transition logging
  slaveLocalOutcome = nil, -- Slave's locally detected outcome (used as fallback if master timeout)
  slaveOutcomeClock = nil, -- os.clock() when slave detected battle end (real-time, speedhack-safe)
  lastServerMessageClock = 0, -- os.clock() of last server message during in_battle (real-time ping timeout)
  characterName = nil,  -- Local player's in-game character name (ASCII, from SaveBlock2)
  playerNames = {},     -- Dictionary: playerId → character name (from server)
  lastIdleHeartbeatFrame = 0,
  lastSpriteSendFrame = -SPRITE_HEARTBEAT,
  hadGameplayPosLastFrame = false,
  -- Early movement detection
  earlyDetect = {
    inputDir = nil,         -- KEYINPUT direction ("up"/"down"/"left"/"right")
    inputFrame = 0,         -- frame when input was detected
    prevCameraX = nil,      -- camera X from previous frame
    prevCameraY = nil,      -- camera Y from previous frame
    predictedPos = nil,     -- predicted position sent (to avoid duplicates)
    predictedFrame = 0,     -- frame when prediction was sent
  }
}

-- Canvas and painter for overlay
local overlay = nil
local painter = nil
local W = 240
local H = 160

-- Real delta time tracking (Fix 4: os.clock based)
local lastClock = os.clock()
local prevDuelButtonMask = 0

-- ROM Detection
local detectedRomId = nil

--[[
  Debug logging
]]
local function log(message)
  if ENABLE_DEBUG then
    console:log("[PokéCoop] " .. message)
  end
  if _G._diagLog then _G._diagLog("[PokéCoop] " .. message) end
end

--[[
  Generate unique player ID
  Uses timestamp + random to avoid collisions between instances
]]
local function generatePlayerId()
  math.randomseed(os.time())
  return string.format("player_%x_%x", os.time() % 0xFFFF, math.random(0, 0xFFF))
end

--[[
  Detect ROM from header
  Returns config module for the detected ROM
]]
local function loadConfig(filename)
  local path = configDir .. filename
  local ok, result = pcall(dofile, path)
  if ok and result then
    return result
  end
  log("WARNING: dofile failed for " .. path .. ", falling back to require")
  return nil
end

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
      return loadConfig("run_and_bun.lua")
    end

    -- BPEE = Emerald engine. Run & Bun uses the same game ID,
    -- so default to Run & Bun config for now (our primary target).
    -- Change this to emerald_us if you're testing vanilla Emerald.
    if gameId == "BPEE" then
      log("Loading Run & Bun config (BPEE detected)")
      return loadConfig("run_and_bun.lua")
    end

    log("Unknown ROM ID: " .. gameId)
  else
    log("Failed to detect ROM")
  end

  return nil
end

local function isValidProjectionMeta(meta)
  if type(meta) ~= "table" then
    return false
  end

  local borderX = tonumber(meta.borderX)
  local borderY = tonumber(meta.borderY)
  if not borderX or not borderY then
    return false
  end
  if borderX <= 0 or borderY <= 0 or borderX > 4096 or borderY > 4096 then
    return false
  end

  if meta.connections ~= nil and type(meta.connections) ~= "table" then
    return false
  end
  if meta.connectionCount ~= nil then
    local c = tonumber(meta.connectionCount)
    if not c or c < 0 or c > 64 then
      return false
    end
  end

  return true
end

local function projectionMetaSignature(meta)
  if not meta then
    return nil
  end
  local parts = {
    tostring(math.floor(tonumber(meta.borderX) or -1)),
    tostring(math.floor(tonumber(meta.borderY) or -1)),
  }
  if type(meta.connections) == "table" then
    for _, conn in ipairs(meta.connections) do
      parts[#parts + 1] = string.format("%d:%d:%d:%d",
        tonumber(conn.direction) or -1,
        tonumber(conn.offset) or 0,
        tonumber(conn.mapGroup) or -1,
        tonumber(conn.mapId) or -1
      )
    end
  end
  return table.concat(parts, "|")
end

-- Forward declarations
local readPlayerPosition
local readCharacterName

--[[
  Initialize client
]]
local function initialize()
  log("Initializing Pokémon Co-op Framework...")

  -- Detect ROM and load appropriate config
  local detectedConfig = detectROM()

  if not detectedConfig then
    log("ERROR: Could not detect ROM or load config")
    log("Loading default Emerald US config as fallback")
    detectedConfig = loadConfig("emerald_us.lua")
  end

  -- Store config for later use (character name reading)
  gameConfig = detectedConfig
  localMapMetaCache = {}
  localMapMetaPending = {}

  -- Initialize HAL with detected config
  HAL.init(detectedConfig)
  log("Using config: " .. (detectedConfig.name or "Unknown"))

  -- Proactively scan for sWarpData (works if game loaded from save)
  HAL.findSWarpData()

  -- Initialize rendering and sprite extraction
  Render.init(detectedConfig)
  Sprite.init()
  Render.setSprite(Sprite)

  -- Initialize textbox module (native GBA textboxes for duel UI)
  local textboxOk = Textbox.init(detectedConfig)
  if textboxOk and Textbox.isConfigured() then
    log("Textbox module configured (native GBA textboxes)")
  else
    log("Textbox module not configured (using fallback overlay)")
  end

  -- Read local player's character name from GBA memory
  State.characterName = readCharacterName()
  if State.characterName and #State.characterName > 0 then
    log("Character name: " .. State.characterName)
  else
    State.characterName = nil
    log("Could not read character name from SaveBlock2")
  end

  -- Initialize duel module with textbox
  Duel.init(Textbox)

  -- Initialize battle module (pass HAL for triggerMapLoad)
  Battle.init(detectedConfig, HAL)
  Battle.setSendFn(function(msg)
    if State.connected then Network.send(msg) end
  end)
  if Battle.isConfigured() then
    log("Battle module configured (Link Battle Emulation)")
    if Battle.isLinkConfigured() then
      log("Link battle patches configured")
    else
      log("Link battle patches NOT configured (run discovery scripts)")
    end
  else
    log("Battle module not configured (scan addresses first)")
  end

  -- Generate player ID
  State.playerId = generatePlayerId()
  log("Player ID: " .. State.playerId)

  -- Connect to TCP server
  log("Connecting to server " .. SERVER_HOST .. ":" .. SERVER_PORT .. "...")

  local success = Network.connect(SERVER_HOST, SERVER_PORT)

  if success then
    State.connected = true
    log("Connected to server!")

    -- Send registration message (include character name for duel prompts)
    Network.send({
      type = "register",
      playerId = State.playerId,
      characterName = State.characterName
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
        data = initPos,
        t = State.timeMs
      })
      State.lastPosition = initPos
      State.lastSentPosition = initPos
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
  if not (pos.x and pos.y and pos.mapId and pos.mapGroup and pos.facing) then
    return nil
  end

  -- Run & Bun occasionally reports transient wrapped coordinates during
  -- route<->town border transitions (e.g. 65535). Reject these frames so
  -- map-change compensation and network state are not polluted.
  local maxCoord = 4095
  if gameConfig and gameConfig.validation then
    local vx = tonumber(gameConfig.validation.maxX)
    local vy = tonumber(gameConfig.validation.maxY)
    if vx and vy then
      maxCoord = math.max(vx, vy)
    end
  end

  if pos.x >= 0x8000 or pos.y >= 0x8000 then
    return nil
  end
  if pos.x > maxCoord or pos.y > maxCoord then
    return nil
  end
  if pos.mapId > 255 or pos.mapGroup > 255 then
    return nil
  end

  local mapKey = string.format("%d:%d", pos.mapGroup, pos.mapId)
  local freshMeta = HAL.readMapProjectionMeta(pos.x, pos.y)
  local hasFresh = isValidProjectionMeta(freshMeta)
  if hasFresh then
    -- Require two consecutive identical snapshots before caching.
    -- This prevents storing one-frame stale metadata under a new map key.
    local sig = projectionMetaSignature(freshMeta)
    local pending = localMapMetaPending[mapKey]
    if pending and pending.signature == sig then
      pending.frames = pending.frames + 1
      pending.meta = freshMeta
    else
      pending = {
        signature = sig,
        frames = 1,
        meta = freshMeta,
      }
      localMapMetaPending[mapKey] = pending
    end

    if pending.frames >= 2 then
      localMapMetaCache[mapKey] = pending.meta
    end
  end

  local selectedMeta = localMapMetaCache[mapKey]
  if not selectedMeta and hasFresh then
    -- First stable frame: use immediately for local rendering/send, but don't cache yet.
    selectedMeta = freshMeta
  end

  if selectedMeta then
    pos.borderX = selectedMeta.borderX
    pos.borderY = selectedMeta.borderY
    pos.connectionCount = selectedMeta.connectionCount
    pos.connections = selectedMeta.connections
  end

  return pos
end

--[[
  Resolve local positions for gameplay vs rendering.
  - gameplayPos: only valid in overworld (used for movement/network logic)
  - renderPos: gameplayPos or last known-good position (used for ghost rendering in menus)
]]
local function resolveLocalPositions(rawPos, inOverworld)
  -- Keep gameplay position when raw data is available.
  -- Overworld state is still tracked for selective features (sprite capture/send),
  -- but must not gate core rendering/network position flow on R&B variants.
  local gameplayPos = rawPos
  if rawPos then
    State.lastRenderPosition = rawPos
  end

  local renderPos = gameplayPos or State.lastRenderPosition
  return gameplayPos, renderPos
end

--[[
  Read the local player's character name from SaveBlock2 (GBA memory).
  Returns ASCII string or nil if unable to read.
]]
readCharacterName = function()
  if not gameConfig or not gameConfig.battle_link or not gameConfig.battle_link.gSaveBlock2Ptr then
    return nil
  end
  local sb2PtrAddr = gameConfig.battle_link.gSaveBlock2Ptr
  local ok, sb2Addr = pcall(function()
    return emu.memory.iwram:read32(sb2PtrAddr - 0x03000000)
  end)
  if not ok or not sb2Addr or sb2Addr < 0x02000000 or sb2Addr > 0x0203FFFF then
    return nil
  end
  local nameBytes = {}
  for i = 0, 7 do
    local ok2, b = pcall(function()
      return emu.memory.wram:read8(sb2Addr - 0x02000000 + i)
    end)
    nameBytes[i + 1] = (ok2 and b) or 0xFF
  end
  return Textbox.decodeGBAText(nameBytes)
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
      data = position,
      t = State.timeMs
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

  -- Draw top bar (always show when debug enabled or not connected, for status visibility)
  if playerCount > 0 or ENABLE_DEBUG or not State.connected then
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
    elseif Network.isReconnecting() then
      painter:setFillColor(0xFFFFFF00)
      painter:drawText(string.format("RECONNECTING #%d", Network.getReconnectAttempts()), 80, 1)
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

  local shouldDrawGhosts = State.showGhosts and playerCount > 0 and currentPos

  -- Draw ghost players using interpolated positions
  if shouldDrawGhosts then
    -- Build interpolated position table for rendering (with state for debug coloring)
    local interpolatedPlayers = {}
    for playerId, rawPosition in pairs(State.otherPlayers) do
      local interpolated = Interpolate.getPosition(playerId)
      interpolatedPlayers[playerId] = {
        pos = interpolated or rawPosition,
        state = Interpolate.getState(playerId)
      }
    end

    Render.drawAllGhosts(painter, overlay.image, interpolatedPlayers, currentPos)
  else
    Render.hideGhosts()
  end

  -- Draw duel UI (fallback overlay — only when native textbox is not active)
  Duel.drawUI(painter)

  overlay:update()
end

--[[
  Main update loop (called every frame)
]]
local function update()
  -- Fix 4: Real delta time via os.clock() instead of fixed 16.67ms
  local now = os.clock()
  local realDt = math.max(5, math.min(50, (now - lastClock) * 1000))  -- ms, clamped [5, 50]
  lastClock = now

  State.frameCounter = State.frameCounter + 1
  State.timeMs = State.timeMs + realDt

  -- === Auto-calibrate warp system (track callback2 transitions every frame) ===
  -- This handles sWarpData discovery after initial game load and after natural warps
  HAL.trackCallback2()

  -- === inBattle tracking (detect natural battle transitions for logging) ===
  local inBattle = HAL.readInBattle()
  if inBattle then
    if State.prevInBattle == 0 and inBattle == 1 then
      log("Battle detected (inBattle 0→1)")
    elseif State.prevInBattle == 1 and inBattle == 0 then
      log("Battle ended (inBattle 1→0)")
    end
    State.prevInBattle = inBattle
  end

  -- Warp/Duel state machine
  if State.inputsLocked then

    -- Phase "waiting_party": waiting for opponent's party data
    if State.warpPhase == "waiting_party" then
      -- Timeout check (real-time via os.clock, speedhack-safe)
      if os.clock() >= State.unlockClock then
        log("WARNING: waiting_party timeout — aborting duel")
        Battle.reset()
        State.inputsLocked = false
        State.warpPhase = nil
        State.duelPending = nil
        State.opponentParty = nil
        State.opponentName = nil
        State.opponentGender = 0
        State.opponentTrainerId = 0
        State.localReady = false
        State.opponentReady = false
        State.lastServerMessageClock = 0
      end

      -- Process network messages
      if State.connected then
        for i = 1, MAX_MESSAGES_PER_FRAME do
          local message = Network.receive()
          if not message then break end
          if message.type == "duel_party" then
            State.opponentParty = message.data
            log(string.format("Received opponent party (%d bytes)", #message.data))
          elseif message.type == "duel_player_info" then
            State.opponentName = message.name
            State.opponentGender = message.gender or 0
            State.opponentTrainerId = message.trainerId or 0
            log(string.format("Received opponent player info (gender=%d)", State.opponentGender))
          elseif message.type == "duel_ready" then
            State.opponentReady = true
            log("Opponent is ready")
          elseif message.type == "duel_cancelled" then
            Duel.reset()
            State.duelPending = nil
            State.inputsLocked = false
            State.warpPhase = nil
            State.localReady = false
            State.opponentReady = false
            State.lastServerMessageClock = 0
            log("Duel cancelled")
          elseif message.type == "duel_opponent_disconnected" then
            log("Opponent disconnected — aborting duel")
            Battle.reset()
            State.duelPending = nil
            State.inputsLocked = false
            State.warpPhase = nil
            State.localReady = false
            State.opponentReady = false
            State.lastServerMessageClock = 0
          elseif message.type == "duel_stage" then
            Battle.onRemoteStage(message.stage)
          elseif message.type == "ping" then
            Network.send({ type = "pong" })
          end
        end
        Network.flush()
      end

      -- Phase 2: Send duel_ready when we have all opponent data
      if not State.localReady and State.opponentParty and State.opponentName then
        State.localReady = true
        if State.connected then
          Network.send({ type = "duel_ready" })
          Network.flush()
        end
        log("All opponent data received — sent duel_ready")
      end

      -- Phase 3: Both ready → inject party and start battle
      if State.localReady and State.opponentReady then
        if State.duelPending and Battle.isConfigured() then
          local injected = Battle.injectEnemyParty(State.opponentParty, State.duelPending.isMaster)
          if injected then
            State.warpPhase = "preparing_battle"
            log("Both players ready — party injected, transitioning to preparing_battle")
          end
        end
      end

    -- Phase "preparing_battle": party injected, start link battle
    elseif State.warpPhase == "preparing_battle" then
      Battle.setOpponentInfo(State.opponentName, State.opponentGender, State.opponentTrainerId)
      local started = Battle.startLinkBattle(State.duelPending.isMaster)
      if started then
        State.warpPhase = "in_battle"
        log("Link battle started!")
      else
        log("ERROR: Failed to start link battle — cleaning up")
        Battle.reset()
        State.warpPhase = nil
        State.duelPending = nil
        State.opponentParty = nil
        State.opponentName = nil
        State.opponentGender = 0
        State.opponentTrainerId = 0
        State.localReady = false
        State.opponentReady = false
        State.inputsLocked = false
        State.lastServerMessageClock = 0
      end

    -- Phase "in_battle": battle in progress
    elseif State.warpPhase == "in_battle" then
      Render.hideGhosts()

      -- Clear overlay (ghosts should not be drawn during battle)
      if painter and overlay then
        painter:setBlend(false)
        painter:setFillColor(0x00000000)
        painter:drawRectangle(0, 0, W, H)
        painter:setBlend(true)
        overlay:update()
      end

      -- Tick the battle module
      Battle.tick()

      -- Process network messages during battle
      if State.connected then
        for i = 1, MAX_MESSAGES_PER_FRAME do
          local message = Network.receive()
          if not message then break end
          State.lastServerMessageClock = os.clock()
          if message.type == "duel_buffer" then
            if Battle.isActive() then Battle.onRemoteBuffer(message) end
          elseif message.type == "duel_buffer_cmd" then
            if Battle.isActive() then Battle.onRemoteBufferCmd(message) end
          elseif message.type == "duel_buffer_resp" then
            if Battle.isActive() then Battle.onRemoteBufferResp(message) end
          elseif message.type == "duel_buffer_ack" then
            if Battle.isActive() then Battle.onRemoteBufferAck(message) end
          elseif message.type == "duel_choice" then
            if Battle.isActive() then Battle.onRemoteChoice(message) end
          elseif message.type == "duel_player_info" then
            State.opponentName = message.name
            State.opponentGender = message.gender or 0
            State.opponentTrainerId = message.trainerId or 0
            log(string.format("Received opponent player info during battle (gender=%d)", State.opponentGender))
          elseif message.type == "duel_ready" then
            -- Late arrival, ignore (we're already in battle)
          elseif message.type == "duel_stage" then
            Battle.onRemoteStage(message.stage)
          elseif message.type == "duel_end" then
            -- Opponent's battle ended — force-end ours too.
            -- In PvP, the opponent's outcome is authoritative.
            -- Opponent "win" = we "lose", opponent "lose"/"flee"/"forfeit" = we "win".
            local theirOutcome = message.outcome or "completed"
            local ourOutcome
            if theirOutcome == "win" then ourOutcome = "lose"
            elseif theirOutcome == "lose" or theirOutcome == "flee" or theirOutcome == "forfeit" then ourOutcome = "win"
            elseif theirOutcome == "draw" then ourOutcome = "draw"
            else ourOutcome = "completed" end
            log(string.format("Opponent battle ended: %s → our outcome: %s", theirOutcome, ourOutcome))
            if State.connected then
              Network.send({ type = "duel_end", outcome = ourOutcome })
            end
            Battle.forceEnd(ourOutcome)
            -- Don't clear warpPhase yet — let Battle.tick() detect DONE via isFinished()
          elseif message.type == "duel_opponent_disconnected" then
            log("Opponent disconnected during battle")
            Battle.forceEnd("completed")
            -- Don't clear warpPhase yet — let Battle.tick() detect DONE via isFinished()
          elseif message.type == "ping" then
            Network.send({ type = "pong" })
          end
        end
        Network.flush()
      end

      -- Ping timeout: no server messages for 15 seconds during battle (real-time, speedhack-safe)
      if State.lastServerMessageClock > 0 and
         os.clock() - State.lastServerMessageClock > 15.0 then
        log("No server messages for 15s — forcing battle end")
        Battle.forceEnd("completed")
        State.lastServerMessageClock = os.clock()  -- prevent re-trigger
      end

      -- Check if battle finished (naturally via savedCallback → overworld, or via detection)
      if Battle.isFinished() then
        local outcome = Battle.getOutcome()
        if State.duelPending and State.duelPending.isMaster then
          -- Master is authoritative: send outcome immediately
          if State.connected then
            Network.send({ type = "duel_end", outcome = outcome })
          end
          log(string.format("Battle finished (master): %s", outcome or "unknown"))
          Battle.reset()
          State.warpPhase = nil
          State.duelPending = nil
          State.opponentParty = nil
          State.opponentName = nil
          State.opponentGender = 0
          State.opponentTrainerId = 0
          State.localReady = false
          State.opponentReady = false
          State.inputsLocked = false
          State.lastServerMessageClock = 0
        else
          -- Slave: wait for master's duel_end (up to 180 frames)
          -- The master's mirrored outcome is more reliable than local detection
          State.warpPhase = "waiting_master_outcome"
          State.slaveLocalOutcome = outcome
          State.slaveOutcomeClock = os.clock()
          log(string.format("Battle finished (slave): local=%s, waiting for master outcome", outcome or "unknown"))
        end
      end

      -- Skip overworld logic during battle
      return

    -- Phase "waiting_master_outcome": slave waits for master's duel_end
    elseif State.warpPhase == "waiting_master_outcome" then
      -- Process network messages (looking for master's duel_end)
      if State.connected then
        for i = 1, MAX_MESSAGES_PER_FRAME do
          local message = Network.receive()
          if not message then break end
          if message.type == "duel_end" then
            -- Master's outcome received — mirror it
            local theirOutcome = message.outcome or "completed"
            local ourOutcome
            if theirOutcome == "win" then ourOutcome = "lose"
            elseif theirOutcome == "lose" or theirOutcome == "flee" or theirOutcome == "forfeit" then ourOutcome = "win"
            elseif theirOutcome == "draw" then ourOutcome = "draw"
            else ourOutcome = "completed" end
            log(string.format("Master outcome received: %s → our outcome: %s", theirOutcome, ourOutcome))
            if State.connected then
              Network.send({ type = "duel_end", outcome = ourOutcome })
            end
            Battle.reset()
            State.warpPhase = nil
            State.duelPending = nil
            State.opponentParty = nil
            State.opponentName = nil
            State.opponentGender = 0
            State.opponentTrainerId = 0
            State.localReady = false
            State.opponentReady = false
            State.inputsLocked = false
            State.lastServerMessageClock = 0
          elseif message.type == "duel_opponent_disconnected" then
            log("Master disconnected — using local outcome: " .. (State.slaveLocalOutcome or "completed"))
            if State.connected then
              Network.send({ type = "duel_end", outcome = State.slaveLocalOutcome or "completed" })
            end
            Battle.reset()
            State.warpPhase = nil
            State.duelPending = nil
            State.opponentParty = nil
            State.opponentName = nil
            State.opponentGender = 0
            State.opponentTrainerId = 0
            State.localReady = false
            State.opponentReady = false
            State.inputsLocked = false
            State.lastServerMessageClock = 0
          elseif message.type == "ping" then
            Network.send({ type = "pong" })
          end
        end
        Network.flush()
      end

      -- Timeout: if master hasn't sent outcome in 3 seconds (real-time, speedhack-safe)
      if State.slaveOutcomeClock and os.clock() - State.slaveOutcomeClock > 3.0 then
        log(string.format("Master outcome timeout — using local outcome: %s", State.slaveLocalOutcome or "completed"))
        if State.connected then
          Network.send({ type = "duel_end", outcome = State.slaveLocalOutcome or "completed" })
        end
        Battle.reset()
        State.warpPhase = nil
        State.duelPending = nil
        State.opponentParty = nil
        State.opponentName = nil
        State.opponentGender = 0
        State.opponentTrainerId = 0
        State.localReady = false
        State.opponentReady = false
        State.inputsLocked = false
        State.lastServerMessageClock = 0
      end

      return

    -- Legacy fallback (non-warp input lock)
    else
      if os.clock() >= State.unlockClock then
        State.inputsLocked = false
        State.warpPhase = nil
        log("Inputs unlocked")
      end
      if State.connected then Network.flush() end
      return
    end
  end

  -- Detect disconnection (before receive to avoid processing on dead socket)
  if State.connected and not Network.isConnected() then
    State.connected = false
    prevDuelButtonMask = 0
    Textbox.reset()
    Duel.reset()
    Battle.reset()
    -- Cancel pending duel on disconnect (any phase)
    if State.duelPending then
      State.duelPending = nil
      State.opponentParty = nil
      State.opponentName = nil
      State.opponentGender = 0
      State.opponentTrainerId = 0
      State.localReady = false
      State.opponentReady = false
      State.inputsLocked = false
      State.warpPhase = nil
      State.lastServerMessageClock = 0
      log("Duel pending cancelled (disconnected)")
    end
    log("Connection lost — will attempt reconnection")
  end

  -- Reconnection logic
  if not State.connected and not Network.isConnected() then
    local reconnected = Network.tryReconnect(State.timeMs)
    if reconnected then
      State.connected = true
      log("Reconnected to server!")

      -- Re-register and re-join room
      Network.send({ type = "register", playerId = State.playerId, characterName = State.characterName })
      Network.send({ type = "join", roomId = State.roomId })

      -- Send current position immediately so other players see us
      local pos = readPlayerPosition()
      if pos then
        Network.send({ type = "position", data = pos, t = State.timeMs })
        State.lastPosition = pos
        State.lastSentPosition = pos
      end

      Network.flush()
    end
  end

  -- Fix 1: Receive messages BEFORE Interpolate.step() so new waypoints are
  -- available in the queue before the ghost advances. Eliminates the 1-frame
  -- idle gap between consecutive steps.
  if State.connected then
    for i = 1, MAX_MESSAGES_PER_FRAME do
      local message = Network.receive()
      if not message then break end

      -- Handle different message types
      if message.type == "position" then
        -- Feed interpolation buffer with timestamp + duration hint
        Interpolate.update(message.playerId, message.data, message.t, message.dur)
        -- Store raw data as backup + update last seen
        State.otherPlayers[message.playerId] = message.data
        -- Store character name if provided (for duel textbox display)
        if message.characterName then
          State.playerNames[message.playerId] = message.characterName
        end

      elseif message.type == "sprite_update" then
        Sprite.updateFromNetwork(message.playerId, message.data)

      elseif message.type == "player_disconnected" then
        Interpolate.remove(message.playerId)
        Sprite.removePlayer(message.playerId)
        State.otherPlayers[message.playerId] = nil
        State.playerNames[message.playerId] = nil
        log("Player " .. message.playerId .. " disconnected")

      elseif message.type == "registered" then
        log("Registered with ID: " .. message.playerId)
        State.playerId = message.playerId

      elseif message.type == "joined" then
        log("Joined room: " .. message.roomId)

      elseif message.type == "duel_request" then
        -- Incoming duel request from another player
        local requesterName = message.requesterName
        -- Store character name if provided
        if requesterName and message.requesterId then
          State.playerNames[message.requesterId] = requesterName
        end
        local handled = Duel.handleRequest(message.requesterId, requesterName, State.frameCounter)
        if handled then
          log(string.format("Duel request from: %s (state=%s)",
            requesterName or message.requesterId, Duel.getState()))
        elseif State.connected and message.requesterId then
          -- If we're busy in another duel flow, reject immediately so requester doesn't hang.
          Network.send({ type = "duel_decline", requesterId = message.requesterId })
          log(string.format("Auto-declined duel from %s (busy state=%s)",
            requesterName or message.requesterId, Duel.getState()))
        end

      elseif message.type == "duel_warp" then
        -- Server says: both players accepted, start battle
        if not message.coords then
          log("ERROR: duel_warp missing coords")
        else
          local isMaster = message.isMaster or false
          log(string.format("Duel accepted! master=%s — no warp (GBA-PK style)", tostring(isMaster)))
          -- Notify duel module (clears textbox) and reset
          Duel.onResponse("accepted")
          Textbox.clear()
          Duel.reset()

          State.duelPending = { isMaster = isMaster }

          -- Send party data immediately
          if Battle.isConfigured() then
            local localParty = Battle.readLocalParty()
            if localParty then
              Network.send({ type = "duel_party", data = localParty })
              log("Sent local party data (" .. #localParty .. " bytes)")
            end
          end

          -- Send player info (name/gender/trainerId for VS screen)
          local playerInfo = Battle.getLocalPlayerInfo()
          if playerInfo then
            Network.send({ type = "duel_player_info", name = playerInfo.name, gender = playerInfo.gender, trainerId = playerInfo.trainerId })
            log("Sent player info for VS screen")
          end

          -- No map warp needed — CB2_InitBattle takes over the full screen
          State.inputsLocked = true
          State.warpPhase = "waiting_party"
          State.unlockClock = os.clock() + 10.0  -- 10 second real-time timeout (speedhack-safe)

          -- Reset early detection + ghost OAM cache
          State.earlyDetect.inputDir = nil
          State.earlyDetect.predictedPos = nil
          Render.clearGhostCache()
        end

      elseif message.type == "duel_cancelled" then
        -- Requester cancelled/disconnected, clear our prompt and pending duel
        Duel.reset()
        if State.duelPending then
          State.duelPending = nil
          State.localReady = false
          State.opponentReady = false
          State.inputsLocked = false
          State.lastServerMessageClock = 0
          State.warpPhase = nil
        end
        log("Duel cancelled by requester")

      elseif message.type == "duel_declined" then
        Duel.onResponse("declined")
        local reason = message.reason and (" (" .. tostring(message.reason) .. ")") or ""
        log("Duel was declined" .. reason)

      elseif message.type == "duel_party" then
        -- Received opponent's party data for PvP battle (stored for handshake)
        State.opponentParty = message.data
        log(string.format("Received opponent party data (%d bytes)", #message.data))

      elseif message.type == "duel_buffer" then
        -- Received battle buffer data from opponent (Link Battle Emulation)
        if Battle.isActive() then
          Battle.onRemoteBuffer(message)
        end

      elseif message.type == "duel_buffer_cmd" then
        if Battle.isActive() then Battle.onRemoteBufferCmd(message) end
      elseif message.type == "duel_buffer_resp" then
        if Battle.isActive() then Battle.onRemoteBufferResp(message) end
      elseif message.type == "duel_buffer_ack" then
        if Battle.isActive() then Battle.onRemoteBufferAck(message) end

      elseif message.type == "duel_choice" then
        -- Received PvP move choice from opponent
        if Battle.isActive() then
          Battle.onRemoteChoice(message)
        end

      elseif message.type == "duel_player_info" then
        State.opponentName = message.name
        State.opponentGender = message.gender or 0
        State.opponentTrainerId = message.trainerId or 0
        log(string.format("Received opponent player info (gender=%d)", State.opponentGender))

      elseif message.type == "duel_ready" then
        State.opponentReady = true
        log("Opponent is ready (received in main loop)")

      elseif message.type == "duel_stage" then
        -- Received battle stage sync from opponent
        if Battle.isActive() or State.warpPhase == "waiting_party" then
          Battle.onRemoteStage(message.stage)
        end

      elseif message.type == "duel_end" then
        -- Opponent's battle ended
        log(string.format("Opponent battle ended: %s", message.outcome or "unknown"))

      elseif message.type == "duel_opponent_disconnected" then
        -- Opponent disconnected during battle
        log("Opponent disconnected during battle — returning to origin")
        if Battle.isActive() then
          Battle.reset()
        end
        -- No return warp — engine returns to overworld naturally (GBA-PK style)
        State.warpPhase = nil
        State.duelPending = nil
        State.opponentParty = nil
        State.opponentName = nil
        State.opponentGender = 0
        State.opponentTrainerId = 0
        State.localReady = false
        State.opponentReady = false
        State.inputsLocked = false
        State.lastServerMessageClock = 0

      elseif message.type == "ping" then
        -- Respond to heartbeat
        Network.send({ type = "pong" })

      elseif message.type == "pong" then
        -- Heartbeat acknowledged

      end
    end
  end

  -- Advance ghost interpolation (after receive so new waypoints are in the queue)
  Interpolate.step(realDt)

  -- Read current position and callback state.
  -- Keep gameplay logic strict (overworld only), but keep rendering stable in menus
  -- using the last known-good local position.
  local rawCurrentPos = readPlayerPosition()
  local inOverworldNow = HAL.isOverworld()
  State.isOverworld = inOverworldNow
  local currentPos, renderPos = resolveLocalPositions(rawCurrentPos, inOverworldNow)

  -- Always attempt local sprite capture. The capture routine already no-ops
  -- when it cannot find a valid player OAM entry.
  Sprite.captureLocalPlayer()

  -- Duel module tick (expire timeouts for fallback overlay)
  Duel.tick(State.frameCounter)

  -- Read buttons for duel interaction (edge + hold from KEYINPUT)
  local rawKeys = HAL.readIOReg16(0x0130)
  local heldMask = 0
  if rawKeys then
    heldMask = (~rawKeys) & 0x03FF
  end
  local pressedMask = heldMask & (~prevDuelButtonMask)
  prevDuelButtonMask = heldMask

  local keyState = {
    a = (heldMask & 0x0001) ~= 0,
    b = (heldMask & 0x0002) ~= 0,
    pressedA = (pressedMask & 0x0001) ~= 0,
    pressedB = (pressedMask & 0x0002) ~= 0,
    pressedRight = (pressedMask & 0x0010) ~= 0,
    pressedLeft = (pressedMask & 0x0020) ~= 0,
    pressedUp = (pressedMask & 0x0040) ~= 0,
    pressedDown = (pressedMask & 0x0080) ~= 0,
  }
  local keyA, keyB = keyState.a, keyState.b

  -- Auto-duel support: _G.AUTO_DUEL set by wrapper scripts for automated testing
  -- In auto-duel mode, bypass textbox entirely by writing VAR_RESULT/VAR_0x8001 directly
  if _G.AUTO_DUEL and State.connected and currentPos then
    if _G.AUTO_DUEL == "accept" then
      -- Auto-accept: if a native textbox Yes/No is showing, write VAR_RESULT=1 (Yes) directly
      if Textbox.isActive() and Textbox.getActiveType() == "yesno" then
        Textbox.setVarResult(1)
      elseif Textbox.isActive() and Textbox.getActiveType() == "message" then
        Textbox.setVar8001(1)
      end
      -- Also handle fallback mode
      if Duel.hasFallbackPrompt() then
        local response, reqId = Duel.checkResponse(true, false)
        if response == "accept" and reqId then
          Network.send({ type = "duel_accept", requesterId = reqId })
          log("[AUTO] Accepted duel from: " .. reqId)
        end
      end
    elseif _G.AUTO_DUEL == "request" and not Duel.hasPrompt() then
      -- Auto-request: after 180 frames connected with another player visible, send request
      if not _G._autoDuelSent and State.frameCounter > 180 then
        for playerId, ghostPos in pairs(State.otherPlayers) do
          if ghostPos.mapId == currentPos.mapId and ghostPos.mapGroup == currentPos.mapGroup then
            Network.send({ type = "duel_request", targetId = playerId })
            Duel.onRequestSent(playerId, State.frameCounter)
            log("[AUTO] Duel request sent to: " .. playerId)
            _G._autoDuelSent = true
            break
          end
        end
      end
      -- Auto-request: if textbox Yes/No is showing (confirming_challenge), auto-confirm
      if Textbox.isActive() and Textbox.getActiveType() == "yesno" then
        Textbox.setVarResult(1)
      elseif Textbox.isActive() and Textbox.getActiveType() == "message" then
        Textbox.setVar8001(1)
      end
    end
  end

  -- Update native textbox duel state machine (returns action when main.lua needs to act)
  local duelAction = Duel.update(State.frameCounter, keyState)
  if duelAction and State.connected then
    if duelAction.action == "send_request" then
      local sent = Network.send({ type = "duel_request", targetId = duelAction.targetId })
      if sent then
        if duelAction.latencyFrames then
          log(string.format("Duel request sent to: %s (%d frames)", duelAction.targetId, duelAction.latencyFrames))
        else
          log("Duel request sent to: " .. duelAction.targetId)
        end
      else
        log("ERROR: Failed to send duel_request (network disconnected)")
      end
    elseif duelAction.action == "accept" then
      Network.send({ type = "duel_accept", requesterId = duelAction.requesterId })
      if duelAction.latencyFrames then
        log(string.format("Accepted duel from: %s (%d frames)", duelAction.requesterId, duelAction.latencyFrames))
      else
        log("Accepted duel from: " .. duelAction.requesterId)
      end
    elseif duelAction.action == "decline" then
      Network.send({ type = "duel_decline", requesterId = duelAction.requesterId })
      if duelAction.latencyFrames then
        log(string.format("Declined duel from: %s (%d frames)", duelAction.requesterId, duelAction.latencyFrames))
      else
        log("Declined duel from: " .. duelAction.requesterId)
      end
    elseif duelAction.action == "cancel" then
      if duelAction.targetId then
        Network.send({ type = "duel_cancel", targetId = duelAction.targetId })
      end
      log("Duel cancelled (no response or timeout)")
    elseif duelAction.action == "accepted" then
      log("Duel accepted — proceeding to battle")
      -- duel_warp already received and processed, nothing extra needed
    end
  end

  -- Check for fallback duel response (accept/decline) if fallback prompt is showing
  if Duel.hasFallbackPrompt() then
    local response, reqId = Duel.checkResponse(keyA, keyB)
    if response == "accept" and reqId and State.connected then
      Network.send({ type = "duel_accept", requesterId = reqId })
      log("Accepted duel from: " .. reqId)
    elseif response == "decline" and reqId and State.connected then
      Network.send({ type = "duel_decline", requesterId = reqId })
      log("Declined duel from: " .. reqId)
    end
  elseif not Duel.hasPrompt() then
    -- Check for duel trigger (A near ghost) — only when no prompt is showing
    if currentPos and State.connected then
      local targetId = Duel.checkTrigger(currentPos, State.otherPlayers, keyA, State.frameCounter)
      if targetId then
        -- Try native textbox flow (use character name if known)
        local targetName = State.playerNames[targetId] or targetId
        local started = Duel.startChallenge(targetId, targetName, State.frameCounter)
        if not started then
          -- Textbox not configured or failed: send request directly (old behavior)
          Network.send({ type = "duel_request", targetId = targetId })
          Duel.onRequestSent(targetId, State.frameCounter)
          log("Duel request sent to: " .. targetId)
        end
      end
    end
  end

  -- Send sprite update when local capture reports a meaningful change.
  if Sprite.hasChanged() and State.connected then
    local spriteData = Sprite.getLocalSpriteData()
    if spriteData then
      Network.send({
        type = "sprite_update",
        data = spriteData
      })
      State.lastSpriteSendFrame = State.frameCounter
    end
  elseif State.connected and (State.frameCounter - State.lastSpriteSendFrame) >= SPRITE_HEARTBEAT then
    local spriteData = Sprite.getLocalSpriteData()
    if spriteData then
      Network.send({
        type = "sprite_update",
        data = spriteData
      })
      State.lastSpriteSendFrame = State.frameCounter
    end
  end

  local regainedGameplayPos = (currentPos ~= nil) and (not State.hadGameplayPosLastFrame)
  State.hadGameplayPosLastFrame = (currentPos ~= nil)

  if currentPos then
    -- Read camera early (needed for early movement detection AND render)
    local cameraX = HAL.readCameraX()
    local cameraY = HAL.readCameraY()

    if regainedGameplayPos and State.connected then
      sendPositionUpdate(currentPos)
      State.lastSentPosition = currentPos
      State.lastIdleHeartbeatFrame = State.frameCounter
    end

    -- Detect movement state
    if positionChanged(currentPos, State.lastPosition) then
      -- Check for map change → immediate send + clear caches
      local mapChanged = currentPos.mapId ~= State.lastPosition.mapId
                      or currentPos.mapGroup ~= State.lastPosition.mapGroup
      if mapChanged then
        local oldMapGroup = State.lastPosition.mapGroup
        local oldMapId = State.lastPosition.mapId
        local dx = math.abs(currentPos.x - State.lastPosition.x)
        local dy = math.abs(currentPos.y - State.lastPosition.y)
        if ENABLE_DEBUG then
          log(string.format("Map change %d:%d -> %d:%d (dx=%d dy=%d)",
            oldMapGroup, oldMapId, currentPos.mapGroup, currentPos.mapId, dx, dy))
        end

        sendPositionUpdate(currentPos)
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
        State.sendCooldown = SEND_RATE_MOVING
        State.lastIdleHeartbeatFrame = State.frameCounter
        -- Keep camera continuity across connected-map seams (GBAPK-like behavior),
        -- but reset injected OAM/projection allocations.
        Render.clearGhostCache({ preserveCamera = true })
        Duel.reset()
        -- Scan for sWarpData after natural map change (calibrates warp system)
        HAL.findSWarpData()
        -- Reset early detection on map change
        State.earlyDetect.inputDir = nil
        State.earlyDetect.predictedPos = nil
      end

      State.isMoving = true
      State.lastMoveFrame = State.frameCounter
    else
      if State.frameCounter - State.lastMoveFrame > IDLE_THRESHOLD then
        State.isMoving = false
      end
    end

    -- === Early movement detection (KEYINPUT + camera delta double validation) ===
    local ed = State.earlyDetect
    local inputDir = HAL.readKeyInput()

    -- Track input direction (only when no prediction pending)
    if inputDir and not ed.predictedPos then
      if ed.inputDir ~= inputDir then
        ed.inputDir = inputDir
        ed.inputFrame = State.frameCounter
      end
    elseif not inputDir and not ed.predictedPos then
      ed.inputDir = nil
      ed.inputFrame = 0
    end

    -- Camera delta detection (hoisted for use in duration estimation)
    local cameraDir = nil
    local cameraDX, cameraDY = 0, 0
    if ed.prevCameraX and cameraX and cameraY then
      cameraDX = cameraX - ed.prevCameraX
      cameraDY = cameraY - ed.prevCameraY
      if cameraDX ~= 0 or cameraDY ~= 0 then
        cameraDir = cameraDeltaToDir(cameraDX, cameraDY)
      end
    end
    ed.prevCameraX = cameraX
    ed.prevCameraY = cameraY

    -- Double validation: input + camera agree on direction, gap <= INPUT_CAMERA_MAX_GAP
    if ed.inputDir and cameraDir and not ed.predictedPos then
      if ed.inputDir == cameraDir then
        local gap = State.frameCounter - ed.inputFrame
        if gap <= INPUT_CAMERA_MAX_GAP then
          -- CONFIRMED: compute destination and send immediately
          local delta = DIR_DELTA[ed.inputDir]
          if delta then
            ed.predictedPos = {
              x = currentPos.x + delta.dx,
              y = currentPos.y + delta.dy,
              mapId = currentPos.mapId,
              mapGroup = currentPos.mapGroup,
              facing = currentPos.facing
            }
            ed.predictedFrame = State.frameCounter

            if State.connected then
              -- Estimate step duration from camera scroll rate:
              -- pixels/frame → frames to cross 1 tile (16px) → ms
              local pxPerFrame = math.max(1, math.abs(cameraDX ~= 0 and cameraDX or cameraDY))
              local estimatedDur = math.floor((16 / pxPerFrame) * 16.67)

              Network.send({
                type = "position",
                data = ed.predictedPos,
                t = State.timeMs,
                dur = estimatedDur
              })
              State.lastSentPosition = ed.predictedPos
            end
          end
        end
      end
    end

    -- Timeout input without camera confirmation (wall/blocked)
    if ed.inputDir and not ed.predictedPos then
      if State.frameCounter - ed.inputFrame > INPUT_TIMEOUT then
        ed.inputDir = nil
        ed.inputFrame = 0
      end
    end

    -- === Tile confirmation + adaptive send ===
    if ed.predictedPos and positionChanged(currentPos, State.lastPosition) then
      -- Tile changed while prediction active: check match
      if currentPos.x == ed.predictedPos.x
        and currentPos.y == ed.predictedPos.y
        and currentPos.mapId == ed.predictedPos.mapId
        and currentPos.mapGroup == ed.predictedPos.mapGroup then
        -- MATCH: prediction correct, no duplicate needed
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
      else
        -- MISMATCH (e.g. ledge jump): send actual position as normal update
        sendPositionUpdate(currentPos)
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
      end
      -- Reset detection in all cases
      ed.inputDir = nil
      ed.predictedPos = nil
    elseif not ed.predictedPos then
      -- No prediction active: original adaptive send behavior
      local sendRate = State.isMoving and SEND_RATE_MOVING or SEND_RATE_IDLE

      if sendRate > 0 and State.sendCooldown <= 0 then
        if positionChanged(currentPos, State.lastPosition) then
          sendPositionUpdate(currentPos)
          State.lastPosition = currentPos
          State.lastSentPosition = currentPos
          State.sendCooldown = sendRate
        end
      end
    end

    -- Idle correction: send when stopped but lastSentPosition differs (fixes false predictions)
    if not State.isMoving and State.lastSentPosition
      and positionChanged(currentPos, State.lastSentPosition)
      and State.sendCooldown <= 0 then
      sendPositionUpdate(currentPos)
      State.lastSentPosition = currentPos
      State.sendCooldown = SEND_RATE_IDLE
      State.lastIdleHeartbeatFrame = State.frameCounter
    end

    if State.connected and not State.isMoving
      and (State.frameCounter - State.lastIdleHeartbeatFrame) >= POSITION_HEARTBEAT_IDLE then
      sendPositionUpdate(currentPos)
      State.lastSentPosition = currentPos
      State.lastIdleHeartbeatFrame = State.frameCounter
    end

    State.sendCooldown = math.max(0, State.sendCooldown - 1)

    -- Update sub-tile camera tracking for smooth ghost scrolling
    Render.updateCamera(currentPos.x, currentPos.y, cameraX, cameraY)

  end

  -- Draw overlay using render fallback position (keeps ghosts visible in menus).
  if renderPos then
    drawOverlay(renderPos)
  elseif rawCurrentPos == nil and State.frameCounter % 300 == 0 then -- Every 5 seconds
    log("Warning: Failed to read player position")
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

-- Register frame callback (wrapped in pcall for error logging)
local _updateErrorCount = 0
local _updateErrorFile = nil
callbacks:add("frame", function()
  local ok, err = pcall(update)
  if not ok then
    _updateErrorCount = _updateErrorCount + 1
    if _updateErrorCount <= 10 then
      local errMsg = "[FATAL] update() error #" .. _updateErrorCount .. ": " .. tostring(err)
      console:log(errMsg)
      -- Write errors to file so they can be read without mGBA console
      if not _updateErrorFile then
        _updateErrorFile = io.open("update_errors.txt", "w")
      end
      if _updateErrorFile then
        _updateErrorFile:write(errMsg .. "\n")
        _updateErrorFile:flush()
      end
    end
  end
end)

-- Cleanup on exit
callbacks:add("shutdown", function()
  -- Clean up interpolation for all tracked players
  for _, playerId in ipairs(Interpolate.getPlayers()) do
    Interpolate.remove(playerId)
  end

  -- Clean up textbox and battle state
  Textbox.reset()
  Battle.reset()

  log("Disconnecting from server...")
  Network.disconnect()
end)

log("Script loaded successfully!")
log("Press Ctrl+R to reload this script")
