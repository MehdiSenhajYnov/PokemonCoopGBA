--[[
  Render Module
  Handles ghost player rendering and coordinate conversion

  Uses mGBA 0.11+ Painter API (NOT gui.* which doesn't exist in mGBA)
  The painter object is passed from main.lua's overlay system

  Positioning: Relative to local player (screen center approach).
  The GBA camera always centers on the player, so the player tile
  appears at a fixed screen position. Ghost position is computed as
  a tile delta from the local player.
]]

local Render = {}

-- Configuration
local TILE_SIZE = 16  -- Pixels per tile
local GHOST_SIZE = 14 -- Ghost square size in pixels
local GHOST_COLOR = 0x8000FF00       -- Semi-transparent green (ARGB)
local GHOST_OUTLINE = 0xFF00CC00     -- Opaque darker green for outline
local TEXT_COLOR = 0xFFFFFFFF        -- White text
local TEXT_BG_COLOR = 0xA0000000     -- Semi-transparent black background

-- Screen dimensions (GBA)
local SCREEN_WIDTH = 240
local SCREEN_HEIGHT = 160

-- Player tile top-left on screen (screen center minus half tile)
-- Screen center = (120, 80), tile is 16x16, so top-left = (112, 72)
local PLAYER_SCREEN_X = 112
local PLAYER_SCREEN_Y = 72

function Render.init(config)
  -- Placeholder for future config (custom colors, sprite mode, etc.)
end

--[[
  Convert ghost tile coordinates to screen pixel coordinates
  Uses relative positioning: ghost is at a tile offset from the local player,
  and the local player is always at screen center.
  @param ghostX Ghost tile X
  @param ghostY Ghost tile Y
  @param playerX Local player tile X
  @param playerY Local player tile Y
  @return screenX, screenY in pixels (top-left of ghost tile)
]]
local function ghostToScreen(ghostX, ghostY, playerX, playerY)
  local screenX = PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE
  local screenY = PLAYER_SCREEN_Y + (ghostY - playerY) * TILE_SIZE
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
]]
function Render.drawGhost(painter, playerId, position, playerPos, currentMap)
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

  -- Convert ghost tile coords to screen coords (relative to local player)
  local screenX, screenY = ghostToScreen(position.x, position.y, playerPos.x, playerPos.y)

  -- Skip if off-screen
  if not isOnScreen(screenX, screenY) then
    return
  end

  -- Draw ghost rectangle (filled, semi-transparent)
  painter:setFill(true)
  painter:setStrokeWidth(0)
  painter:setFillColor(GHOST_COLOR)
  painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)

  -- Draw outline
  painter:setFill(false)
  painter:setStrokeWidth(1)
  painter:setStrokeColor(GHOST_OUTLINE)
  painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)

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
  @param otherPlayers Table of {playerId => position}
  @param playerPos Table {x, y, mapId, mapGroup} of local player
  @param currentMap Table {mapId, mapGroup}
  @return number of ghosts drawn
]]
function Render.drawAllGhosts(painter, otherPlayers, playerPos, currentMap)
  if not otherPlayers or not painter then
    return 0
  end

  local count = 0
  for playerId, position in pairs(otherPlayers) do
    Render.drawGhost(painter, playerId, position, playerPos, currentMap)
    count = count + 1
  end

  return count
end

return Render
