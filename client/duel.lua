--[[
  Duel Module — Native GBA Textbox UI

  Handles the duel request/accept/decline flow between two players.
  Uses native Pokemon GBA textboxes (via PokéScript injection) for immersive UI.
  - Proximity trigger: press A near a ghost to send a duel request
  - Native textbox prompts for confirm/accept/decline
  - Cooldown to prevent spam

  The actual warp (battle start) is handled by main.lua when the server sends duel_warp.

  State machine:
    idle → pre_challenge_wait → confirming_challenge → waiting_response → (showing_result | accepted)
    idle → showing_incoming → (accepted | idle)
]]

local Duel = {}

local function log(msg)
  console:log("[Duel] " .. msg)
end

-- Configuration
local TRIGGER_DISTANCE = 2      -- Max tile distance to trigger a duel
local REQUEST_TIMEOUT = 600     -- Frames before pending request expires (~10s)
local COOLDOWN_FRAMES = 120     -- Frames between outgoing requests (~2s)
local RESPONSE_TIMEOUT = 900    -- Frames to wait for opponent response (~15s)
local CHALLENGE_MIN_WAIT_FRAMES = 3   -- Min wait to avoid same-frame A bleed into yes/no
local CHALLENGE_MAX_WAIT_FRAMES = 10  -- Hard cap: open prompt even if A stays held
local YESNO_SENTINEL = 0x007F

-- Textbox module reference (set by init)
local Textbox = nil

-- State machine
local duelState = "idle"  -- "idle" | "pre_challenge_wait" | "confirming_challenge" | "waiting_response" | "showing_result" | "showing_incoming"
local lastRequestFrame = -999   -- Frame of last outgoing request (cooldown)
local prevKeyA = false          -- Previous frame A-button state (edge detect)

-- Context for current duel flow
local ctx = {
  targetId = nil,         -- Target player ID (outgoing challenge)
  targetName = nil,       -- Target player display name
  requesterId = nil,      -- Incoming requester ID
  requesterName = nil,    -- Incoming requester display name
  responseReceived = nil, -- "accepted" | "declined" | nil (stored while waiting for message dismiss)
  stateFrame = 0,         -- Frame when current state started
  flowStartFrame = 0,     -- Frame when current duel flow started (for latency metrics)
  textboxFailed = false,  -- Textbox failed to show (fallback mode)
  yesNoSelection = true,  -- Fallback cursor selection when VAR_RESULT is stuck (true=Yes)
  yesNoFallbackAnnounced = false,
}

-- Fallback overlay state (used when textbox is not configured)
local fallbackPending = nil     -- {id, name, frame} for incoming request (old overlay mode)
local fallbackOutgoing = nil    -- {targetId, frame} for outgoing request (old overlay mode)
local prevKeyB = false

--[[
  Initialize with Textbox module reference.
  @param textboxModule  table  The textbox.lua module
]]
function Duel.init(textboxModule)
  Textbox = textboxModule
end

--[[
  Get a short display name from a player ID.
  @param playerId  string  e.g. "player_1a2b_c3d"
  @return string  Truncated name, max 8 chars
]]
local function displayName(name)
  if not name then return "???" end
  -- If it's a player_xxx ID, extract the meaningful part
  local short = name:match("^player_(.+)$") or name
  return short:sub(1, 8)
end

--[[
  Check if textbox is available for use.
]]
local function canUseTextbox()
  return Textbox and Textbox.isConfigured()
end

local function resetYesNoFallback()
  ctx.yesNoSelection = true
  ctx.yesNoFallbackAnnounced = false
end

local function tryManualYesNoFallback(keyInfo)
  if not Textbox or not Textbox.isActive() or Textbox.getActiveType() ~= "yesno" then
    return nil
  end
  if not Textbox.isPollReady() then
    return nil
  end

  local varResult = Textbox.readVarResult()
  if varResult ~= YESNO_SENTINEL then
    return nil
  end

  if not ctx.yesNoFallbackAnnounced then
    log("yes/no fallback armed (VAR_RESULT stuck at sentinel)")
    ctx.yesNoFallbackAnnounced = true
  end

  if keyInfo.pressedUp or keyInfo.pressedDown or keyInfo.pressedLeft or keyInfo.pressedRight then
    ctx.yesNoSelection = not ctx.yesNoSelection
    log("yes/no fallback cursor -> " .. (ctx.yesNoSelection and "Yes" or "No"))
  end

  if keyInfo.pressedB then
    log("yes/no fallback decision -> No (B)")
    Textbox.clear()
    return false
  end

  if keyInfo.pressedA then
    local decision = ctx.yesNoSelection
    log("yes/no fallback decision -> " .. (decision and "Yes (A)" or "No (A)"))
    Textbox.clear()
    return decision
  end

  return nil
end

-- ========== Proximity Detection (unchanged) ==========

--[[
  Check if button A is pressed near a ghost (trigger for sending duel request).
  Only fires on rising edge (press, not hold).

  @param playerPos   table  {x, y, mapId, mapGroup}
  @param otherPlayers table {playerId => {x, y, mapId, mapGroup, ...}}
  @param keyA        boolean  A button currently held
  @param frameCounter number  Current frame
  @return targetPlayerId, targetName or nil
]]
function Duel.checkTrigger(playerPos, otherPlayers, keyA, frameCounter)
  -- Edge detect: only on press (not hold)
  local pressed = keyA and not prevKeyA
  prevKeyA = keyA

  if not pressed then
    return nil
  end

  -- Don't trigger during active duel flow
  if duelState ~= "idle" then
    return nil
  end

  -- Cooldown check
  if frameCounter - lastRequestFrame < COOLDOWN_FRAMES then
    return nil
  end

  -- Find closest ghost within range on same map
  local bestId, bestDist = nil, math.huge
  for playerId, ghostPos in pairs(otherPlayers) do
    if ghostPos.mapId == playerPos.mapId
      and ghostPos.mapGroup == playerPos.mapGroup then

      local dx = math.abs(ghostPos.x - playerPos.x)
      local dy = math.abs(ghostPos.y - playerPos.y)
      local dist = dx + dy  -- Manhattan distance

      if dist <= TRIGGER_DISTANCE and dist < bestDist then
        bestId = playerId
        bestDist = dist
      end
    end
  end

  return bestId
end

-- ========== Native Textbox State Machine ==========

--[[
  Start a challenge flow (requester side).
  Called when A is pressed near a ghost.

  @param targetId     string  Target player ID
  @param targetName   string  Target display name
  @param frameCounter number  Current frame
  @return boolean  True if challenge flow started
]]
function Duel.startChallenge(targetId, targetName, frameCounter)
  if duelState ~= "idle" then return false end

  ctx.targetId = targetId
  ctx.targetName = displayName(targetName or targetId)
  ctx.stateFrame = frameCounter
  ctx.flowStartFrame = frameCounter
  ctx.responseReceived = nil
  ctx.textboxFailed = false
  resetYesNoFallback()

  if canUseTextbox() then
    -- Wait a few frames to avoid A-button bleed into yes/no,
    -- then open as soon as A is released (with hard max to stay responsive).
    duelState = "pre_challenge_wait"
    log(string.format(
      "startChallenge: entering pre_challenge_wait (min=%d max=%d)",
      CHALLENGE_MIN_WAIT_FRAMES, CHALLENGE_MAX_WAIT_FRAMES))
    return true
  end

  -- No textbox or textbox failed: send request directly (old behavior)
  duelState = "idle"
  return false  -- Caller should send duel_request directly
end

--[[
  Handle incoming duel request from server.
  Shows native textbox prompt.

  @param requesterId   string  Who sent the request
  @param requesterName string  Display name
  @param frameCounter  number  Current frame
]]
function Duel.handleRequest(requesterId, requesterName, frameCounter)
  log("handleRequest: from=" .. (requesterId or "nil") .. " name=" .. (requesterName or "nil") .. " state=" .. duelState)
  -- Ignore if we're already in a duel flow
  if duelState ~= "idle" then
    log("handleRequest: BLOCKED (state=" .. duelState .. ")")
    return
  end

  ctx.requesterId = requesterId
  ctx.requesterName = displayName(requesterName or requesterId)
  ctx.stateFrame = frameCounter
  ctx.flowStartFrame = frameCounter
  ctx.textboxFailed = false
  resetYesNoFallback()

  if canUseTextbox() then
    local text = ctx.requesterName .. " wants to\\nbattle! Accept?"
    log("handleRequest: showing textbox '" .. text .. "'")
    local ok = Textbox.showYesNo(text)
    if ok then
      duelState = "showing_incoming"
      resetYesNoFallback()
      log("handleRequest: state → showing_incoming")
      return
    end
    log("handleRequest: textbox FAILED")
    ctx.textboxFailed = true
  else
    log("handleRequest: textbox not available, using fallback")
  end

  -- Fallback: use old overlay mode
  fallbackPending = {
    id = requesterId,
    name = ctx.requesterName,
    frame = frameCounter
  }
end

--[[
  Store server response to our outgoing challenge.
  Called by main.lua when duel_declined or duel_warp is received.

  @param response  "accepted" | "declined"
]]
function Duel.onResponse(response)
  if duelState == "waiting_response" then
    ctx.responseReceived = response
  end
end

--[[
  Update duel state machine. Call once per frame.
  Returns action string when main.lua needs to act.

  @param frameCounter  number  Current frame
  @param keyA          boolean|table  A currently held, or key info table from main.lua
  @return nil | {action = "send_request", targetId} | {action = "accept", requesterId}
         | {action = "decline", requesterId} | {action = "cancel"}
]]
function Duel.update(frameCounter, keyA)
  local keyInfo = {
    a = false,
    b = false,
    pressedA = false,
    pressedB = false,
    pressedUp = false,
    pressedDown = false,
    pressedLeft = false,
    pressedRight = false,
  }
  if type(keyA) == "table" then
    keyInfo = keyA
    keyA = keyInfo.a
  else
    keyA = keyA and true or false
  end

  -- Tick textbox startup delay
  if Textbox then
    Textbox.tick(frameCounter)
  end

  -- === Native textbox state machine ===

  if duelState == "pre_challenge_wait" then
    -- Open quickly once A is released, with a short min wait and max safety cap.
    local waited = frameCounter - ctx.stateFrame
    local minReached = waited >= CHALLENGE_MIN_WAIT_FRAMES
    local releaseReached = not keyA
    local maxReached = waited >= CHALLENGE_MAX_WAIT_FRAMES
    if minReached and (releaseReached or maxReached) then
      local text = "Challenge " .. ctx.targetName .. "?"
      local reason = releaseReached and "A released" or "max wait reached"
      log(string.format(
        "pre_challenge_wait: showing textbox after %d frames (%s) '%s'",
        waited, reason, text))
      local ok = Textbox.showYesNo(text)
      if ok then
        duelState = "confirming_challenge"
        ctx.stateFrame = frameCounter  -- reset frame count for timeout
        resetYesNoFallback()
        log("startChallenge: state → confirming_challenge")
      else
        log("startChallenge: textbox failed, cancelling")
        duelState = "idle"
        -- Caller logic in main.lua handles the 'false' return from startChallenge,
        -- but here we are async. We could return an action to fallback, but for now just cancel.
      end
    end

  elseif duelState == "confirming_challenge" then
    -- Polling Yes/No for "Challenge [Name]?"
    local result = Textbox.pollYesNo()
    if result == nil then
      result = tryManualYesNoFallback(keyInfo)
    end
    if result == true then
      -- Yes selected → send request, show waiting message
      log("update: Yes selected → sending duel_request to " .. (ctx.targetId or "nil"))
      lastRequestFrame = frameCounter
      resetYesNoFallback()
      if canUseTextbox() then
        Textbox.showMessage("Waiting for\\n" .. ctx.targetName .. "...")
      end
      duelState = "waiting_response"
      ctx.stateFrame = frameCounter
      return {
        action = "send_request",
        targetId = ctx.targetId,
        latencyFrames = frameCounter - (ctx.flowStartFrame or frameCounter),
      }
    elseif result == false then
      -- No selected → back to idle
      log("update: No selected → idle")
      duelState = "idle"
      ctx.targetId = nil
      ctx.targetName = nil
      ctx.responseReceived = nil
      resetYesNoFallback()
    else
      -- Diagnostic: log pollYesNo state every 60 frames
      if (frameCounter - ctx.stateFrame) % 60 == 0 and (frameCounter - ctx.stateFrame) > 0 then
        log(string.format("confirming_challenge: waiting %d frames, pollYesNo=nil (pollReady=%s, active=%s, VAR=0x%04X, TRACE=%d)",
          frameCounter - ctx.stateFrame,
          tostring(Textbox.isPollReady()),
          tostring(Textbox.isActive()),
          Textbox.readVarResult() or 0,
          Textbox.readVar8001 and Textbox.readVar8001() or -1))
      end
    end
    -- Safety timeout: 10 seconds
    if frameCounter - ctx.stateFrame > 600 then
      log("confirming_challenge TIMEOUT — cancelling")
      Textbox.clear()
      duelState = "idle"
      ctx.targetId = nil
      ctx.targetName = nil
      resetYesNoFallback()
    end
    -- nil = still waiting

  elseif duelState == "waiting_response" then
    -- Waiting for opponent's response while "Waiting..." message shows.
    -- Prioritize server response over local dismiss to keep requester/responder in sync.
    if ctx.responseReceived == "accepted" then
      Textbox.clear()
      duelState = "idle"
      ctx.targetId = nil
      ctx.targetName = nil
      ctx.responseReceived = nil
      resetYesNoFallback()
      return { action = "accepted" }
    elseif ctx.responseReceived == "declined" then
      Textbox.clear()
      ctx.responseReceived = nil
      resetYesNoFallback()
      if canUseTextbox() and Textbox.showMessage((ctx.targetName or "Opponent") .. " declined.") then
        duelState = "showing_result"
        ctx.stateFrame = frameCounter
      else
        duelState = "idle"
        ctx.targetId = nil
        ctx.targetName = nil
      end
    else
      -- If player dismisses manually before response, reopen waiting message.
      -- This avoids cancelling locally while server still has a pending request.
      local dismissed = Textbox.pollMessage()
      if dismissed and canUseTextbox() then
        Textbox.showMessage("Waiting for\\n" .. (ctx.targetName or "opponent") .. "...")
      end
    end

    -- Timeout
    if frameCounter - ctx.stateFrame > RESPONSE_TIMEOUT then
      Textbox.clear()
      duelState = "idle"
      ctx.targetId = nil
      ctx.targetName = nil
      ctx.responseReceived = nil
      resetYesNoFallback()
      return { action = "cancel" }
    end

  elseif duelState == "showing_result" then
    -- Showing "[Name] declined." message
    local dismissed = Textbox.pollMessage()
    if dismissed then
      duelState = "idle"
      ctx.targetId = nil
      ctx.targetName = nil
      resetYesNoFallback()
    end
    -- Timeout safety
    if frameCounter - ctx.stateFrame > REQUEST_TIMEOUT then
      Textbox.clear()
      duelState = "idle"
      ctx.targetId = nil
      resetYesNoFallback()
    end

  elseif duelState == "showing_incoming" then
    -- Polling Yes/No for incoming request "[Name] wants to battle!"
    local result = Textbox.pollYesNo()
    if result == nil then
      result = tryManualYesNoFallback(keyInfo)
    end
    if result == true then
      -- Yes = accept
      local reqId = ctx.requesterId
      duelState = "idle"
      ctx.requesterId = nil
      ctx.requesterName = nil
      resetYesNoFallback()
      return {
        action = "accept",
        requesterId = reqId,
        latencyFrames = frameCounter - (ctx.flowStartFrame or frameCounter),
      }
    elseif result == false then
      -- No = decline
      local reqId = ctx.requesterId
      duelState = "idle"
      ctx.requesterId = nil
      ctx.requesterName = nil
      resetYesNoFallback()
      return {
        action = "decline",
        requesterId = reqId,
        latencyFrames = frameCounter - (ctx.flowStartFrame or frameCounter),
      }
    end
    -- Timeout
    if frameCounter - ctx.stateFrame > REQUEST_TIMEOUT then
      local reqId = ctx.requesterId
      Textbox.clear()
      duelState = "idle"
      ctx.requesterId = nil
      ctx.requesterName = nil
      resetYesNoFallback()
      return { action = "decline", requesterId = reqId }
    end
  end

  return nil
end

-- ========== Fallback overlay methods (for when textbox is not configured) ==========

--[[
  Check user input for accept (A) or decline (B) on a fallback pending request.
  @param keyA  boolean  A button held
  @param keyB  boolean  B button held
  @return "accept"|"decline"|nil, requesterId
]]
function Duel.checkResponse(keyA, keyB)
  if not fallbackPending then
    prevKeyA = keyA
    prevKeyB = keyB
    return nil
  end

  local pressedA = keyA and not prevKeyA
  prevKeyA = keyA

  local pressedB = keyB and not prevKeyB
  prevKeyB = keyB

  if pressedA then
    local reqId = fallbackPending.id
    fallbackPending = nil
    return "accept", reqId
  end

  if pressedB then
    local reqId = fallbackPending.id
    fallbackPending = nil
    return "decline", reqId
  end

  return nil
end

--[[
  Record that we sent a duel request (for fallback UI feedback / cooldown).
  @param targetId    string  Target player ID
  @param frameCounter number  Current frame
]]
function Duel.onRequestSent(targetId, frameCounter)
  fallbackOutgoing = { targetId = targetId, frame = frameCounter }
  lastRequestFrame = frameCounter
end

--[[
  Draw fallback duel UI elements using Painter API.
  Only used when native textbox is not configured.
  @param painter  Painter object from overlay
]]
function Duel.drawUI(painter)
  if not painter then return end

  -- Don't draw fallback UI when native textbox is active
  if canUseTextbox() and duelState ~= "idle" then return end

  -- Draw incoming duel request prompt (fallback)
  if fallbackPending then
    local boxW, boxH = 130, 36
    local boxX = math.floor((240 - boxW) / 2)
    local boxY = math.floor((160 - boxH) / 2) - 10

    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(0xE0000000)
    painter:drawRectangle(boxX, boxY, boxW, boxH)

    painter:setFill(false)
    painter:setStrokeWidth(1)
    painter:setStrokeColor(0xFFFFFFFF)
    painter:drawRectangle(boxX, boxY, boxW, boxH)

    painter:setFill(true)
    painter:setStrokeWidth(0)

    local name = string.sub(fallbackPending.name, 1, 12)
    painter:setFillColor(0xFFFFFF00)
    painter:drawText("Duel: " .. name, boxX + 4, boxY + 3)

    painter:setFillColor(0xFF00FF00)
    painter:drawText("[A] Accept", boxX + 4, boxY + 15)

    painter:setFillColor(0xFFFF4444)
    painter:drawText("[B] Decline", boxX + 70, boxY + 15)
    return
  end

  -- Draw outgoing request feedback (fallback)
  if fallbackOutgoing then
    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(0xA0000000)
    painter:drawRectangle(60, 140, 120, 12)

    painter:setFillColor(0xFFFFFF00)
    painter:drawText("Duel request sent...", 64, 141)
  end
end

-- ========== Lifecycle ==========

--[[
  Expire timed-out requests. Call once per frame.
  @param frameCounter number  Current frame
]]
function Duel.tick(frameCounter)
  -- Expire fallback incoming request
  if fallbackPending and (frameCounter - fallbackPending.frame) > REQUEST_TIMEOUT then
    fallbackPending = nil
  end

  -- Expire fallback outgoing request feedback
  if fallbackOutgoing and (frameCounter - fallbackOutgoing.frame) > REQUEST_TIMEOUT then
    fallbackOutgoing = nil
  end
end

--[[
  Clear all duel state (e.g. on disconnect or warp).
]]
function Duel.reset()
  duelState = "idle"
  ctx.targetId = nil
  ctx.targetName = nil
  ctx.requesterId = nil
  ctx.requesterName = nil
  ctx.responseReceived = nil
  ctx.stateFrame = 0
  ctx.flowStartFrame = 0
  ctx.textboxFailed = false
  resetYesNoFallback()
  fallbackPending = nil
  fallbackOutgoing = nil
  prevKeyA = false
  prevKeyB = false
  if Textbox then
    Textbox.clear()
  end
end

--[[
  Check if a duel prompt is currently showing (to suppress other A-button actions).
]]
function Duel.hasPrompt()
  if duelState ~= "idle" then return true end
  return fallbackPending ~= nil
end

--[[
  Check if we're using fallback overlay prompt (not native textbox).
]]
function Duel.hasFallbackPrompt()
  return fallbackPending ~= nil
end

--[[
  Get the current duel state for debugging.
]]
function Duel.getState()
  return duelState
end

--[[
  Check if textbox failed and caller should use direct send.
]]
function Duel.didTextboxFail()
  return ctx.textboxFailed
end

return Duel
