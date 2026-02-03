--[[
  Interpolation Module
  Provides smooth ghost movement using "animate toward target" approach.

  When a new position snapshot arrives, the ghost smoothly lerps from its
  current visual position toward the new position. The animation duration
  is estimated from the interval between consecutive snapshots, so it
  automatically adapts to any movement speed (walk, run, bike, surf).

  Reference:
  - Gabriel Gambetta: Fast-Paced Multiplayer (entity interpolation)
]]

local Interpolate = {}

-- Configuration
local TELEPORT_THRESHOLD = 10      -- Tile distance considered a teleport
local DEFAULT_ANIM_DURATION = 250  -- Default animation duration in ms (first move)
local MIN_ANIM_DURATION = 50       -- Floor to prevent instant snapping
local MAX_ANIM_DURATION = 500      -- Ceiling to prevent sluggish movement

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
  Update target position for a player.
  Called when a new network update arrives with a timestamp.

  @param playerId  string  Unique player identifier
  @param newPosition  table  {x, y, mapId, mapGroup, facing}
  @param timestamp  number  Sender's time in ms when position was captured
]]
function Interpolate.update(playerId, newPosition, timestamp)
  if not newPosition or not newPosition.x or not newPosition.y then
    return
  end

  timestamp = timestamp or 0

  -- First time seeing this player: snap to position, no animation
  if not players[playerId] then
    players[playerId] = {
      current = copyPos(newPosition),
      lastReceived = copyPos(newPosition),
      lastTimestamp = timestamp,
      state = "idle",
      -- Animation state
      animFrom = nil,
      animTo = nil,
      animProgress = 0,
      animDuration = 0,
    }
    return
  end

  local player = players[playerId]

  -- Teleport detection: map change or large distance jump
  if not isSameMap(player.lastReceived, newPosition)
    or distance(player.lastReceived, newPosition) > TELEPORT_THRESHOLD then
    -- Snap instantly, no animation
    player.current = copyPos(newPosition)
    player.lastReceived = copyPos(newPosition)
    player.lastTimestamp = timestamp
    player.animTo = nil
    player.animProgress = 0
    player.state = "idle"
    return
  end

  -- Estimate animation duration from interval between this and last snapshot
  local interval = timestamp - player.lastTimestamp
  local duration = DEFAULT_ANIM_DURATION
  if interval > 0 then
    duration = interval
  end
  if duration < MIN_ANIM_DURATION then duration = MIN_ANIM_DURATION end
  if duration > MAX_ANIM_DURATION then duration = MAX_ANIM_DURATION end

  -- Start animation from current visual position toward new position
  player.animFrom = copyPos(player.current)
  player.animTo = copyPos(newPosition)
  player.animProgress = 0
  player.animDuration = duration
  player.state = "interpolating"

  player.lastReceived = copyPos(newPosition)
  player.lastTimestamp = timestamp
end

--[[
  Advance interpolation by dt milliseconds for all players.
  Call this once per frame with dt = time since last frame (~16.67ms at 60fps).

  @param dt  number  Elapsed time in ms since last frame
]]
function Interpolate.step(dt)
  dt = dt or 16.67

  for _, player in pairs(players) do
    if player.animTo and player.animDuration > 0 and player.animProgress < 1 then
      player.animProgress = player.animProgress + dt / player.animDuration

      if player.animProgress >= 1 then
        -- Animation complete: snap to target
        player.animProgress = 1
        player.current.x = player.animTo.x
        player.current.y = player.animTo.y
        player.current.mapId = player.animTo.mapId
        player.current.mapGroup = player.animTo.mapGroup
        player.current.facing = player.animTo.facing
        player.animTo = nil
        player.state = "idle"
      else
        -- Mid-animation: lerp between start and target
        local t = player.animProgress
        player.current.x = lerp(player.animFrom.x, player.animTo.x, t)
        player.current.y = lerp(player.animFrom.y, player.animTo.y, t)
        player.current.mapId = player.animTo.mapId
        player.current.mapGroup = player.animTo.mapGroup
        -- Switch facing at halfway point
        if t >= 0.5 then
          player.current.facing = player.animTo.facing
        else
          player.current.facing = player.animFrom.facing
        end
        player.state = "interpolating"
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
