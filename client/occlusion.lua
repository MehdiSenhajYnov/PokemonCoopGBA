--[[
  Occlusion Module
  Overdraw BG cover-layer tiles on the overlay to hide ghosts behind
  buildings, trees, and other foreground map objects.

  Method: After each ghost is drawn on the overlay, re-draw the BG1
  (cover layer) tiles that overlap the ghost area. Since these tiles
  are identical to what the GBA already renders, they seamlessly mask
  the ghost behind foreground scenery.

  Uses the Painter API (drawRectangle) for drawing — the canvas layer
  image does not support setPixel or drawImage with small images.
]]

local HAL = require("hal")

local Occlusion = {}

-- BG1 is the cover/foreground layer in the Pokemon Emerald engine
local COVER_BG_INDEX = 1

-- Per-frame cached BG config and scroll
local bgConfig = nil
local bgScrollX = 0
local bgScrollY = 0

-- Tile pixel cache: key -> table grouped by color for efficient Painter calls
-- Format: { {color=0xAARRGGBB, pts={{dx,dy}, ...}}, ... }
-- false = tile was checked and is fully transparent (skip)
local tilePixelCache = {}
local tilePixelCacheCount = 0
local MAX_CACHE_SIZE = 256

--[[
  Convert BGR555 (GBA palette format) to ARGB 0xAARRGGBB
]]
local function bgr555ToARGB(bgr555)
  local r5 = bgr555 & 0x1F
  local g5 = (bgr555 >> 5) & 0x1F
  local b5 = (bgr555 >> 10) & 0x1F
  local r8 = (r5 << 3) | (r5 >> 2)
  local g8 = (g5 << 3) | (g5 >> 2)
  local b8 = (b5 << 3) | (b5 >> 2)
  return 0xFF000000 | (r8 << 16) | (g8 << 8) | b8
end

--[[
  Decode an 8x8 4bpp tile into color-grouped pixel arrays.
  Groups non-transparent pixels by color for efficient Painter batch drawing.
  @param tileData  string  32 bytes of 4bpp pixel data
  @param palette   table   16 ARGB colors (indexed 0-15)
  @param hFlip     boolean
  @param vFlip     boolean
  @return array of {color, pts={{dx,dy},...}} or nil if fully transparent
]]
local function decodeTilePixels(tileData, palette, hFlip, vFlip)
  -- Collect pixels grouped by color
  local colorMap = {}  -- color -> list of {dx, dy}
  local hasPixels = false

  for py = 0, 7 do
    for px = 0, 3 do  -- 4bpp: 2 pixels per byte
      local byteOffset = py * 4 + px
      local b = string.byte(tileData, byteOffset + 1)
      if not b then b = 0 end

      local leftIdx = b & 0x0F
      local rightIdx = (b >> 4) & 0x0F

      local x0, x1, y
      if hFlip then
        x0 = 7 - (px * 2 + 1)
        x1 = x0 + 1
      else
        x0 = px * 2
        x1 = x0 + 1
      end
      y = vFlip and (7 - py) or py

      -- Left pixel (or right if hFlip)
      local idx1 = hFlip and rightIdx or leftIdx
      if idx1 ~= 0 then
        local c = palette[idx1] or 0xFF000000
        if not colorMap[c] then colorMap[c] = {} end
        local pts = colorMap[c]
        pts[#pts + 1] = {x0, y}
        hasPixels = true
      end

      -- Right pixel (or left if hFlip)
      local idx2 = hFlip and leftIdx or rightIdx
      if idx2 ~= 0 then
        local c = palette[idx2] or 0xFF000000
        if not colorMap[c] then colorMap[c] = {} end
        local pts = colorMap[c]
        pts[#pts + 1] = {x1, y}
        hasPixels = true
      end
    end
  end

  if not hasPixels then
    return nil
  end

  -- Convert to array for stable iteration
  local groups = {}
  for color, pts in pairs(colorMap) do
    groups[#groups + 1] = {color = color, pts = pts}
  end
  return groups
end

--[[
  Get or build cached pixel data for a tile.
  @return color-grouped pixel array or nil if tile is empty/transparent
]]
local function getCachedTilePixels(charBase, tileId, palBank, hFlip, vFlip)
  local key = string.format("%d_%d_%d_%s_%s", charBase, tileId, palBank,
    hFlip and "1" or "0", vFlip and "1" or "0")

  local cached = tilePixelCache[key]
  if cached ~= nil then
    if cached == false then return nil end
    return cached
  end

  -- Enforce cache size limit before adding
  if tilePixelCacheCount >= MAX_CACHE_SIZE then
    tilePixelCache = {}
    tilePixelCacheCount = 0
  end

  -- Read tile pixel data from BG VRAM
  local tileData = HAL.readBGTileData(charBase, tileId)
  if not tileData then
    tilePixelCache[key] = false
    return nil
  end

  -- Quick check: if all bytes are zero, tile is fully transparent
  local allZero = true
  for i = 1, #tileData do
    if string.byte(tileData, i) ~= 0 then
      allZero = false
      break
    end
  end
  if allZero then
    tilePixelCache[key] = false
    return nil
  end

  -- Read BG palette
  local palRaw = HAL.readBGPalette(palBank)
  if not palRaw then
    tilePixelCache[key] = false
    return nil
  end

  -- Convert palette to ARGB
  local palette = {}
  for i = 0, 15 do
    if i == 0 then
      palette[i] = 0x00000000
    else
      palette[i] = bgr555ToARGB(palRaw[i])
    end
  end

  local groups = decodeTilePixels(tileData, palette, hFlip, vFlip)
  if not groups then
    tilePixelCache[key] = false
    return nil
  end

  tilePixelCache[key] = groups
  tilePixelCacheCount = tilePixelCacheCount + 1
  return groups
end

--[[
  Initialize the occlusion module.
]]
function Occlusion.init()
  bgConfig = nil
  bgScrollX = 0
  bgScrollY = 0
  tilePixelCache = {}
  tilePixelCacheCount = 0
end

--[[
  Read BG config and scroll registers. Call once per frame before drawing.
]]
function Occlusion.beginFrame()
  bgConfig = HAL.readBGControl(COVER_BG_INDEX)
  if bgConfig then
    bgScrollX, bgScrollY = HAL.readBGScroll(COVER_BG_INDEX)
    if not bgScrollX then
      bgScrollX = 0
      bgScrollY = 0
    end
  end
end

--[[
  Overdraw BG cover-layer tiles on the overlay for a single ghost.
  Reads the BG1 tilemap for tiles overlapping the ghost bounding box,
  and draws non-transparent pixels using the Painter API (1x1 rectangles).

  @param painter   Painter The mGBA Painter object
  @param ghostX    number  Ghost screen X (top-left, pixels)
  @param ghostY    number  Ghost screen Y (top-left, pixels)
  @param ghostW    number  Ghost width in pixels
  @param ghostH    number  Ghost height in pixels
]]
function Occlusion.drawOcclusionForGhost(painter, ghostX, ghostY, ghostW, ghostH)
  if not bgConfig or not painter then
    return
  end

  -- Determine the range of map tiles that overlap the ghost bounding box
  local left = ghostX + bgScrollX
  local top = ghostY + bgScrollY
  local right = left + ghostW - 1
  local bottom = top + ghostH - 1

  local tileXStart = math.floor(left / 8)
  local tileYStart = math.floor(top / 8)
  local tileXEnd = math.floor(right / 8)
  local tileYEnd = math.floor(bottom / 8)

  local charBase = bgConfig.charBaseBlock
  local screenBase = bgConfig.screenBaseBlock
  local screenSize = bgConfig.screenSize

  -- Ensure painter is in fill mode for 1x1 pixel rects
  painter:setFill(true)
  painter:setStrokeWidth(0)

  for ty = tileYStart, tileYEnd do
    for tx = tileXStart, tileXEnd do
      local entry = HAL.readBGTilemapEntry(screenBase, tx, ty, screenSize)
      if entry then
        local tileId = entry & 0x3FF
        if tileId ~= 0 then
          local hFlip = ((entry >> 10) & 1) == 1
          local vFlip = ((entry >> 11) & 1) == 1
          local palBank = (entry >> 12) & 0xF

          local groups = getCachedTilePixels(charBase, tileId, palBank, hFlip, vFlip)
          if groups then
            local baseX = tx * 8 - bgScrollX
            local baseY = ty * 8 - bgScrollY
            -- Draw pixels grouped by color (minimizes setFillColor calls)
            for g = 1, #groups do
              local grp = groups[g]
              painter:setFillColor(grp.color)
              local pts = grp.pts
              for i = 1, #pts do
                local p = pts[i]
                local sx = baseX + p[1]
                local sy = baseY + p[2]
                if sx >= 0 and sx < 240 and sy >= 0 and sy < 160 then
                  painter:drawRectangle(sx, sy, 1, 1)
                end
              end
            end
          end
        end
      end
    end
  end
end

--[[
  Flush the tile pixel cache. Call on map change.
]]
function Occlusion.clearCache()
  tilePixelCache = {}
  tilePixelCacheCount = 0
end

return Occlusion
