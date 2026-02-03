--[[
  Render Module
  Handles ghost player rendering and coordinate conversion

  Uses mGBA 0.11+ Painter API (NOT gui.* which doesn't exist in mGBA)
  The painter object is passed from main.lua's overlay system

  Positioning uses tile-delta (known correct) plus a sub-tile correction
  derived from tracking gSpriteCoordOffsetX/Y deltas between frames.
  This avoids needing to know the absolute coordinate system (MAP_OFFSET)
  while still producing pixel-smooth scrolling during walks.
]]

local Render = {}

-- Configuration
local TILE_SIZE = 16  -- Pixels per tile
local GHOST_SIZE = 14 -- Ghost square size in pixels
local GHOST_COLOR = 0x8000FF00       -- Semi-transparent green (ARGB)
local GHOST_OUTLINE = 0xFF00CC00     -- Opaque darker green for outline

-- State-based colors for debug rendering (ARGB)
local STATE_COLORS = {
  interpolating = 0x8000FF00,   -- Green (normal)
  idle          = 0x8000FF00,   -- Green (normal)
}
local STATE_OUTLINES = {
  interpolating = 0xFF00CC00,
  idle          = 0xFF00CC00,
}
local TEXT_COLOR = 0xFFFFFFFF        -- White text
local TEXT_BG_COLOR = 0xA0000000     -- Semi-transparent black background

-- Screen dimensions (GBA)
local SCREEN_WIDTH = 240
local SCREEN_HEIGHT = 160

-- Player tile top-left on screen (screen center minus half tile)
-- Screen center = (120, 80), tile is 16x16, so top-left = (112, 72)
local PLAYER_SCREEN_X = 112
local PLAYER_SCREEN_Y = 72

-- Sub-tile camera tracking state
-- Accumulates camera offset deltas between tile changes for smooth scrolling
local prevCamX, prevCamY
local prevTileX, prevTileY
local subTileX, subTileY = 0, 0

function Render.init(config)
  -- Reset sub-tile tracking
  prevCamX, prevCamY = nil, nil
  prevTileX, prevTileY = nil, nil
  subTileX, subTileY = 0, 0
end

--[[
  Update sub-tile camera correction. Call once per frame before drawing.
  Tracks how much the camera has scrolled since the last tile change,
  producing a smooth ±0..15 pixel correction without needing MAP_OFFSET.

  @param playerX Local player tile X (integer from memory)
  @param playerY Local player tile Y (integer from memory)
  @param cameraX gSpriteCoordOffsetX (signed, from IWRAM) or nil
  @param cameraY gSpriteCoordOffsetY (signed, from IWRAM) or nil
]]
function Render.updateCamera(playerX, playerY, cameraX, cameraY)
  if not cameraX or not cameraY then
    subTileX, subTileY = 0, 0
    prevCamX, prevCamY = nil, nil
    return
  end

  -- First frame: record baseline, no correction yet
  if not prevCamX then
    prevCamX, prevCamY = cameraX, cameraY
    prevTileX, prevTileY = playerX, playerY
    return
  end

  -- X axis
  if playerX ~= prevTileX then
    local deltaTiles = playerX - prevTileX
    if math.abs(deltaTiles) <= 2 then
      -- Normal walk: tile-delta formula just shifted ghosts by deltaTiles*16 pixels,
      -- but camera hasn't scrolled yet. Compensate to keep visual continuity.
      subTileX = subTileX + deltaTiles * TILE_SIZE
    else
      -- Teleport/map change: reset
      subTileX = 0
    end
    prevTileX = playerX
  end

  -- Y axis
  if playerY ~= prevTileY then
    local deltaTiles = playerY - prevTileY
    if math.abs(deltaTiles) <= 2 then
      subTileY = subTileY + deltaTiles * TILE_SIZE
    else
      subTileY = 0
    end
    prevTileY = playerY
  end

  -- Accumulate camera delta (sub-tile scrolling)
  local dx = cameraX - prevCamX
  local dy = cameraY - prevCamY
  if math.abs(dx) <= TILE_SIZE then
    subTileX = subTileX + dx
  end
  if math.abs(dy) <= TILE_SIZE then
    subTileY = subTileY + dy
  end

  -- Clamp to ±1 tile as safety net
  if subTileX > TILE_SIZE then subTileX = TILE_SIZE end
  if subTileX < -TILE_SIZE then subTileX = -TILE_SIZE end
  if subTileY > TILE_SIZE then subTileY = TILE_SIZE end
  if subTileY < -TILE_SIZE then subTileY = -TILE_SIZE end

  prevCamX, prevCamY = cameraX, cameraY
end

--[[
  Convert ghost tile coordinates to screen pixel coordinates.
  Uses tile-delta positioning (correct) plus sub-tile camera correction (smooth).
  @param ghostX Ghost tile X (may be fractional during interpolation)
  @param ghostY Ghost tile Y
  @param playerX Local player tile X
  @param playerY Local player tile Y
  @return screenX, screenY in pixels (top-left of ghost tile)
]]
local function ghostToScreen(ghostX, ghostY, playerX, playerY)
  local screenX = math.floor(PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE + subTileX)
  local screenY = math.floor(PLAYER_SCREEN_Y + (ghostY - playerY) * TILE_SIZE + subTileY)
  return screenX, screenY
end

--[[
  Check if two positions are on the same map
]]
local function isSameMap(pos, currentMap)
  return pos.mapId == currentMap.mapId and pos.mapGroup == currentMap.mapGroup
end

--[[
  Check if screen coordinates are visible
]]
local function isOnScreen(screenX, screenY)
  return screenX >= -GHOST_SIZE and screenX <= SCREEN_WIDTH and
         screenY >= -GHOST_SIZE and screenY <= SCREEN_HEIGHT
end

--[[
  Draw a single ghost player on screen
  @param painter The mGBA Painter object
  @param playerId String identifier for this player
  @param position Table {x, y, mapId, mapGroup, facing}
  @param playerPos Table {x, y, mapId, mapGroup} of local player
  @param currentMap Table {mapId, mapGroup} of local player
  @param state (optional) Interpolation state string for debug coloring
]]
function Render.drawGhost(painter, playerId, position, playerPos, currentMap, state)
  if not position or not position.x or not position.y then
    return
  end

  if not playerPos or not playerPos.x or not playerPos.y then
    return
  end

  -- Only show ghosts on the same map
  if not isSameMap(position, currentMap) then
    return
  end

  -- Convert ghost tile coords to screen coords
  local screenX, screenY = ghostToScreen(position.x, position.y, playerPos.x, playerPos.y)

  -- Skip if off-screen
  if not isOnScreen(screenX, screenY) then
    return
  end

  -- Select color based on interpolation state (debug) or default
  local fillColor = (state and STATE_COLORS[state]) or GHOST_COLOR
  local outlineColor = (state and STATE_OUTLINES[state]) or GHOST_OUTLINE

  -- Draw ghost rectangle (filled, semi-transparent)
  painter:setFill(true)
  painter:setStrokeWidth(0)
  painter:setFillColor(fillColor)
  painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)

  -- Draw outline
  painter:setFill(false)
  painter:setStrokeWidth(1)
  painter:setStrokeColor(outlineColor)
  painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)

  -- Draw facing direction marker (4x4 white square)
  if position.facing then
    local markerX, markerY = screenX + 5, screenY + 5
    if position.facing == 1 then       -- Down
      markerY = screenY + GHOST_SIZE - 2
    elseif position.facing == 2 then   -- Up
      markerY = screenY - 2
    elseif position.facing == 3 then   -- Left
      markerX = screenX - 2
    elseif position.facing == 4 then   -- Right
      markerX = screenX + GHOST_SIZE - 2
    end
    painter:setFill(true)
    painter:setStrokeWidth(0)
    painter:setFillColor(0xFFFFFFFF)
    painter:drawRectangle(markerX, markerY, 4, 4)
  end

  -- Reset to fill mode for text
  painter:setFill(true)
  painter:setStrokeWidth(0)

  -- Draw player name label above the ghost
  local label = string.sub(playerId, 1, 10)
  -- Text background
  painter:setFillColor(TEXT_BG_COLOR)
  painter:drawRectangle(screenX - 2, screenY - 10, #label * 6 + 4, 10)
  -- Text
  painter:setFillColor(TEXT_COLOR)
  painter:drawText(label, screenX, screenY - 10)
end

--[[
  Draw all ghost players from the otherPlayers table
  @param painter The mGBA Painter object
  @param otherPlayers Table of {playerId => {pos=position, state=string}} or {playerId => position}
  @param playerPos Table {x, y, mapId, mapGroup} of local player
  @param currentMap Table {mapId, mapGroup}
  @return number of ghosts drawn
]]
function Render.drawAllGhosts(painter, otherPlayers, playerPos, currentMap)
  if not otherPlayers or not painter then
    return 0
  end

  local count = 0
  for playerId, data in pairs(otherPlayers) do
    local position, state
    if data.pos then
      position = data.pos
      state = data.state
    else
      position = data
    end
    Render.drawGhost(painter, playerId, position, playerPos, currentMap, state)
    count = count + 1
  end

  return count
end

return Render
