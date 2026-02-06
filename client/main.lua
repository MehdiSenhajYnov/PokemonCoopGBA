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
local configDir = ""
if scriptDir then
  package.path = package.path .. ";" .. scriptDir .. "../?.lua"
  package.path = package.path .. ";" .. scriptDir .. "../?/init.lua"
  configDir = scriptDir .. "../config/"
end

-- Load modules
local HAL = require("hal")
local Network = require("network")
local Render = require("render")
local Interpolate = require("interpolate")
local Sprite = require("sprite")
local Occlusion = require("occlusion")
local Duel = require("duel")
local Battle = require("battle")
-- GameConfig will be loaded dynamically via ROM detection

-- Configuration
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 8080
local SEND_RATE_MOVING = 1     -- Send on exact frame position changes (tiles change ~once per walk anim)
local SEND_RATE_IDLE = 30      -- Send every 30 frames (~2x/sec) in idle for correction
local IDLE_THRESHOLD = 30      -- Frames without movement to consider idle (~0.5sec)
local MAX_MESSAGES_PER_FRAME = 10 -- Limit messages processed per frame
local ENABLE_DEBUG = true

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
  isMoving = false,
  lastMoveFrame = 0,
  sendCooldown = 0,
  lastSentPosition = nil,
  -- Duel warp state machine
  inputsLocked = false,
  unlockFrame = 0,
  warpPhase = nil,       -- nil / "loading" / "waiting_party" / "in_battle" / "returning"
  duelPending = nil,     -- {mapGroup, mapId, x, y, isMaster} when duel warp is pending
  duelOrigin = nil,      -- {x, y, mapGroup, mapId} position before duel (for return)
  opponentParty = nil,   -- 600-byte party data from opponent
  prevInBattle = 0,      -- Previous inBattle value for transition logging
  sentChoice = false,    -- Whether we've sent our choice this turn
  remoteChoiceTimeout = nil, -- Frame when we started waiting for remote choice
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

-- Forward declarations
local readPlayerPosition

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

  -- Initialize HAL with detected config
  HAL.init(detectedConfig)
  log("Using config: " .. (detectedConfig.name or "Unknown"))

  -- Proactively scan for sWarpData (works if game loaded from save)
  HAL.findSWarpData()

  -- Initialize rendering, sprite extraction, and occlusion
  Render.init(detectedConfig)
  Sprite.init()
  Occlusion.init()
  Render.setSprite(Sprite)
  Render.setOcclusion(Occlusion)

  -- Initialize battle module (pass HAL for triggerMapLoad)
  Battle.init(detectedConfig, HAL)
  if Battle.isConfigured() then
    log("Battle module configured")
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

  -- Read BG cover-layer config for occlusion (once per frame)
  Occlusion.beginFrame()

  -- Draw ghost players using interpolated positions
  if State.showGhosts and playerCount > 0 and currentPos then
    local currentMap = {
      mapId = currentPos.mapId,
      mapGroup = currentPos.mapGroup
    }

    -- Build interpolated position table for rendering (with state for debug coloring)
    local interpolatedPlayers = {}
    for playerId, rawPosition in pairs(State.otherPlayers) do
      local interpolated = Interpolate.getPosition(playerId)
      interpolatedPlayers[playerId] = {
        pos = interpolated or rawPosition,
        state = Interpolate.getState(playerId)
      }
    end

    Render.drawAllGhosts(painter, overlay.image, interpolatedPlayers, currentPos, currentMap)
  end

  -- Draw duel UI (request prompt / outgoing feedback)
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

  -- Warp state machine
  if State.inputsLocked then
    -- Phase "loading": CB2_LoadMap is running, wait for completion
    if State.warpPhase == "loading" then
      -- Check if map load finished (callback2 returned to CB2_Overworld)
      if HAL.isWarpComplete() then
        log("Warp complete! callback2 returned to Overworld")
        -- Re-scan sWarpData for future warps (new map has fresh data)
        HAL.findSWarpData()

        -- If this is a duel warp and battle is configured, proceed to party exchange
        if State.duelPending and Battle.isConfigured() then
          -- Send our party data to opponent
          local localParty = Battle.readLocalParty()
          if localParty then
            Network.send({ type = "duel_party", data = localParty })
            log("Sent local party data")
          end

          -- Transition to waiting for opponent's party
          State.warpPhase = "waiting_party"
          State.unlockFrame = State.frameCounter + 600  -- 10 second timeout
          State.inputsLocked = true  -- Keep inputs locked

          -- If we already have opponent's party (they sent first), start battle immediately
          if State.opponentParty then
            local injected = Battle.injectEnemyParty(State.opponentParty)
            if injected then
              local started = Battle.startBattle(State.duelPending.isMaster, State.duelOrigin)
              if started then
                State.warpPhase = "in_battle"
                State.sentChoice = false
                log("PvP battle started (had party already)!")
              end
            end
          end
        else
          -- No battle config or not a duel, just complete normally
          State.inputsLocked = false
          State.warpPhase = nil
          State.duelPending = nil
        end
      elseif State.frameCounter >= State.unlockFrame then
        -- Safety timeout — force unlock to prevent permanent freeze
        State.inputsLocked = false
        State.warpPhase = nil
        State.duelPending = nil
        State.duelOrigin = nil
        log("WARNING: Warp timeout — force unlocked")
      else
        -- Diagnostic: log callback2 every 30 frames to track progress
        if State.frameCounter % 30 == 0 then
          local cb2 = HAL.readCallback2()
          if cb2 then
            log(string.format("Warp loading: callback2=0x%08X (waiting for 0x%08X)",
              cb2, 0x080A89A5))
          end
        end
      end

      -- NO overlay drawing during map load
      if State.connected then Network.flush() end
      return

    -- Phase "waiting_party": waiting for opponent's party data
    elseif State.warpPhase == "waiting_party" then
      -- Timeout check
      if State.frameCounter >= State.unlockFrame then
        log("WARNING: waiting_party timeout — aborting duel")
        State.inputsLocked = false
        State.warpPhase = nil
        State.duelPending = nil
        State.opponentParty = nil
        -- TODO: could trigger return to origin here
      end
      -- Network messages are processed above; duel_party handler will transition to in_battle

    -- Phase "in_battle": PvP battle in progress
    elseif State.warpPhase == "in_battle" then
      -- Tick the battle module
      Battle.tick()

      -- Capture our choice when we make it
      if Battle.hasPlayerChosen() and not State.sentChoice then
        local choice = Battle.captureLocalChoice()
        if choice then
          local rng = nil
          if State.duelPending and State.duelPending.isMaster then
            rng = Battle.readRng()
          end
          Network.send({
            type = "duel_choice",
            choice = choice,
            rng = rng
          })
          State.sentChoice = true
          log(string.format("Sent local choice: %s", choice.action))
        end
      end

      -- Reset sent flag when new turn starts (based on turn count)
      -- This is simplified; proper detection would track turn transitions
      if not Battle.hasPlayerChosen() and State.sentChoice then
        State.sentChoice = false
      end

      -- Timeout for remote choice (30 seconds)
      if Battle.isWaitingForRemote() then
        if not State.remoteChoiceTimeout then
          State.remoteChoiceTimeout = State.frameCounter
        end
        if State.frameCounter - State.remoteChoiceTimeout > 1800 then
          log("Remote choice timeout — using default action")
          Battle.setRemoteChoice({ action = "move", slot = 0, target = 0 })
          State.remoteChoiceTimeout = nil
        end
      else
        State.remoteChoiceTimeout = nil
      end

      -- Check if battle finished
      if Battle.isFinished() then
        local outcome = Battle.getOutcome()
        Network.send({ type = "duel_end", outcome = outcome })
        log(string.format("Battle finished: %s", outcome or "unknown"))

        -- Trigger return to origin
        State.warpPhase = "returning"
        Battle.reset()
      end

    -- Phase "returning": returning to origin after battle
    elseif State.warpPhase == "returning" then
      if State.duelOrigin then
        -- Direct warp back to origin (no save/restore needed — WRAM is preserved)
        local warpOk, warpErr = HAL.performDirectWarp(
          State.duelOrigin.mapGroup,
          State.duelOrigin.mapId,
          State.duelOrigin.x,
          State.duelOrigin.y
        )

        if warpOk then
          log(string.format("Returning to origin: %d:%d (%d,%d)",
            State.duelOrigin.mapGroup, State.duelOrigin.mapId,
            State.duelOrigin.x, State.duelOrigin.y))
          State.warpPhase = "loading_return"
          State.unlockFrame = State.frameCounter + 300
        else
          log("ERROR: Return warp failed: " .. (warpErr or "unknown"))
          State.warpPhase = nil
          State.inputsLocked = false
        end
      else
        log("WARNING: No origin for return")
        State.warpPhase = nil
        State.inputsLocked = false
        State.duelPending = nil
        State.duelOrigin = nil
      end

    -- Phase "loading_return": loading map after return warp
    elseif State.warpPhase == "loading_return" then
      if HAL.isWarpComplete() then
        -- Cleanup
        State.warpPhase = nil
        State.duelPending = nil
        State.duelOrigin = nil
        State.opponentParty = nil
        State.inputsLocked = false
        State.sentChoice = false
        State.remoteChoiceTimeout = nil
        Occlusion.clearCache()
        HAL.findSWarpData()
        log("Returned to origin after duel!")
      elseif State.frameCounter >= State.unlockFrame then
        -- Timeout
        State.warpPhase = nil
        State.duelPending = nil
        State.duelOrigin = nil
        State.opponentParty = nil
        State.inputsLocked = false
        log("WARNING: Return warp timeout — force unlocked")
      end

      if State.connected then Network.flush() end
      return

    -- Legacy fallback (non-warp input lock)
    else
      if State.frameCounter >= State.unlockFrame then
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
    Duel.reset()
    Battle.reset()
    -- Cancel pending duel on disconnect (any phase)
    if State.duelPending then
      State.duelPending = nil
      State.duelOrigin = nil
      State.opponentParty = nil
      State.inputsLocked = false
      State.warpPhase = nil
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
      Network.send({ type = "register", playerId = State.playerId })
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

      elseif message.type == "sprite_update" then
        Sprite.updateFromNetwork(message.playerId, message.data)

      elseif message.type == "player_disconnected" then
        Interpolate.remove(message.playerId)
        Sprite.removePlayer(message.playerId)
        State.otherPlayers[message.playerId] = nil
        log("Player " .. message.playerId .. " disconnected")

      elseif message.type == "registered" then
        log("Registered with ID: " .. message.playerId)
        State.playerId = message.playerId

      elseif message.type == "joined" then
        log("Joined room: " .. message.roomId)

      elseif message.type == "duel_request" then
        -- Incoming duel request from another player
        Duel.handleRequest(message.requesterId, message.requesterName, State.frameCounter)
        log("Duel request from: " .. (message.requesterName or message.requesterId))

      elseif message.type == "duel_warp" then
        -- Server says warp to duel room
        if not message.coords then
          log("ERROR: duel_warp missing coords")
        else
          local coords = message.coords
          local isMaster = message.isMaster or false
          log(string.format("Duel warp received: %d:%d (%d,%d) master=%s",
            coords.mapGroup, coords.mapId, coords.x, coords.y, tostring(isMaster)))
          Duel.reset()

          -- Save origin position for return after battle
          local currentPos = readPlayerPosition()
          if currentPos then
            State.duelOrigin = {
              x = currentPos.x,
              y = currentPos.y,
              mapGroup = currentPos.mapGroup,
              mapId = currentPos.mapId
            }
          end

          State.duelPending = {
            mapGroup = coords.mapGroup,
            mapId = coords.mapId,
            x = coords.x,
            y = coords.y,
            isMaster = isMaster
          }

          -- === DIRECT WARP: write sWarpDestination + trigger CB2_LoadMap ===
          local warpOk, warpErr = HAL.performDirectWarp(
            coords.mapGroup, coords.mapId, coords.x, coords.y)

          if warpOk then
            State.inputsLocked = true
            State.warpPhase = "loading"
            State.unlockFrame = State.frameCounter + 300
            log("Direct warp initiated — CB2_LoadMap will execute next frame")
          else
            log("ERROR: Direct warp failed: " .. (warpErr or "unknown"))
            State.duelPending = nil
            State.duelOrigin = nil
            -- Notify server so opponent isn't stuck waiting
            if State.connected then
              Network.send({ type = "duel_cancelled" })
            end
          end

          -- Reset early detection + occlusion cache
          State.earlyDetect.inputDir = nil
          State.earlyDetect.predictedPos = nil
          Occlusion.clearCache()
        end

      elseif message.type == "duel_cancelled" then
        -- Requester disconnected, clear our prompt and pending duel
        Duel.reset()
        if State.duelPending then
          State.duelPending = nil
          State.duelOrigin = nil
          State.inputsLocked = false
          State.warpPhase = nil
        end
        log("Duel cancelled (requester disconnected)")

      elseif message.type == "duel_declined" then
        log("Duel was declined")

      elseif message.type == "duel_party" then
        -- Received opponent's party data for PvP battle
        State.opponentParty = message.data
        log(string.format("Received opponent party data (%d bytes)", #message.data))

        -- If we were waiting for party data to start battle, proceed
        if State.warpPhase == "waiting_party" and State.duelPending and Battle.isConfigured() then
          -- Inject opponent's party
          local injected = Battle.injectEnemyParty(State.opponentParty)
          if injected then
            -- Start the battle
            local started = Battle.startBattle(State.duelPending.isMaster, State.duelOrigin)
            if started then
              State.warpPhase = "in_battle"
              State.sentChoice = false
              log("PvP battle started!")
            else
              log("ERROR: Failed to start battle")
              State.warpPhase = nil
              State.duelPending = nil
            end
          else
            log("ERROR: Failed to inject opponent party")
          end
        end

      elseif message.type == "duel_choice" then
        -- Received opponent's battle choice
        if Battle.isActive() then
          Battle.setRemoteChoice(message.choice)
          if message.rng and State.duelPending and not State.duelPending.isMaster then
            Battle.onRngSync(message.rng)
          end
          log(string.format("Received remote choice: %s", message.choice.action))
        end

      elseif message.type == "duel_rng_sync" then
        -- Received RNG sync from master
        if Battle.isActive() then
          Battle.onRngSync(message.rng)
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
        -- Trigger return to origin
        if State.duelOrigin then
          State.warpPhase = "returning"
        else
          State.warpPhase = nil
          State.duelPending = nil
          State.inputsLocked = false
        end

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

  -- Read current position
  local currentPos = readPlayerPosition()

  -- Capture local player sprite from VRAM (only rebuilds image when sprite changes)
  Sprite.captureLocalPlayer()

  -- Duel module tick (expire timeouts)
  Duel.tick(State.frameCounter)

  -- Read A/B buttons for duel interaction
  local keyA, keyB = HAL.readButtons()

  -- Check for duel response (accept/decline) if prompt is showing
  if Duel.hasPrompt() then
    local response, reqId = Duel.checkResponse(keyA, keyB)
    if response == "accept" and reqId and State.connected then
      Network.send({ type = "duel_accept", requesterId = reqId })
      log("Accepted duel from: " .. reqId)
    elseif response == "decline" and reqId and State.connected then
      Network.send({ type = "duel_decline", requesterId = reqId })
      log("Declined duel from: " .. reqId)
    end
  else
    -- Check for duel trigger (A near ghost) — only when no prompt is showing
    if currentPos and State.connected then
      local targetId = Duel.checkTrigger(currentPos, State.otherPlayers, keyA, State.frameCounter)
      if targetId then
        Network.send({ type = "duel_request", targetId = targetId })
        Duel.onRequestSent(targetId, State.frameCounter)
        log("Duel request sent to: " .. targetId)
      end
    end
  end

  -- Send sprite update if sprite changed
  if Sprite.hasChanged() and State.connected then
    local spriteData = Sprite.getLocalSpriteData()
    if spriteData then
      Network.send({
        type = "sprite_update",
        data = spriteData
      })
    end
  end

  if currentPos then
    -- Read camera early (needed for early movement detection AND render)
    local cameraX = HAL.readCameraX()
    local cameraY = HAL.readCameraY()

    -- Detect movement state
    if positionChanged(currentPos, State.lastPosition) then
      -- Check for map change → immediate send + clear caches
      local mapChanged = currentPos.mapId ~= State.lastPosition.mapId
                      or currentPos.mapGroup ~= State.lastPosition.mapGroup
      if mapChanged then
        sendPositionUpdate(currentPos)
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
        State.sendCooldown = SEND_RATE_MOVING
        Occlusion.clearCache()
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
    end

    State.sendCooldown = math.max(0, State.sendCooldown - 1)

    -- Update sub-tile camera tracking for smooth ghost scrolling
    Render.updateCamera(currentPos.x, currentPos.y, cameraX, cameraY)

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
  -- Clean up interpolation for all tracked players
  for _, playerId in ipairs(Interpolate.getPlayers()) do
    Interpolate.remove(playerId)
  end

  -- Clean up battle state
  Battle.reset()

  log("Disconnecting from server...")
  Network.disconnect()
end)

log("Script loaded successfully!")
log("Press Ctrl+R to reload this script")
