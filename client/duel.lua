--[[
  Duel Warp Module

  Handles the duel request/accept/decline flow between two players.
  - Proximity trigger: press A near a ghost to send a duel request
  - UI prompt: incoming duel requests shown as overlay box
  - Accept/decline via A/B buttons
  - Cooldown to prevent spam

  The actual warp (RAM write + input lock) is handled by main.lua
  when the server sends duel_warp.
]]

local Duel = {}

-- Configuration
local TRIGGER_DISTANCE = 2      -- Max tile distance to trigger a duel
local REQUEST_TIMEOUT = 600     -- Frames before pending request expires (~10s)
local COOLDOWN_FRAMES = 120     -- Frames between outgoing requests (~2s)

-- State
local pendingRequest = nil       -- Incoming request: {id, name, frame}
local outgoingRequest = nil      -- Outgoing request: {targetId, frame}
local lastRequestFrame = -999    -- Frame of last outgoing request (cooldown)
local prevKeyA = false           -- Previous frame A-button state (edge detect)
local prevKeyB = false           -- Previous frame B-button state (edge detect)

--[[
  Check if button A is pressed near a ghost (trigger for sending duel request).
  Only fires on rising edge (press, not hold).

  @param playerPos   table  {x, y, mapId, mapGroup}
  @param otherPlayers table {playerId => {x, y, mapId, mapGroup, ...}}
  @param keyA        boolean  A button currently held
  @param frameCounter number  Current frame
  @return targetPlayerId or nil
]]
function Duel.checkTrigger(playerPos, otherPlayers, keyA, frameCounter)
  -- Edge detect: only on press (not hold)
  local pressed = keyA and not prevKeyA
  prevKeyA = keyA

  if not pressed then
    return nil
  end

  -- Cooldown check
  if frameCounter - lastRequestFrame < COOLDOWN_FRAMES then
    return nil
  end

  -- Don't trigger while we have a pending incoming request
  if pendingRequest then
    return nil
  end

  -- Find closest ghost within range on same map
  for playerId, ghostPos in pairs(otherPlayers) do
    if ghostPos.mapId == playerPos.mapId
      and ghostPos.mapGroup == playerPos.mapGroup then

      local dx = math.abs(ghostPos.x - playerPos.x)
      local dy = math.abs(ghostPos.y - playerPos.y)
      local dist = dx + dy  -- Manhattan distance

      if dist <= TRIGGER_DISTANCE then
        return playerId
      end
    end
  end

  return nil
end

--[[
  Record that we sent a duel request (for UI feedback / cooldown).
  @param targetId    string  Target player ID
  @param frameCounter number  Current frame
]]
function Duel.onRequestSent(targetId, frameCounter)
  outgoingRequest = { targetId = targetId, frame = frameCounter }
  lastRequestFrame = frameCounter
end

--[[
  Handle incoming duel request from server.
  @param requesterId   string  Who sent the request
  @param requesterName string  Display name (truncated playerId)
  @param frameCounter  number  Current frame
]]
function Duel.handleRequest(requesterId, requesterName, frameCounter)
  -- Ignore if we already have a pending request
  if pendingRequest then
    return
  end

  pendingRequest = {
    id = requesterId,
    name = requesterName or requesterId,
    frame = frameCounter
  }
end

--[[
  Check user input for accept (A) or decline (B) on a pending request.
  Returns "accept", "decline", or nil.

  @param keyA  boolean  A button held
  @param keyB  boolean  B button held
  @return "accept" | "decline" | nil
]]
function Duel.checkResponse(keyA, keyB)
  if not pendingRequest then
    prevKeyA = keyA
    prevKeyB = keyB
    return nil
  end

  -- Edge detect on A
  local pressedA = keyA and not prevKeyA
  prevKeyA = keyA

  -- Edge detect on B
  local pressedB = keyB and not prevKeyB
  prevKeyB = keyB

  if pressedA then
    local reqId = pendingRequest.id
    pendingRequest = nil
    return "accept", reqId
  end

  if pressedB then
    local reqId = pendingRequest.id
    pendingRequest = nil
    return "decline", reqId
  end

  return nil
end

--[[
  Get the pending incoming request (for accept message).
  @return requesterId or nil
]]
function Duel.getPendingRequesterId()
  if pendingRequest then
    return pendingRequest.id
  end
  return nil
end

--[[
  Expire timed-out requests. Call once per frame.
  @param frameCounter number  Current frame
]]
function Duel.tick(frameCounter)
  -- Expire incoming request
  if pendingRequest and (frameCounter - pendingRequest.frame) > REQUEST_TIMEOUT then
    pendingRequest = nil
  end

  -- Expire outgoing request feedback
  if outgoingRequest and (frameCounter - outgoingRequest.frame) > REQUEST_TIMEOUT then
    outgoingRequest = nil
  end
end

--[[
  Draw duel UI elements using Painter API.
  @param painter  Painter object from overlay
]]
function Duel.drawUI(painter)
  if not painter then return end

  -- Draw incoming duel request prompt
  if pendingRequest then
    -- Box dimensions
    local boxW, boxH = 130, 36
    local boxX = math.floor((240 - boxW) / 2)
    local boxY = math.floor((160 - boxH) / 2) - 10

    -- Background
    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(0xE0000000)
    painter:drawRectangle(boxX, boxY, boxW, boxH)

    -- Border
    painter:setFill(false)
    painter:setStrokeWidth(1)
    painter:setStrokeColor(0xFFFFFFFF)
    painter:drawRectangle(boxX, boxY, boxW, boxH)

    -- Text
    painter:setFill(true)
    painter:setStrokeWidth(0)

    local name = string.sub(pendingRequest.name, 1, 12)
    painter:setFillColor(0xFFFFFF00)
    painter:drawText("Duel: " .. name, boxX + 4, boxY + 3)

    painter:setFillColor(0xFF00FF00)
    painter:drawText("[A] Accept", boxX + 4, boxY + 15)

    painter:setFillColor(0xFFFF4444)
    painter:drawText("[B] Decline", boxX + 70, boxY + 15)

    -- Timeout bar
    if pendingRequest.frame then
      -- We don't have frameCounter here, so skip timeout bar
      -- (it's purely cosmetic and Duel.tick handles expiry)
    end

    return
  end

  -- Draw outgoing request feedback
  if outgoingRequest then
    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(0xA0000000)
    painter:drawRectangle(60, 140, 120, 12)

    painter:setFillColor(0xFFFFFF00)
    painter:drawText("Duel request sent...", 64, 141)
  end
end

--[[
  Clear all duel state (e.g. on disconnect or warp).
]]
function Duel.reset()
  pendingRequest = nil
  outgoingRequest = nil
  prevKeyA = false
  prevKeyB = false
end

--[[
  Check if a duel prompt is currently showing (to suppress other A-button actions).
]]
function Duel.hasPrompt()
  return pendingRequest ~= nil
end

return Duel
