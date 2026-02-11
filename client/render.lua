--[[
  Render Module
  Handles ghost player rendering and coordinate conversion.

  Hybrid OAM renderer:
  - Ghost sprites are injected directly into OBJ VRAM + OAM
  - Painter overlay is used only for labels and fallback debug rectangles
]]

local HAL = require("hal")

local Sprite -- forward declaration, set via Render.setSprite()

local Render = {}

-- Configuration
local TILE_SIZE = 16
local GHOST_SIZE = 14 -- fallback rectangle size when no sprite data/OAM slot
local OAM_PRIORITY = 2
local MAX_GHOSTS = HAL.getGhostMaxSlots() or 6

local RESERVED_PALETTE_SLOTS = {13, 14, 15}

-- Debug fallback colors (ARGB)
local GHOST_COLOR = 0x8000FF00
local GHOST_OUTLINE = 0xFF00CC00
local STATE_COLORS = {
  interpolating = 0x8000FF00,
  idle = 0x8000FF00,
}
local STATE_OUTLINES = {
  interpolating = 0xFF00CC00,
  idle = 0xFF00CC00,
}

local TEXT_COLOR = 0xFFFFFFFF
local TEXT_BG_COLOR = 0xA0000000

local SCREEN_WIDTH = 240
local SCREEN_HEIGHT = 160

-- Player tile top-left on screen (screen center minus half tile)
local PLAYER_SCREEN_X = 112
local PLAYER_SCREEN_Y = 72

-- OAM shape/size encoding lookup
local SHAPE_SIZE_LOOKUP = {
  ["8x8"] = { shape = 0, size = 0 },
  ["16x16"] = { shape = 0, size = 1 },
  ["32x32"] = { shape = 0, size = 2 },
  ["64x64"] = { shape = 0, size = 3 },
  ["16x8"] = { shape = 1, size = 0 },
  ["32x8"] = { shape = 1, size = 1 },
  ["32x16"] = { shape = 1, size = 2 },
  ["64x32"] = { shape = 1, size = 3 },
  ["8x16"] = { shape = 2, size = 0 },
  ["8x32"] = { shape = 2, size = 1 },
  ["16x32"] = { shape = 2, size = 2 },
  ["32x64"] = { shape = 2, size = 3 },
}

-- Sub-tile camera tracking state
local prevCamX, prevCamY
local prevTileX, prevTileY
local subTileX, subTileY = 0, 0

-- Injection state
local slotByPlayer = {}          -- playerId -> vram slot
local ownerBySlot = {}           -- vram slot -> playerId
local slotSpriteHash = {}        -- vram slot -> sprite hash
local paletteHashBySlot = {}     -- palette slot -> hash
local previousOAM = {}           -- OAM indices written during previous frame

local function oamShapeSizeForDimensions(width, height)
  return SHAPE_SIZE_LOOKUP[string.format("%dx%d", width, height)]
end

local function isSameMap(pos, currentMap)
  return pos.mapId == currentMap.mapId and pos.mapGroup == currentMap.mapGroup
end

local function normalizeConnection(conn)
  if type(conn) ~= "table" then
    return nil
  end

  local direction = tonumber(conn.direction)
  local offset = tonumber(conn.offset)
  local mapGroup = tonumber(conn.mapGroup)
  local mapId = tonumber(conn.mapId)

  if not direction or not offset or not mapGroup or not mapId then
    return nil
  end
  if direction < 1 or direction > 4 then
    return nil
  end

  return {
    direction = direction,
    offset = offset,
    mapGroup = mapGroup,
    mapId = mapId,
  }
end

local function findConnectionToMap(connections, targetMap)
  if type(connections) ~= "table" or type(targetMap) ~= "table" then
    return nil
  end

  local targetGroup = tonumber(targetMap.mapGroup)
  local targetId = tonumber(targetMap.mapId)
  if targetGroup == nil or targetId == nil then
    return nil
  end

  for _, rawConn in ipairs(connections) do
    local conn = normalizeConnection(rawConn)
    if conn and conn.mapGroup == targetGroup and conn.mapId == targetId then
      return conn
    end
  end
  return nil
end

local function projectFromLocalConnection(localPos, remotePos, conn)
  local localBorderX = tonumber(localPos.borderX)
  local localBorderY = tonumber(localPos.borderY)
  local remoteBorderX = tonumber(remotePos.borderX)
  local remoteBorderY = tonumber(remotePos.borderY)
  local remoteX = tonumber(remotePos.x)
  local remoteY = tonumber(remotePos.y)

  if remoteX == nil or remoteY == nil then
    return nil, nil
  end

  if conn.direction == 1 then
    if not localBorderY then return nil, nil end
    return remoteX + conn.offset, remoteY + localBorderY
  elseif conn.direction == 2 then
    if not remoteBorderY then return nil, nil end
    return remoteX + conn.offset, remoteY - remoteBorderY
  elseif conn.direction == 3 then
    if not remoteBorderX then return nil, nil end
    return remoteX - remoteBorderX, remoteY + conn.offset
  elseif conn.direction == 4 then
    if not localBorderX then return nil, nil end
    return remoteX + localBorderX, remoteY + conn.offset
  end

  return nil, nil
end

local function projectFromRemoteConnection(localPos, remotePos, conn)
  local localBorderX = tonumber(localPos.borderX)
  local localBorderY = tonumber(localPos.borderY)
  local remoteBorderX = tonumber(remotePos.borderX)
  local remoteBorderY = tonumber(remotePos.borderY)
  local remoteX = tonumber(remotePos.x)
  local remoteY = tonumber(remotePos.y)

  if remoteX == nil or remoteY == nil then
    return nil, nil
  end

  -- Inverse projection of GBAPK formulas when only remote-side connection metadata is available.
  if conn.direction == 1 then
    if not remoteBorderY then return nil, nil end
    return remoteX - conn.offset, remoteY - remoteBorderY
  elseif conn.direction == 2 then
    if not localBorderY then return nil, nil end
    return remoteX - conn.offset, remoteY + localBorderY
  elseif conn.direction == 3 then
    if not localBorderX then return nil, nil end
    return remoteX + localBorderX, remoteY - conn.offset
  elseif conn.direction == 4 then
    if not remoteBorderX then return nil, nil end
    return remoteX - remoteBorderX, remoteY - conn.offset
  end

  return nil, nil
end

local function projectGhostTilePosition(localPos, remotePos)
  if type(localPos) ~= "table" or type(remotePos) ~= "table" then
    return nil, nil, nil
  end

  if localPos.mapId == nil or localPos.mapGroup == nil
      or remotePos.mapId == nil or remotePos.mapGroup == nil then
    return nil, nil, nil
  end

  local remoteX = tonumber(remotePos.x)
  local remoteY = tonumber(remotePos.y)
  if remoteX == nil or remoteY == nil then
    return nil, nil, nil
  end

  if isSameMap(remotePos, localPos) then
    return remoteX, remoteY, false
  end

  -- GBAPK behavior: prefer local map connections for cross-map projection.
  -- Remote-side connections are only a fallback when local metadata is missing.
  local localConn = findConnectionToMap(localPos.connections, remotePos)
  if localConn then
    local projectedX, projectedY = projectFromLocalConnection(localPos, remotePos, localConn)
    if projectedX ~= nil and projectedY ~= nil then
      return projectedX, projectedY, true
    end
  end

  local remoteConn = findConnectionToMap(remotePos.connections, localPos)
  if remoteConn then
    local projectedX, projectedY = projectFromRemoteConnection(localPos, remotePos, remoteConn)
    if projectedX ~= nil and projectedY ~= nil then
      return projectedX, projectedY, true
    end
  end

  return nil, nil, nil
end

local function ghostToScreen(ghostX, ghostY, playerX, playerY, useSubTile)
  local sx = 0
  local sy = 0
  if useSubTile then
    sx = subTileX
    sy = subTileY
  end
  local screenX = math.floor(PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE + sx)
  local screenY = math.floor(PLAYER_SCREEN_Y + (ghostY - playerY) * TILE_SIZE + sy)
  return screenX, screenY
end

local function rectOnScreen(x, y, w, h)
  return x < SCREEN_WIDTH and y < SCREEN_HEIGHT and (x + w) > 0 and (y + h) > 0
end

local function clearPreviousInjectedOAM()
  for _, oamIndex in ipairs(previousOAM) do
    HAL.hideOAMEntry(oamIndex)
  end
  previousOAM = {}
end

local function hideReservedGhostOAM()
  for slot = 0, MAX_GHOSTS - 1 do
    local idx = HAL.getGhostOAMIndexForSlot and HAL.getGhostOAMIndexForSlot(slot) or nil
    if idx ~= nil then
      HAL.hideOAMEntry(idx)
    end
  end
end

local function clearSlotAssignments()
  slotByPlayer = {}
  ownerBySlot = {}
  slotSpriteHash = {}
  paletteHashBySlot = {}
end

local function releaseInactiveSlots(activePlayers)
  for playerId, slot in pairs(slotByPlayer) do
    if not activePlayers[playerId] then
      slotByPlayer[playerId] = nil
      if ownerBySlot[slot] == playerId then
        ownerBySlot[slot] = nil
      end
    end
  end
end

local function allocateVramSlot(playerId, usedSlots)
  local existing = slotByPlayer[playerId]
  if existing ~= nil and not usedSlots[existing] then
    usedSlots[existing] = true
    ownerBySlot[existing] = playerId
    return existing
  end

  for slot = 0, MAX_GHOSTS - 1 do
    if not usedSlots[slot] and (ownerBySlot[slot] == nil or ownerBySlot[slot] == playerId) then
      slotByPlayer[playerId] = slot
      ownerBySlot[slot] = playerId
      usedSlots[slot] = true
      return slot
    end
  end
  return nil
end

local function assignPaletteSlots(ghosts)
  local paletteMap = {}
  local nextPalette = 1

  for _, ghost in ipairs(ghosts) do
    local renderData = ghost.renderData
    local palBank = renderData and tonumber(renderData.palBank) or nil
    if palBank and palBank >= 0 and palBank <= 15 then
      ghost.nativePalBank = palBank
      ghost.paletteSlot = nil
    else
      ghost.nativePalBank = nil
      local hashKey = renderData and tostring(renderData.paletteHash or "") or ""
      if hashKey ~= "" then
        local slot = paletteMap[hashKey]
        if not slot then
          if nextPalette <= #RESERVED_PALETTE_SLOTS then
            slot = RESERVED_PALETTE_SLOTS[nextPalette]
            nextPalette = nextPalette + 1
            paletteMap[hashKey] = slot
          end
        end
        ghost.paletteSlot = slot
      else
        ghost.paletteSlot = nil
      end
    end
  end
end

local function drawFallbackGhost(painter, overlayImage, ghost)
  if overlayImage and Sprite and Sprite.getImageForPlayer then
    local spriteImg, spriteW, spriteH = Sprite.getImageForPlayer(ghost.playerId)
    if spriteImg and spriteW and spriteH and spriteW > 0 and spriteH > 0 then
      local drawX = ghost.screenX - math.floor((spriteW - TILE_SIZE) / 2)
      local drawY = ghost.screenY - (spriteH - TILE_SIZE)
      local drawOk = pcall(overlayImage.drawImage, overlayImage, spriteImg, drawX, drawY)
      if drawOk then
        ghost.drawX = drawX
        ghost.drawY = drawY
        ghost.width = spriteW
        ghost.height = spriteH
        return
      end
    end
  end

  local fillColor = (ghost.state and STATE_COLORS[ghost.state]) or GHOST_COLOR
  local outlineColor = (ghost.state and STATE_OUTLINES[ghost.state]) or GHOST_OUTLINE

  painter:setFill(true)
  painter:setStrokeWidth(0)
  painter:setFillColor(fillColor)
  painter:drawRectangle(ghost.screenX + 1, ghost.screenY + 1, GHOST_SIZE, GHOST_SIZE)

  painter:setFill(false)
  painter:setStrokeWidth(1)
  painter:setStrokeColor(outlineColor)
  painter:drawRectangle(ghost.screenX + 1, ghost.screenY + 1, GHOST_SIZE, GHOST_SIZE)
  painter:setFill(true)
  painter:setStrokeWidth(0)
end

local function drawGhostLabel(painter, playerId, drawX, drawY)
  local label = string.sub(playerId, 1, 10)
  painter:setFillColor(TEXT_BG_COLOR)
  painter:drawRectangle(drawX - 2, drawY - 10, #label * 6 + 4, 10)
  painter:setFillColor(TEXT_COLOR)
  painter:drawText(label, drawX, drawY - 10)
end

local function writeGhostOAMEntry(ghost, oamIndex)
  local shapeSize = oamShapeSizeForDimensions(ghost.width, ghost.height)
  if not shapeSize then
    return false
  end

  local tileIndex = HAL.getGhostTileIndex(ghost.vramSlot)
  if tileIndex == nil then
    return false
  end

  local y = ghost.drawY
  local x = ghost.drawX
  if y < 0 then y = y + 256 end
  if x < 0 then x = x + 512 end

  local attr0 = (y & 0xFF) | ((shapeSize.shape & 0x3) << 14)
  local attr1 = (x & 0x1FF) | ((shapeSize.size & 0x3) << 14)
  if ghost.renderData.hFlip then attr1 = attr1 | (1 << 12) end
  if ghost.renderData.vFlip then attr1 = attr1 | (1 << 13) end

  local palBank = ghost.nativePalBank or ghost.paletteSlot or RESERVED_PALETTE_SLOTS[1]
  local attr2 = (tileIndex & 0x3FF) | ((OAM_PRIORITY & 0x3) << 10) | ((palBank & 0xF) << 12)

  return HAL.writeOAMEntry(oamIndex, attr0, attr1, attr2)
end

local function collectVisibleGhosts(otherPlayers, playerPos)
  local ghostList = {}

  for playerId, data in pairs(otherPlayers) do
    local position, state
    if data.pos then
      position = data.pos
      state = data.state
    else
      position = data
    end

    local projectedX, projectedY, isCrossMap = projectGhostTilePosition(playerPos, position)
    if projectedX ~= nil and projectedY ~= nil then
      local screenX, screenY = ghostToScreen(
        projectedX,
        projectedY,
        playerPos.x,
        playerPos.y,
        true
      )
      local renderData = Sprite and Sprite.getGhostRenderData and Sprite.getGhostRenderData(playerId) or nil

      local width = (renderData and renderData.width) or TILE_SIZE
      local height = (renderData and renderData.height) or (TILE_SIZE * 2)
      if (not renderData) and Sprite and Sprite.getImageForPlayer then
        local _, cachedW, cachedH = Sprite.getImageForPlayer(playerId)
        if cachedW and cachedW > 0 then
          width = cachedW
        end
        if cachedH and cachedH > 0 then
          height = cachedH
        end
      end

      local drawX = screenX - math.floor((width - TILE_SIZE) / 2)
      local drawY = screenY - (height - TILE_SIZE)
      if rectOnScreen(drawX, drawY, width, height) then
        local dx = projectedX - playerPos.x
        local dy = projectedY - playerPos.y
        ghostList[#ghostList + 1] = {
          playerId = playerId,
          position = position,
          state = state,
          crossMap = isCrossMap and true or false,
          renderData = renderData,
          screenX = screenX,
          screenY = screenY,
          drawX = drawX,
          drawY = drawY,
          width = width,
          height = height,
          y = projectedY,
          distance = math.abs(dx) + math.abs(dy),
        }
      end
    end
  end

  table.sort(ghostList, function(a, b)
    if a.distance ~= b.distance then
      return a.distance < b.distance
    end
    return a.y < b.y
  end)

  if #ghostList > MAX_GHOSTS then
    local trimmed = {}
    for i = 1, MAX_GHOSTS do
      trimmed[i] = ghostList[i]
    end
    ghostList = trimmed
  end

  table.sort(ghostList, function(a, b) return a.y < b.y end)
  return ghostList
end

function Render.init(config)
  prevCamX, prevCamY = nil, nil
  prevTileX, prevTileY = nil, nil
  subTileX, subTileY = 0, 0
  clearPreviousInjectedOAM()
  clearSlotAssignments()
end

--[[
  Update sub-tile camera correction. Call once per frame before drawing.
]]
function Render.updateCamera(playerX, playerY, cameraX, cameraY)
  if not cameraX or not cameraY then
    subTileX, subTileY = 0, 0
    prevCamX, prevCamY = nil, nil
    return
  end

  if not prevCamX then
    prevCamX, prevCamY = cameraX, cameraY
    prevTileX, prevTileY = playerX, playerY
    return
  end

  if playerX ~= prevTileX then
    local deltaTiles = playerX - prevTileX
    if math.abs(deltaTiles) <= 2 then
      subTileX = subTileX + deltaTiles * TILE_SIZE
    else
      subTileX = 0
    end
    prevTileX = playerX
  end

  if playerY ~= prevTileY then
    local deltaTiles = playerY - prevTileY
    if math.abs(deltaTiles) <= 2 then
      subTileY = subTileY + deltaTiles * TILE_SIZE
    else
      subTileY = 0
    end
    prevTileY = playerY
  end

  local dx = cameraX - prevCamX
  local dy = cameraY - prevCamY
  if math.abs(dx) <= TILE_SIZE then subTileX = subTileX + dx end
  if math.abs(dy) <= TILE_SIZE then subTileY = subTileY + dy end

  if subTileX > TILE_SIZE then subTileX = TILE_SIZE end
  if subTileX < -TILE_SIZE then subTileX = -TILE_SIZE end
  if subTileY > TILE_SIZE then subTileY = TILE_SIZE end
  if subTileY < -TILE_SIZE then subTileY = -TILE_SIZE end

  prevCamX, prevCamY = cameraX, cameraY
end

function Render.setSprite(spriteModule)
  Sprite = spriteModule
end

--[[
  Remove all injected ghost OAM entries and clear injection caches.
  Call on map changes or when leaving the overworld.
  options:
    preserveCamera=true keeps sub-tile tracking continuity
]]
function Render.clearGhostCache(options)
  options = options or {}
  local preserveCamera = options.preserveCamera == true

  clearPreviousInjectedOAM()
  hideReservedGhostOAM()
  clearSlotAssignments()
  if not preserveCamera then
    prevCamX, prevCamY = nil, nil
    prevTileX, prevTileY = nil, nil
    subTileX, subTileY = 0, 0
  end
end

function Render.hideGhosts()
  clearPreviousInjectedOAM()
  hideReservedGhostOAM()
end

--[[
  Draw all ghost players:
  - write remote sprites to OBJ VRAM/palette if changed
  - write OAM entries each frame
  - draw labels on painter overlay
]]
function Render.drawAllGhosts(painter, overlayImage, otherPlayers, playerPos)
  if not otherPlayers or not painter or not playerPos then
    return 0
  end

  clearPreviousInjectedOAM()

  local ghosts = collectVisibleGhosts(otherPlayers, playerPos)
  if #ghosts == 0 then
    return 0
  end

  local activePlayers = {}
  for _, ghost in ipairs(ghosts) do
    activePlayers[ghost.playerId] = true
  end
  releaseInactiveSlots(activePlayers)
  assignPaletteSlots(ghosts)

  local usedSlots = {}
  for _, ghost in ipairs(ghosts) do
    local data = ghost.renderData
    if data and data.tileBytes and oamShapeSizeForDimensions(ghost.width, ghost.height) then
      local vramSlot = allocateVramSlot(ghost.playerId, usedSlots)
      if vramSlot ~= nil then
        ghost.vramSlot = vramSlot
      end
    end
  end

  local writtenPaletteThisFrame = {}
  local renderedCount = 0

  for _, ghost in ipairs(ghosts) do
    local rendered = false
    local data = ghost.renderData

    if data and ghost.vramSlot ~= nil then
      local spriteKey = data.spriteHash or tostring(data.revision or 0)
      if slotSpriteHash[ghost.vramSlot] ~= spriteKey then
        if HAL.writeGhostTilesToVRAM(ghost.vramSlot, data.tileBytes) then
          slotSpriteHash[ghost.vramSlot] = spriteKey
        else
          ghost.vramSlot = nil
        end
      end

      if ghost.vramSlot ~= nil then
        -- Prefer native palBank captured from sender OAM.
        -- If unavailable, fall back to our reserved OBJ palette slots.
        if not ghost.nativePalBank then
          local paletteSlot = ghost.paletteSlot
          if paletteSlot and data.paletteBgr then
            if not writtenPaletteThisFrame[paletteSlot] then
              local paletteKey = tostring(data.paletteHash or "")
              if HAL.writeGhostPalette(paletteSlot, data.paletteBgr) then
                paletteHashBySlot[paletteSlot] = paletteKey
                writtenPaletteThisFrame[paletteSlot] = true
              else
                ghost.vramSlot = nil
              end
            end
          else
            ghost.vramSlot = nil
          end
        end

        local oamIndex = HAL.getGhostOAMIndexForSlot(ghost.vramSlot)
        if ghost.vramSlot ~= nil and oamIndex and writeGhostOAMEntry(ghost, oamIndex) then
          previousOAM[#previousOAM + 1] = oamIndex
          rendered = true
          renderedCount = renderedCount + 1
        end
      end
    end

    if not rendered then
      drawFallbackGhost(painter, overlayImage, ghost)
    end

    drawGhostLabel(painter, ghost.playerId, ghost.drawX, ghost.drawY)
  end

  return renderedCount
end

return Render
