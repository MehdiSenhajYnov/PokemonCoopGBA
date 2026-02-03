--[[
  Interpolation Module — Waypoint Queue
  Provides smooth ghost movement using a FIFO waypoint queue with
  adaptive catch-up.

  Each network snapshot is enqueued rather than overwriting a single target.
  The ghost consumes waypoints one-by-one in order, guaranteeing the
  displayed path matches the real player's path even at extreme speedhack
  rates (mGBA 2x–250x+).

  Catch-up formula:
    segmentDuration = BASE_DURATION / max(1, queueLength)

  This single expression handles all speeds from 1x to 1000x+ with no
  thresholds, paliers, or special cases.

  Reference:
  - Gabriel Gambetta: Fast-Paced Multiplayer (entity interpolation)
]]

local Interpolate = {}

-- Configuration
local TELEPORT_THRESHOLD = 10  -- Tile distance considered a teleport
local BASE_DURATION = 250      -- Natural step duration in ms (~16 GBA frames)
local MAX_QUEUE_SIZE = 1000    -- Safety cap on queue length

-- Player data storage
local players = {}

--[[
  Copy position fields into a new table
]]
local function copyPos(pos)
  return {
    x = pos.x,
    y = pos.y,
    mapId = pos.mapId,
    mapGroup = pos.mapGroup,
    facing = pos.facing or 1
  }
end

--[[
  Calculate tile distance between two positions
]]
local function distance(pos1, pos2)
  local dx = pos2.x - pos1.x
  local dy = pos2.y - pos1.y
  return math.sqrt(dx * dx + dy * dy)
end

--[[
  Check if two positions are on the same map
]]
local function isSameMap(pos1, pos2)
  return pos1.mapId == pos2.mapId and pos1.mapGroup == pos2.mapGroup
end

--[[
  Linear interpolation between two values
]]
local function lerp(a, b, t)
  return a + (b - a) * t
end

--[[
  Check if two positions are identical (same tile + map)
]]
local function isSamePosition(pos1, pos2)
  return pos1.x == pos2.x
     and pos1.y == pos2.y
     and pos1.mapId == pos2.mapId
     and pos1.mapGroup == pos2.mapGroup
end

--[[
  Get the reference position for comparison (last queue element, or current)
]]
local function lastQueuedPos(player)
  if #player.queue > 0 then
    return player.queue[#player.queue]
  end
  return player.current
end

--[[
  Update target position for a player.
  Called when a new network update arrives.

  @param playerId    string  Unique player identifier
  @param newPosition table   {x, y, mapId, mapGroup, facing}
  @param timestamp   number  (kept for API compat, not used internally)
]]
function Interpolate.update(playerId, newPosition, timestamp)
  if not newPosition or not newPosition.x or not newPosition.y then
    return
  end

  -- First time seeing this player: snap to position, empty queue
  if not players[playerId] then
    players[playerId] = {
      current = copyPos(newPosition),
      queue = {},
      animFrom = nil,
      animProgress = 0,
      state = "idle",
    }
    return
  end

  local player = players[playerId]
  local ref = lastQueuedPos(player)

  -- Teleport detection: map change or large distance jump
  if not isSameMap(ref, newPosition)
    or distance(ref, newPosition) > TELEPORT_THRESHOLD then
    -- Flush queue and snap
    player.current = copyPos(newPosition)
    player.queue = {}
    player.animFrom = nil
    player.animProgress = 0
    player.state = "idle"
    return
  end

  -- Deduplication: ignore if same tile + map as the reference position
  if isSamePosition(ref, newPosition) then
    -- Exception: if only facing changed and queue is empty, update directly
    if ref.facing ~= newPosition.facing and #player.queue == 0 then
      player.current.facing = newPosition.facing
    end
    return
  end

  -- Enqueue waypoint
  table.insert(player.queue, copyPos(newPosition))

  -- Queue overflow safety: flush and snap to latest
  if #player.queue > MAX_QUEUE_SIZE then
    local last = player.queue[#player.queue]
    player.current = copyPos(last)
    player.queue = {}
    player.animFrom = nil
    player.animProgress = 0
    player.state = "idle"
    console:log("[Interpolate] WARNING: queue overflow for " .. playerId .. ", snapping")
  end
end

--[[
  Advance interpolation by dt milliseconds for all players.
  Consumes multiple waypoints per frame when the queue is large (catch-up).

  @param dt  number  Elapsed time in ms since last frame
]]
function Interpolate.step(dt)
  dt = dt or 16.67
  if dt <= 0 then return end

  for _, player in pairs(players) do
    if #player.queue == 0 then
      player.state = "idle"
      player.animFrom = nil
      player.animProgress = 0
    else
      player.state = "interpolating"
      local remaining = dt

      while remaining > 0 and #player.queue > 0 do
        -- Initialize segment start if needed
        if not player.animFrom then
          player.animFrom = copyPos(player.current)
        end

        -- Adaptive duration: inversely proportional to queue size
        local segDuration = BASE_DURATION / math.max(1, #player.queue)

        -- Time left to finish this segment
        local timeLeftInSegment = (1 - player.animProgress) * segDuration

        if remaining >= timeLeftInSegment then
          -- Segment completes within this frame
          remaining = remaining - timeLeftInSegment

          -- Snap to waypoint target
          local target = player.queue[1]
          player.current = copyPos(target)

          -- Pop consumed waypoint
          table.remove(player.queue, 1)

          -- Reset for next segment
          player.animFrom = copyPos(player.current)
          player.animProgress = 0
        else
          -- Frame ends mid-segment
          player.animProgress = player.animProgress + remaining / segDuration

          local t = player.animProgress
          local target = player.queue[1]
          player.current.x = lerp(player.animFrom.x, target.x, t)
          player.current.y = lerp(player.animFrom.y, target.y, t)
          player.current.mapId = target.mapId
          player.current.mapGroup = target.mapGroup

          -- Switch facing at halfway point
          if t >= 0.5 then
            player.current.facing = target.facing
          end

          remaining = 0
        end
      end

      -- After loop: if queue drained, go idle
      if #player.queue == 0 then
        player.state = "idle"
        player.animFrom = nil
        player.animProgress = 0
      end
    end
  end
end

--[[
  Get current interpolated position for a player.
  Returns nil if player is unknown.
]]
function Interpolate.getPosition(playerId)
  if not players[playerId] then
    return nil
  end
  return players[playerId].current
end

--[[
  Get current interpolation state for a player.
  Returns "interpolating", "idle", or nil.
]]
function Interpolate.getState(playerId)
  if not players[playerId] then return nil end
  return players[playerId].state
end

--[[
  Remove a player from interpolation (disconnection).
]]
function Interpolate.remove(playerId)
  players[playerId] = nil
end

--[[
  Get all tracked player IDs.
]]
function Interpolate.getPlayers()
  local list = {}
  for playerId, _ in pairs(players) do
    list[#list + 1] = playerId
  end
  return list
end

--[[
  Set the teleport threshold in tiles.
  @param threshold  number  Distance beyond which to snap instead of interpolate
]]
function Interpolate.setTeleportThreshold(threshold)
  TELEPORT_THRESHOLD = threshold
end

return Interpolate
