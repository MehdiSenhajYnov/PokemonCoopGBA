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

-- Install timestamp prefix on console logs once per mGBA session.
-- This timestamps logs from all modules ([HAL], [Battle], [PokéCoop], ...).
local function installTimestampedConsoleLogging()
  if not console then
    return
  end

  -- Keep the original mGBA console object. Avoid assigning fields on it
  -- directly (userdata may reject writes with "Invalid key").
  if _G.__pokecoopConsoleRaw == nil then
    if type(console) == "table" and console.__pokecoop_raw_console ~= nil then
      _G.__pokecoopConsoleRaw = console.__pokecoop_raw_console
    else
      _G.__pokecoopConsoleRaw = console
    end
  end
  local rawConsole = _G.__pokecoopConsoleRaw
  if not rawConsole or type(rawConsole.log) ~= "function" then
    return
  end

  _G.__pokecoopLogStartClock = os.clock()
  _G.__pokecoopLogStartWallSec = os.time()

  if _G.__pokecoopConsoleWrapper == nil then
    local wrapper = {
      __pokecoop_raw_console = rawConsole,
    }

    function wrapper:log(...)
      local clockNow = os.clock()
      local elapsedMs = math.floor((clockNow - (_G.__pokecoopLogStartClock or clockNow)) * 1000 + 0.5)
      if elapsedMs < 0 then
        elapsedMs = 0
      end
      local wallSec = (_G.__pokecoopLogStartWallSec or os.time()) + math.floor(elapsedMs / 1000)
      local wall = os.date("*t", wallSec)
      local ms = elapsedMs % 1000
      local prefix = string.format("[%02d:%02d:%02d.%03d +%dms]", wall.hour, wall.min, wall.sec, ms, elapsedMs)

      local parts = {}
      local argCount = select("#", ...)
      for i = 1, argCount do
        parts[#parts + 1] = tostring(select(i, ...))
      end
      local payload = table.concat(parts, " ")

      rawConsole:log(prefix .. " " .. payload)
    end

    setmetatable(wrapper, {
      __index = function(_, key)
        if key == "log" then
          return wrapper.log
        end
        local value = rawConsole[key]
        if type(value) == "function" then
          -- Preserve method semantics for other console functions.
          return function(_, ...)
            return value(rawConsole, ...)
          end
        end
        return value
      end
    })

    _G.__pokecoopConsoleWrapper = wrapper
  end

  -- Redirect global console reference to wrapper.
  console = _G.__pokecoopConsoleWrapper
end

installTimestampedConsoleLogging()

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
local SERVER_HOST_LOCAL = "127.0.0.1"
local SERVER_HOST_REMOTE = "5.196.23.143" -- Keep remote server IP for quick switch-back
local USE_LOCALHOST = true
local SERVER_HOST = USE_LOCALHOST and SERVER_HOST_LOCAL or SERVER_HOST_REMOTE
local SERVER_PORT = 3333
local SEND_RATE_MOVING = 1     -- Send on exact frame position changes (tiles change ~once per walk anim)
local SEND_RATE_IDLE = 30      -- Send every 30 frames (~2x/sec) in idle for correction
local IDLE_THRESHOLD = 30      -- Frames without movement to consider idle (~0.5sec)
local MAX_MESSAGES_PER_FRAME = 10 -- Limit messages processed per frame
local ENABLE_DEBUG = true
local POSITION_HEARTBEAT_IDLE = 60 -- Force a periodic idle position refresh (~1/sec)
local SPRITE_HEARTBEAT = 120        -- Force sprite refresh (~2/sec) if packets were missed
local SPRITE_MIN_BROADCAST_CONFIDENCE = 0.35
local ENABLE_REMOTE_POS_DEBUG = true   -- Build remote debug snapshot state
local SHOW_LOCAL_POS_DEBUG_OVERLAY = false  -- Draw local X/Y/map debug in top bar
local SHOW_REMOTE_POS_DEBUG_OVERLAY = false -- Draw remote Target/Current/Projected/Screen on overlay
local REMOTE_POS_DEBUG_CONSOLE = true  -- Optional per-frame console log (very verbose)

-- Early detection constants
local INPUT_CAMERA_MAX_GAP = 3     -- Max frames between input and camera for validation
local INPUT_TIMEOUT = 5            -- Frames before abandoning input without camera confirm
local ENABLE_EARLY_PREDICTION = false -- Disable pre-send step prediction (causes start-of-step ghost kick)

-- Map transition / metadata stability
local META_STABLE_CONSEC_FRAMES = 3
local MAP_SETTLE_MAX_FRAMES = 12

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

local function clampNumber(value, minValue, maxValue, fallback)
  local n = tonumber(value)
  if n == nil then
    n = fallback
  end
  if n == nil then
    n = minValue
  end
  if n < minValue then n = minValue end
  if n > maxValue then n = maxValue end
  return n
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
  remoteDebugLastConsoleLine = nil,
  remoteDebugTrackedPlayerId = nil,
  mapSync = {
    mapRev = 0,
    phase = "stable",          -- stable | transition_pending | transition_settling
    currentMapKey = nil,
    transitionFrame = 0,
    justSettled = false,
    metaStable = false,
    metaStableFrames = 0,
    lastMetaSig = nil,
    lastStableHash = nil,
    settleTimeoutLogged = false,
  },
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

local function mapKeyFromPosition(pos)
  if type(pos) ~= "table" then
    return nil
  end
  if pos.mapGroup == nil or pos.mapId == nil then
    return nil
  end
  return string.format("%d:%d", tonumber(pos.mapGroup) or -1, tonumber(pos.mapId) or -1)
end

local function positionHasConnectionToMap(sourcePos, targetPos)
  if type(sourcePos) ~= "table" or type(targetPos) ~= "table" then
    return false
  end

  local targetGroup = tonumber(targetPos.mapGroup)
  local targetId = tonumber(targetPos.mapId)
  if targetGroup == nil or targetId == nil then
    return false
  end

  if type(sourcePos.connections) ~= "table" then
    return false
  end

  for _, conn in ipairs(sourcePos.connections) do
    local direction = tonumber(conn.direction)
    local mapGroup = tonumber(conn.mapGroup)
    local mapId = tonumber(conn.mapId)
    if direction and direction >= 1 and direction <= 4
      and mapGroup == targetGroup and mapId == targetId then
      return true
    end
  end

  return false
end

local function classifyMapTransition(previousPos, currentPos)
  local previousKey = mapKeyFromPosition(previousPos)
  local currentKey = mapKeyFromPosition(currentPos)
  if previousKey == nil or currentKey == nil then
    return "unknown"
  end
  if previousKey == currentKey then
    return "same_map"
  end

  if positionHasConnectionToMap(previousPos, currentPos)
    or positionHasConnectionToMap(currentPos, previousPos) then
    return "seam_connected"
  end

  local prevX = tonumber(previousPos.x)
  local prevY = tonumber(previousPos.y)
  local currX = tonumber(currentPos.x)
  local currY = tonumber(currentPos.y)
  if prevX ~= nil and prevY ~= nil and currX ~= nil and currY ~= nil then
    local dx = math.abs(currX - prevX)
    local dy = math.abs(currY - prevY)
    if dx <= 2 and dy <= 2 then
      return "likely_seam"
    end
  end

  return "warp_or_hard"
end

local function wouldPredictionCrossMapBoundary(pos, delta)
  if type(pos) ~= "table" or type(delta) ~= "table" then
    return false
  end

  local x = tonumber(pos.x)
  local y = tonumber(pos.y)
  local dx = tonumber(delta.dx)
  local dy = tonumber(delta.dy)
  local borderX = tonumber(pos.borderX)
  local borderY = tonumber(pos.borderY)

  if x == nil or y == nil or dx == nil or dy == nil then
    return false
  end
  if borderX == nil or borderY == nil or borderX <= 0 or borderY <= 0 then
    return false
  end

  local nextX = x + dx
  local nextY = y + dy
  return (nextX < 0) or (nextY < 0) or (nextX >= borderX) or (nextY >= borderY)
end

local function getLocalPositionEnvelope()
  local sync = State.mapSync or {}
  local mapRev = tonumber(sync.mapRev) or 0
  local metaStable = sync.metaStable == true
  local metaHash = metaStable and sync.lastStableHash or nil
  return mapRev, metaStable, metaHash
end

local clonePosition

local function buildPositionMessage(position, durationHint, transitionContext)
  local mapRev, metaStable, metaHash = getLocalPositionEnvelope()
  local data = position
  if transitionContext and type(transitionContext) == "table" and type(transitionContext.from) == "table" then
    data = clonePosition(position) or {}
    local fromPos = transitionContext.from
    data.transitionFromMapGroup = tonumber(fromPos.mapGroup)
    data.transitionFromMapId = tonumber(fromPos.mapId)
    data.transitionFromX = tonumber(fromPos.x)
    data.transitionFromY = tonumber(fromPos.y)
    data.transitionToken = transitionContext.token
    data.transitionKind = transitionContext.kind
  end

  local msg = {
    type = "position",
    data = data,
    t = State.timeMs,
    mapRev = mapRev,
    metaStable = metaStable
  }
  if durationHint ~= nil then
    msg.dur = durationHint
  end
  if metaHash then
    msg.metaHash = metaHash
  end
  return msg
end

clonePosition = function(pos)
  if type(pos) ~= "table" then
    return nil
  end
  local out = {}
  for k, v in pairs(pos) do
    out[k] = v
  end
  return out
end

local function parseRemotePositionEnvelope(message)
  local mapRev = tonumber(message and message.mapRev)
  if mapRev == nil and message and type(message.data) == "table" then
    mapRev = tonumber(message.data.mapRev)
  end
  if mapRev == nil then
    mapRev = 0
  end

  local metaStable = false
  if message and message.metaStable == true then
    metaStable = true
  elseif message and type(message.data) == "table" and message.data.metaStable == true then
    metaStable = true
  end

  local metaHash = nil
  if message then
    metaHash = message.metaHash
    if not metaHash and type(message.data) == "table" then
      metaHash = message.data.metaHash
    end
  end

  return {
    mapRev = mapRev,
    metaStable = metaStable,
    metaHash = metaHash
  }
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

  local renderConfig = (type(detectedConfig) == "table" and type(detectedConfig.render) == "table") and detectedConfig.render or nil
  if renderConfig then
    local minSpriteConfidence = renderConfig.spriteBroadcastConfidenceMin
    if minSpriteConfidence == nil then
      minSpriteConfidence = renderConfig.spriteCaptureConfidenceMin
    end
    if minSpriteConfidence ~= nil then
      SPRITE_MIN_BROADCAST_CONFIDENCE = clampNumber(minSpriteConfidence, 0, 1, SPRITE_MIN_BROADCAST_CONFIDENCE)
    end
  end

  -- Initialize HAL with detected config
  HAL.init(detectedConfig)
  log("Using config: " .. (detectedConfig.name or "Unknown"))

  -- Proactively scan for sWarpData (works if game loaded from save)
  HAL.findSWarpData()

  -- Initialize rendering and sprite extraction
  Render.init(detectedConfig)
  Sprite.init(detectedConfig)
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
      Network.send(buildPositionMessage(initPos))
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

  local mapKey = mapKeyFromPosition(pos)
  local mapSync = State.mapSync
  if mapSync and mapKey and mapSync.currentMapKey ~= mapKey then
    local previousKey = mapSync.currentMapKey
    if previousKey ~= nil then
      mapSync.mapRev = (tonumber(mapSync.mapRev) or 0) + 1
      if ENABLE_DEBUG then
        log(string.format(
          "Map transition start %s -> %s (rev=%d, frame=%d)",
          previousKey,
          mapKey,
          mapSync.mapRev,
          State.frameCounter
        ))
      end
    end
    mapSync.currentMapKey = mapKey
    mapSync.phase = "transition_pending"
    mapSync.transitionFrame = State.frameCounter
    mapSync.justSettled = false
    mapSync.metaStable = false
    mapSync.metaStableFrames = 0
    mapSync.lastMetaSig = nil
    mapSync.lastStableHash = nil
    mapSync.settleTimeoutLogged = false
    localMapMetaPending[mapKey] = nil
  end

  local freshMeta = HAL.readMapProjectionMeta(pos.x, pos.y)
  local hasFresh = isValidProjectionMeta(freshMeta)
  if hasFresh then
    -- Require consecutive identical snapshots before caching.
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

    if pending.frames >= META_STABLE_CONSEC_FRAMES then
      localMapMetaCache[mapKey] = pending.meta
    end
  end

  local pending = localMapMetaPending[mapKey]
  local pendingStable = pending and pending.frames >= META_STABLE_CONSEC_FRAMES

  -- Runtime projection should use the freshest valid metadata, matching
  -- GBAPK behavior. Stable cache is kept for envelope hash/trust logic.
  local selectedMeta = nil
  if hasFresh then
    selectedMeta = freshMeta
  else
    selectedMeta = localMapMetaCache[mapKey]
    if pendingStable and pending.meta then
      selectedMeta = pending.meta
    end
  end

  if mapSync then
    if mapSync.phase == "transition_pending" and not pendingStable then
      mapSync.phase = "transition_settling"
    end

    if pendingStable and selectedMeta then
      local stableSig = pending.signature or projectionMetaSignature(selectedMeta)
      if mapSync.lastMetaSig == stableSig then
        mapSync.metaStableFrames = mapSync.metaStableFrames + 1
      else
        mapSync.lastMetaSig = stableSig
        mapSync.metaStableFrames = 1
      end

      local settledFromTransition = (mapSync.phase ~= "stable")
      mapSync.metaStable = true
      mapSync.phase = "stable"
      mapSync.justSettled = settledFromTransition
      mapSync.lastStableHash = stableSig
      mapSync.settleTimeoutLogged = false

      if ENABLE_DEBUG and settledFromTransition then
        log(string.format(
          "Map transition settled %s (rev=%d, frame=%d, header=0x%08X)",
          mapKey or "unknown",
          tonumber(mapSync.mapRev) or 0,
          State.frameCounter,
          tonumber(selectedMeta.mapHeaderAddr) or 0
        ))
      end
    elseif mapSync.phase ~= "stable" then
      mapSync.justSettled = false
      mapSync.metaStable = false
      mapSync.metaStableFrames = 0
      mapSync.lastMetaSig = nil

      if (not mapSync.settleTimeoutLogged)
        and (State.frameCounter - (mapSync.transitionFrame or 0)) >= MAP_SETTLE_MAX_FRAMES then
        mapSync.settleTimeoutLogged = true
        if ENABLE_DEBUG then
          log(string.format(
            "Map transition settling timeout on %s (rev=%d, frame=%d)",
            mapKey or "unknown",
            tonumber(mapSync.mapRev) or 0,
            State.frameCounter
          ))
        end
      end
    else
      mapSync.justSettled = false
      mapSync.metaStable = selectedMeta ~= nil
      if selectedMeta then
        mapSync.lastStableHash = projectionMetaSignature(selectedMeta)
      else
        mapSync.lastStableHash = nil
      end
    end
  end

  if selectedMeta then
    pos.borderX = selectedMeta.borderX
    pos.borderY = selectedMeta.borderY
    pos.connectionCount = selectedMeta.connectionCount
    pos.connections = selectedMeta.connections
  end

  local mapRev, metaStable, metaHash = getLocalPositionEnvelope()
  pos.mapRev = mapRev
  pos.metaStable = metaStable
  pos.metaHash = metaHash

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
         pos1.mapGroup ~= pos2.mapGroup
end

--[[
  Send position update to server
]]
local function sendPositionUpdate(position, durationHint, transitionContext)
  -- Send position to server if connected
  if State.connected then
    Network.send(buildPositionMessage(position, durationHint, transitionContext))
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

local function formatDebugNumber(value)
  local n = tonumber(value)
  if n == nil then
    return "nil"
  end
  return string.format("%.3f", n)
end

local function formatDebugMap(pos)
  if type(pos) ~= "table" then
    return "nil"
  end
  local mapGroup = tonumber(pos.mapGroup)
  local mapId = tonumber(pos.mapId)
  if mapGroup == nil or mapId == nil then
    return "nil"
  end
  return string.format("%d:%d", mapGroup, mapId)
end

local function formatDebugPos(pos)
  if type(pos) ~= "table" then
    return "nil"
  end
  return string.format("%s,%s @%s",
    formatDebugNumber(pos.x),
    formatDebugNumber(pos.y),
    formatDebugMap(pos)
  )
end

local function formatDebugScreen(pos)
  if type(pos) ~= "table" then
    return "nil"
  end
  local x = tonumber(pos.x)
  local y = tonumber(pos.y)
  if x == nil or y == nil then
    return "nil"
  end
  return string.format("%d,%d", math.floor(x), math.floor(y))
end

local function buildRemotePositionDebugSnapshot(currentPos)
  if not currentPos then
    return nil
  end
  if not ENABLE_REMOTE_POS_DEBUG
    and not SHOW_REMOTE_POS_DEBUG_OVERLAY
    and not REMOTE_POS_DEBUG_CONSOLE then
    return nil
  end

  local ids = {}
  for playerId in pairs(State.otherPlayers) do
    ids[#ids + 1] = playerId
  end
  if #ids == 0 then
    State.remoteDebugLastConsoleLine = nil
    State.remoteDebugTrackedPlayerId = nil
    return nil
  end

  table.sort(ids)
  local remotePlayerId = State.remoteDebugTrackedPlayerId
  if not remotePlayerId or State.otherPlayers[remotePlayerId] == nil then
    remotePlayerId = ids[1]
  end

  local function candidateScore(candidateId)
    local candidateTarget = State.otherPlayers[candidateId]
    local candidateCurrent = Interpolate.getPosition(candidateId) or candidateTarget
    local score = 0
    if type(candidateCurrent) == "table" then
      if tonumber(candidateCurrent.transitionProgress) then
        score = score + 100
      end
      local tx = tonumber(candidateTarget and candidateTarget.x)
      local ty = tonumber(candidateTarget and candidateTarget.y)
      local cx = tonumber(candidateCurrent.x)
      local cy = tonumber(candidateCurrent.y)
      if tx ~= nil and ty ~= nil and cx ~= nil and cy ~= nil then
        score = score + math.abs(tx - cx) + math.abs(ty - cy)
      end
    end
    return score
  end

  local bestScore = candidateScore(remotePlayerId)
  for _, candidateId in ipairs(ids) do
    local score = candidateScore(candidateId)
    if score > bestScore + 0.01 then
      bestScore = score
      remotePlayerId = candidateId
    end
  end
  State.remoteDebugTrackedPlayerId = remotePlayerId

  local targetPos = State.otherPlayers[remotePlayerId]
  if type(targetPos) ~= "table" then
    State.remoteDebugLastConsoleLine = nil
    return nil
  end

  local currentRemotePos = Interpolate.getPosition(remotePlayerId) or targetPos
  local projection = Render.getDebugProjectionSnapshot and
    Render.getDebugProjectionSnapshot(currentPos, currentRemotePos, remotePlayerId) or nil

  local snapshot = {
    playerId = remotePlayerId,
    target = targetPos,
    current = currentRemotePos,
    projected = projection and projection.projected or nil,
    screen = projection and projection.screen or nil,
    crossMap = projection and projection.crossMap == true or false,
    subTileX = projection and projection.subTileX or 0,
    subTileY = projection and projection.subTileY or 0,
    transitionProgress = tonumber(currentRemotePos and currentRemotePos.transitionProgress) or nil,
  }

  if REMOTE_POS_DEBUG_CONSOLE then
    local line = string.format(
      "RemotePos[%s] T=%s | C=%s | P=%s | S=%s | XM:%s | ST:%s,%s | TP:%s",
      remotePlayerId,
      formatDebugPos(snapshot.target),
      formatDebugPos(snapshot.current),
      formatDebugPos(snapshot.projected),
      formatDebugScreen(snapshot.screen),
      snapshot.crossMap and "1" or "0",
      formatDebugNumber(snapshot.subTileX),
      formatDebugNumber(snapshot.subTileY),
      formatDebugNumber(snapshot.transitionProgress)
    )
    if line ~= State.remoteDebugLastConsoleLine then
      log(line)
      State.remoteDebugLastConsoleLine = line
    end
  end

  return snapshot
end

local function drawRemotePositionDebug(snapshot)
  if not SHOW_REMOTE_POS_DEBUG_OVERLAY or not painter or not snapshot then
    return
  end

  local boxY = 14
  local boxH = 54
  local textX = 4

  painter:setFillColor(0xA0000000)
  painter:drawRectangle(0, boxY, W, boxH)

  painter:setFillColor(0xFFFFFF00)
  painter:drawText("RemoteDBG: " .. string.sub(snapshot.playerId, 1, 18), textX, boxY + 1)

  painter:setFillColor(0xFFFFFFFF)
  painter:drawText("T: " .. formatDebugPos(snapshot.target), textX, boxY + 11)
  painter:drawText("C: " .. formatDebugPos(snapshot.current), textX, boxY + 21)
  painter:drawText("P: " .. formatDebugPos(snapshot.projected), textX, boxY + 31)
  painter:drawText(string.format("S: %s  XM:%s  ST:%s,%s  TP:%s",
    formatDebugScreen(snapshot.screen),
    snapshot.crossMap and "1" or "0",
    formatDebugNumber(snapshot.subTileX),
    formatDebugNumber(snapshot.subTileY),
    formatDebugNumber(snapshot.transitionProgress)
  ), textX, boxY + 41)
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
    if ENABLE_DEBUG and SHOW_LOCAL_POS_DEBUG_OVERLAY and currentPos then
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

  if currentPos and (ENABLE_REMOTE_POS_DEBUG or SHOW_REMOTE_POS_DEBUG_OVERLAY or REMOTE_POS_DEBUG_CONSOLE) then
    local remoteDebug = buildRemotePositionDebugSnapshot(currentPos)
    drawRemotePositionDebug(remoteDebug)
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
        Network.send(buildPositionMessage(pos))
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
        local envelope = parseRemotePositionEnvelope(message)
        local rawPosition = clonePosition(message.data) or {}
        rawPosition.mapRev = envelope.mapRev
        rawPosition.metaStable = envelope.metaStable
        rawPosition.metaHash = envelope.metaHash

        -- Feed interpolation buffer with timestamp + duration hint
        Interpolate.update(message.playerId, rawPosition, message.t, message.dur, envelope)
        -- Store raw data as backup + update last seen
        State.otherPlayers[message.playerId] = rawPosition
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

  -- Send sprite update only when local capture confidence is high enough.
  local spriteCaptureConfidence = Sprite.getLocalCaptureConfidence and Sprite.getLocalCaptureConfidence() or 1
  local canSendSpriteNow = spriteCaptureConfidence >= SPRITE_MIN_BROADCAST_CONFIDENCE

  if Sprite.hasChanged() and State.connected and canSendSpriteNow then
    local spriteData = Sprite.getLocalSpriteData()
    if spriteData then
      Network.send({
        type = "sprite_update",
        data = spriteData
      })
      State.lastSpriteSendFrame = State.frameCounter
    end
  elseif State.connected
    and canSendSpriteNow
    and (State.frameCounter - State.lastSpriteSendFrame) >= SPRITE_HEARTBEAT then
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

    local mapChangedAgainstLast = (currentPos.mapId ~= State.lastPosition.mapId)
      or (currentPos.mapGroup ~= State.lastPosition.mapGroup)

    -- Critical: once map metadata settles after a seam transition, push an
    -- immediate corrective packet so peers don't keep transition-frame metadata
    -- until the idle heartbeat.
    -- IMPORTANT: never send this before map-change handling, otherwise a
    -- map-changed packet without transition context can be broadcast first
    -- and force a snap on peers.
    if State.connected and State.mapSync and State.mapSync.justSettled then
      if not mapChangedAgainstLast then
        sendPositionUpdate(currentPos)
        State.lastSentPosition = currentPos
        State.lastIdleHeartbeatFrame = State.frameCounter
        State.mapSync.justSettled = false
        if ENABLE_DEBUG then
          log(string.format(
            "Map transition settle sync sent %d:%d (rev=%d, frame=%d)",
            tonumber(currentPos.mapGroup) or -1,
            tonumber(currentPos.mapId) or -1,
            tonumber(State.mapSync.mapRev) or 0,
            State.frameCounter
          ))
        end
      elseif ENABLE_DEBUG then
        log("Map transition settle sync deferred (map change packet pending)")
      end
    end

    if regainedGameplayPos and State.connected then
      -- Do not emit a regain packet on the same frame as a map change.
      -- The map-change path below must be the first packet so transitionFrom
      -- metadata is preserved for seam interpolation on peers.
      if not mapChangedAgainstLast then
        sendPositionUpdate(currentPos)
        State.lastSentPosition = currentPos
        State.lastIdleHeartbeatFrame = State.frameCounter
      elseif ENABLE_DEBUG then
        log("Regained gameplay position on map change frame: skipping pre-transition sync")
      end
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
        local transitionType = classifyMapTransition(State.lastPosition, currentPos)
        local dropProjectionState = transitionType == "warp_or_hard"
        local cameraDebugBefore = Render.getCameraDebugState and Render.getCameraDebugState() or nil
        local calibrationApplied, calibTx, calibTy, calibVotes, calibSamples = false, nil, nil, nil, nil
        if Render.recordMapTransitionSample then
          calibrationApplied, calibTx, calibTy, calibVotes, calibSamples = Render.recordMapTransitionSample(
            State.lastPosition,
            currentPos,
            transitionType
          )
        end
        if ENABLE_DEBUG then
          log(string.format("Map change %d:%d -> %d:%d (dx=%d dy=%d, type=%s)",
            oldMapGroup, oldMapId, currentPos.mapGroup, currentPos.mapId, dx, dy, transitionType))
          if calibrationApplied then
            log(string.format(
              "Map seam calibration %d:%d <- %d:%d = (%d,%d) votes=%d/%d",
              oldMapGroup,
              oldMapId,
              currentPos.mapGroup,
              currentPos.mapId,
              tonumber(calibTx) or 0,
              tonumber(calibTy) or 0,
              tonumber(calibVotes) or 0,
              tonumber(calibSamples) or 0
            ))
          end
        end

        sendPositionUpdate(currentPos, nil, {
          from = State.lastPosition,
          token = tonumber(State.frameCounter) or 0,
          kind = transitionType
        })
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
        State.sendCooldown = SEND_RATE_MOVING
        State.lastIdleHeartbeatFrame = State.frameCounter
        -- Reset camera tracking only for hard transitions (warp/teleport).
        -- For seam-connected route<->town transitions, keep camera tracking so
        -- sub-tile offset (ST) continues through the crossing step.
        local shouldResetCameraTracking = transitionType == "warp_or_hard"
        local shouldClearGhostCache = transitionType == "warp_or_hard"
        if shouldClearGhostCache then
          Render.clearGhostCache({
            resetCameraTracking = shouldResetCameraTracking,
            dropProjectionState = dropProjectionState
          })
        end
        if ENABLE_DEBUG then
          local cameraDebugAfter = Render.getCameraDebugState and Render.getCameraDebugState() or nil
          local beforeSubX = math.floor(tonumber(cameraDebugBefore and cameraDebugBefore.subTileX) or 0)
          local beforeSubY = math.floor(tonumber(cameraDebugBefore and cameraDebugBefore.subTileY) or 0)
          local afterSubX = math.floor(tonumber(cameraDebugAfter and cameraDebugAfter.subTileX) or 0)
          local afterSubY = math.floor(tonumber(cameraDebugAfter and cameraDebugAfter.subTileY) or 0)
          local warmup = math.floor(tonumber(cameraDebugAfter and cameraDebugAfter.warmupFrames) or 0)
          log(string.format(
            "Map transition camera reset (clearGhostCache=%s, dropProjection=%s, subTile %d,%d -> %d,%d, warmup=%d)",
            tostring(shouldClearGhostCache), tostring(dropProjectionState), beforeSubX, beforeSubY, afterSubX, afterSubY, warmup
          ))
        end
        Duel.reset()
        -- Scan for sWarpData after natural map change (calibrates warp system)
        HAL.findSWarpData()
        -- Reset early detection on map change
        State.earlyDetect.inputDir = nil
        State.earlyDetect.predictedPos = nil
        State.earlyDetect.prevCameraX = nil
        State.earlyDetect.prevCameraY = nil
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

    if not ENABLE_EARLY_PREDICTION then
      ed.inputDir = nil
      ed.inputFrame = 0
      ed.predictedPos = nil
      ed.predictedFrame = 0
    end

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
    if ENABLE_EARLY_PREDICTION and ed.inputDir and cameraDir and not ed.predictedPos then
      if ed.inputDir == cameraDir then
        local gap = State.frameCounter - ed.inputFrame
        if gap <= INPUT_CAMERA_MAX_GAP then
          -- CONFIRMED: compute destination and send immediately
          local delta = DIR_DELTA[ed.inputDir]
          if delta then
            -- Do not predict map-crossing steps. On border transitions, a
            -- pre-sent out-of-map tile (e.g. y=-1) produces a 1-tile ghost
            -- offset until the real map-change packet arrives.
            if wouldPredictionCrossMapBoundary(currentPos, delta) then
              if ENABLE_DEBUG then
                local borderX = tonumber(currentPos.borderX) or -1
                local borderY = tonumber(currentPos.borderY) or -1
                log(string.format(
                  "Skipping prediction at map boundary (%d:%d x=%d y=%d dx=%d dy=%d border=%d,%d)",
                  tonumber(currentPos.mapGroup) or -1,
                  tonumber(currentPos.mapId) or -1,
                  tonumber(currentPos.x) or -1,
                  tonumber(currentPos.y) or -1,
                  tonumber(delta.dx) or 0,
                  tonumber(delta.dy) or 0,
                  borderX,
                  borderY
                ))
              end
            else
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
                sendPositionUpdate(ed.predictedPos, estimatedDur)
                State.lastSentPosition = ed.predictedPos
              end
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
    if ENABLE_EARLY_PREDICTION and ed.predictedPos and positionChanged(currentPos, State.lastPosition) then
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
    Render.updateCamera(
      currentPos.x,
      currentPos.y,
      cameraX,
      cameraY,
      currentPos.mapGroup,
      currentPos.mapId
    )

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
