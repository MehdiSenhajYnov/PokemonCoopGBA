--[[
  Interpolation Module — Waypoint Queue
  Provides smooth ghost movement using a FIFO waypoint queue with
  adaptive catch-up.

  Each network snapshot is enqueued rather than overwriting a single target.
  The ghost consumes waypoints one-by-one in order, guaranteeing the
  displayed path matches the real player's path even at extreme speedhack
  rates (mGBA 2x–250x+).

  Catch-up formula:
    segmentDuration = waypoint.duration / max(1, queueLength)

  Each waypoint carries a timestamp-derived duration (ms between network
  messages).  This adapts automatically to walk/run/bike/speedhack rates.
  The queue-length divisor provides catch-up when packets arrive faster
  than they are consumed.

  Reference:
  - Gabriel Gambetta: Fast-Paced Multiplayer (entity interpolation)
]]

local Interpolate = {}

-- Configuration
local TELEPORT_THRESHOLD = 10  -- Tile distance considered a teleport
local DEFAULT_DURATION = 266   -- Fallback for 1st message (~16 walk frames at 60fps)
local MIN_DURATION = 10        -- Clamp minimum (ms)
local MAX_DURATION = 2000      -- Clamp maximum (ms)
local MAX_QUEUE_SIZE = 1000    -- Safety cap on queue length

-- Player data storage
local players = {}

--[[
  Copy position fields into a new table
]]
local function copyConnections(connections)
  if type(connections) ~= "table" then
    return nil
  end

  local out = {}
  for _, conn in ipairs(connections) do
    if type(conn) == "table" then
      out[#out + 1] = {
        direction = tonumber(conn.direction),
        offset = tonumber(conn.offset),
        mapGroup = tonumber(conn.mapGroup),
        mapId = tonumber(conn.mapId),
      }
    end
  end
  return out
end

local function copyPos(pos)
  local connections = copyConnections(pos.connections)
  local connectionCount = tonumber(pos.connectionCount)
  if connectionCount == nil and connections then
    connectionCount = #connections
  end

  return {
    x = pos.x,
    y = pos.y,
    mapId = pos.mapId,
    mapGroup = pos.mapGroup,
    facing = pos.facing or 1,
    borderX = pos.borderX,
    borderY = pos.borderY,
    connectionCount = connectionCount,
    connections = connections
  }
end

local function positionMapKey(pos)
  if type(pos) ~= "table" then
    return nil
  end
  if pos.mapGroup == nil or pos.mapId == nil then
    return nil
  end
  return string.format("%d:%d", tonumber(pos.mapGroup) or -1, tonumber(pos.mapId) or -1)
end

local function hasProjectionMeta(pos)
  if type(pos) ~= "table" then
    return false
  end
  local borderX = tonumber(pos.borderX)
  local borderY = tonumber(pos.borderY)
  return borderX ~= nil and borderY ~= nil and borderX > 0 and borderY > 0
end

local function normalizePositionForPlayer(player, pos)
  local normalized = copyPos(pos)
  local key = positionMapKey(pos)
  if not key or not player then
    return normalized
  end

  if hasProjectionMeta(pos) then
    player.metaByMap[key] = {
      borderX = tonumber(pos.borderX),
      borderY = tonumber(pos.borderY),
      connectionCount = tonumber(pos.connectionCount),
      connections = copyConnections(pos.connections),
    }
  else
    local cached = player.metaByMap[key]
    if cached then
      normalized.borderX = cached.borderX
      normalized.borderY = cached.borderY
      normalized.connectionCount = cached.connectionCount
      normalized.connections = copyConnections(cached.connections)
    end
  end

  if normalized.connectionCount == nil and normalized.connections then
    normalized.connectionCount = #normalized.connections
  end
  return normalized
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

  @param playerId     string  Unique player identifier
  @param newPosition  table   {x, y, mapId, mapGroup, facing}
  @param timestamp    number  Sender timeMs (for duration calculation)
  @param durationHint number  Optional: sender-estimated step duration (ms)
]]
function Interpolate.update(playerId, newPosition, timestamp, durationHint)
  if not newPosition or not newPosition.x or not newPosition.y then
    return
  end

  -- First time seeing this player: snap to position, empty queue
  if not players[playerId] then
    local firstPlayer = {
      metaByMap = {},
      current = nil,
      queue = {},
      animFrom = nil,
      animProgress = 0,
      state = "idle",
      lastTimestamp = timestamp,
    }
    firstPlayer.current = normalizePositionForPlayer(firstPlayer, newPosition)
    players[playerId] = firstPlayer
    return
  end

  local player = players[playerId]
  local normalizedPos = normalizePositionForPlayer(player, newPosition)
  local ref = lastQueuedPos(player)

  -- Teleport detection: map change or large distance jump
  if not isSameMap(ref, normalizedPos)
    or distance(ref, normalizedPos) > TELEPORT_THRESHOLD then
    -- Flush queue and snap
    player.current = copyPos(normalizedPos)
    player.queue = {}
    player.animFrom = nil
    player.animProgress = 0
    player.state = "idle"
    return
  end

  -- Deduplication: ignore if same tile + map as the reference position
  if isSamePosition(ref, normalizedPos) then
    -- Exception: if only facing changed and queue is empty, update directly
    if #player.queue == 0 then
      player.current.facing = normalizedPos.facing or player.current.facing
      player.current.borderX = normalizedPos.borderX or player.current.borderX
      player.current.borderY = normalizedPos.borderY or player.current.borderY
      if normalizedPos.connections then
        player.current.connections = copyConnections(normalizedPos.connections)
      end
      if normalizedPos.connectionCount ~= nil then
        player.current.connectionCount = tonumber(normalizedPos.connectionCount)
      elseif player.current.connections then
        player.current.connectionCount = #player.current.connections
      end
    end
    -- Still update lastTimestamp so next duration calc is accurate
    if timestamp then
      player.lastTimestamp = timestamp
    end
    return
  end

  -- Fix 3: Compute duration for this waypoint.
  -- Priority: 1) timestamp delta (consecutive steps — most stable, averaged over full step)
  --           2) sender-estimated hint (camera scroll rate — used for first step after idle)
  --           3) DEFAULT_DURATION (fallback)
  local duration = DEFAULT_DURATION
  if timestamp and player.lastTimestamp then
    local dt = timestamp - player.lastTimestamp
    if dt >= MIN_DURATION and dt <= DEFAULT_DURATION * 2 then
      duration = dt  -- Consecutive step: use actual timing
    elseif durationHint and durationHint >= MIN_DURATION and durationHint <= MAX_DURATION then
      duration = durationHint  -- Idle gap: use camera estimate
    end
  elseif durationHint and durationHint >= MIN_DURATION and durationHint <= MAX_DURATION then
    duration = durationHint  -- No previous timestamp: use camera estimate
  end

  -- Fix 2: Pad duration by 8% to absorb network jitter.
  -- The ghost interpolates slightly slower, so the next waypoint arrives before
  -- the current one finishes. Catch-up formula corrects any accumulation.
  duration = math.floor(duration * 1.08)

  player.lastTimestamp = timestamp

  -- Enqueue waypoint with duration
  local wp = copyPos(normalizedPos)
  wp.duration = duration
  table.insert(player.queue, wp)

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

        -- Adaptive duration: per-waypoint base, inversely proportional to queue size
        local wpDuration = player.queue[1].duration or DEFAULT_DURATION
        -- Fix 5: Softer catch-up curve — halves the acceleration per queue element
        -- Queue 1→/1, 2→/1.5, 3→/2, 5→/3, 10→/5.5 (instead of linear /N)
        local segDuration = wpDuration / math.max(1, 1 + 0.5 * (#player.queue - 1))

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
          player.current.borderX = target.borderX
          player.current.borderY = target.borderY
          player.current.connectionCount = target.connectionCount
          player.current.connections = copyConnections(target.connections)

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
