--[[
  Sprite Module
  Extracts player sprites from GBA VRAM/OAM/Palette at runtime.
  Reconstructs images for ghost rendering and serializes data for network sync.

  Approach: Each client reads its own player sprite from hardware memory
  and sends the raw tile+palette data to other players. No manual assets needed.
]]

local HAL = require("hal")

local Sprite = {}

-- GBA sprite size lookup table: SIZE_TABLE[shape][sizeCode] = {width, height}
-- shape: 0=Square, 1=Wide, 2=Tall
-- sizeCode: 0-3
local SIZE_TABLE = {
  [0] = { [0] = {8,8},   [1] = {16,16}, [2] = {32,32}, [3] = {64,64} },
  [1] = { [0] = {16,8},  [1] = {32,8},  [2] = {32,16}, [3] = {64,32} },
  [2] = { [0] = {8,16},  [1] = {8,32},  [2] = {16,32}, [3] = {32,64} },
}

-- Ghost opacity (0x00=invisible, 0xFF=opaque). Applied to remote sprites only.
local GHOST_ALPHA = 0xFF  -- Fully opaque

-- Cache for local player sprite
local localCache = {
  tileIndex = nil,
  palBank = nil,
  hFlip = false,
  width = 0,
  height = 0,
  img = nil,
  tileBytes = nil,   -- raw tile data string for network
  palette = nil,     -- palette array (16 ARGB values)
  changed = false,
}

-- Cache for remote player sprites: playerId -> {img, width, height}
local remoteCache = {}

-- No cached OAM index — OAM indices shuffle every frame.
-- We find the player by lowest tileIndex + screen position each frame.

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
  Parse a single OAM entry from raw data.
  Returns table with parsed fields, or nil if entry is disabled/empty.
]]
local function parseOAMEntry(attr0, attr1, attr2)
  if not attr0 or not attr1 or not attr2 then
    return nil
  end

  local yPos = attr0 & 0xFF
  local affineMode = (attr0 >> 8) & 0x3
  -- affineMode=2 means OBJ is disabled (hidden)
  if affineMode == 2 then
    return nil
  end

  local shape = (attr0 >> 14) & 0x3
  local is4bpp = ((attr0 >> 13) & 0x1) == 0

  local xPos = attr1 & 0x1FF
  -- Sign-extend 9-bit X position
  if xPos >= 256 then
    xPos = xPos - 512
  end
  local hFlip = ((attr1 >> 12) & 0x1) == 1
  local vFlip = ((attr1 >> 13) & 0x1) == 1
  local sizeCode = (attr1 >> 14) & 0x3

  local tileIndex = attr2 & 0x3FF
  local priority = (attr2 >> 10) & 0x3
  local palBank = (attr2 >> 12) & 0xF

  -- Look up dimensions
  local sizeEntry = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]
  if not sizeEntry then
    return nil
  end

  return {
    xPos = xPos,
    yPos = yPos,
    shape = shape,
    sizeCode = sizeCode,
    width = sizeEntry[1],
    height = sizeEntry[2],
    tileIndex = tileIndex,
    priority = priority,
    palBank = palBank,
    hFlip = hFlip,
    vFlip = vFlip,
    is4bpp = is4bpp,
    affineMode = affineMode,
  }
end

--[[
  Find the OAM entry for the local player.
  Scans all 128 OAM entries every call (indices shuffle each frame).

  Identification strategy:
  - Player is always a 16x32 tall sprite (shape=2, sizeCode=2)
  - Player tiles are always first loaded in VRAM → lowest tileIndex
  - Positioned at screen center: top-left ~(112, 72)

  Sort-based approach (no hysteresis):
  Among all 16x32 sprites within 40px of center, pick the one with:
  1. Lowest tileIndex (player is always first in VRAM)
  2. Lowest OAM priority (player pri=2 beats reflection pri=3)
  3. Closest to center (tiebreaker)

  Works instantly for all player states (walk, run, bike, surf).
  Returns the parsed entry table (not an index), or nil.
]]
local function findPlayerOAM()
  -- Collect all 16x32 candidates near screen center
  local candidates = {}
  for i = 0, 127 do
    local attr0, attr1, attr2 = HAL.readOAMEntry(i)
    local entry = parseOAMEntry(attr0, attr1, attr2)

    -- Accept 16x32 (walk/run: shape=2) and 32x32 (bike: shape=0), both sizeCode=2
    if entry and entry.sizeCode == 2 and (entry.shape == 2 or entry.shape == 0) then
      local ey = entry.yPos
      if ey > 160 then ey = ey - 256 end

      local cx = entry.xPos + entry.width / 2   -- expected ~120
      local cy = ey + entry.height / 2           -- expected ~88
      local dist = math.abs(cx - 120) + math.abs(cy - 88)

      if dist <= 40 then
        entry.oamIndex = i
        entry._dist = dist
        candidates[#candidates + 1] = entry
      end
    end
  end

  if #candidates == 0 then return nil end

  -- Sort: lowest tileIndex (player first in VRAM),
  -- then lowest priority (player pri=2 beats reflection pri=3),
  -- then closest to center
  table.sort(candidates, function(a, b)
    if a.tileIndex ~= b.tileIndex then
      return a.tileIndex < b.tileIndex
    end
    if a.priority ~= b.priority then
      return a.priority < b.priority
    end
    return a._dist < b._dist
  end)

  local chosen = candidates[1]
  chosen._dist = nil
  return chosen
end

--[[
  Reconstruct an Image from tile data and palette.
  @param tileBytes  string  Raw 4bpp tile data
  @param palette    table   Array of 16 ARGB colors (index 0 = transparent)
  @param width      number  Sprite width in pixels
  @param height     number  Sprite height in pixels
  @param hFlip      boolean Horizontal flip
  @param vFlip      boolean Vertical flip
  @param alpha      number  (optional) Alpha byte 0x00-0xFF to override per-pixel alpha (nil = use palette alpha as-is)
  @return Image object or nil
]]
local function buildImage(tileBytes, palette, width, height, hFlip, vFlip, alpha)
  local ok, img = pcall(image.new, width, height)
  if not ok or not img then
    return nil
  end

  local widthTiles = width / 8
  local heightTiles = height / 8
  local numTiles = widthTiles * heightTiles

  for tileIdx = 0, numTiles - 1 do
    local tileRow = math.floor(tileIdx / widthTiles)
    local tileCol = tileIdx % widthTiles
    local baseOffset = tileIdx * 32

    for py = 0, 7 do
      for px = 0, 3 do -- 4bpp: 2 pixels per byte
        local byteOffset = baseOffset + py * 4 + px
        local b = string.byte(tileBytes, byteOffset + 1) -- Lua 1-indexed
        if not b then b = 0 end

        local leftPixel = b & 0x0F
        local rightPixel = (b >> 4) & 0x0F

        local sx0 = tileCol * 8 + px * 2
        local sx1 = sx0 + 1
        local sy = tileRow * 8 + py

        -- Apply flips
        if hFlip then
          -- Mirror horizontally: swap positions AND pixel order
          sx0 = width - 1 - (tileCol * 8 + px * 2 + 1)
          sx1 = sx0 + 1
        end
        if vFlip then
          sy = height - 1 - sy
        end

        -- Set pixels (palette index 0 = transparent)
        local color0 = palette[leftPixel] or 0x00000000
        local color1 = palette[rightPixel] or 0x00000000
        if leftPixel == 0 then color0 = 0x00000000 end
        if rightPixel == 0 then color1 = 0x00000000 end

        -- Apply alpha override to non-transparent pixels
        if alpha and alpha ~= 0xFF then
          if leftPixel ~= 0 then
            color0 = (alpha << 24) | (color0 & 0x00FFFFFF)
          end
          if rightPixel ~= 0 then
            color1 = (alpha << 24) | (color1 & 0x00FFFFFF)
          end
        end

        if hFlip then
          -- When flipped, right pixel goes to lower X position
          pcall(img.setPixel, img, sx0, sy, color1)
          pcall(img.setPixel, img, sx1, sy, color0)
        else
          pcall(img.setPixel, img, sx0, sy, color0)
          pcall(img.setPixel, img, sx1, sy, color1)
        end
      end
    end
  end

  return img
end

--[[
  Initialize the sprite module.
]]
function Sprite.init()
  localCache.tileIndex = nil
  localCache.palBank = nil
  localCache.img = nil
  localCache.changed = false
  localCache.tileBytes = nil
  localCache.palette = nil
  localCache.hFlip = false
  localCache.width = 0
  localCache.height = 0
  remoteCache = {}
end

--[[
  Capture the local player's sprite from VRAM/OAM/Palette.
  Call once per frame (or every N frames). Only rebuilds the image
  when the tile index or palette bank changes.
]]
function Sprite.captureLocalPlayer()
  -- Find player OAM entry (rescan every call — OAM indices shuffle each frame)
  local entry = findPlayerOAM()
  if not entry then
    localCache.changed = false
    return
  end

  -- Read tile data from VRAM (the animation DMA changes the actual pixel
  -- data at the same tile address, so we compare raw bytes to detect changes)
  local widthTiles = entry.width / 8
  local heightTiles = entry.height / 8
  local numTiles = widthTiles * heightTiles
  local tileBytes = HAL.readSpriteTiles(entry.tileIndex, numTiles)
  if not tileBytes then
    localCache.changed = false
    return
  end

  -- Detect change: VRAM content, hFlip, or palette bank changed
  local changed = (tileBytes ~= localCache.tileBytes)
                or (entry.hFlip ~= localCache.hFlip)
                or (entry.palBank ~= localCache.palBank)

  if not changed then
    localCache.changed = false
    return
  end

  -- Read palette
  local palRaw = HAL.readSpritePalette(entry.palBank)
  if not palRaw then
    localCache.changed = false
    return
  end

  -- Convert palette to ARGB
  local palette = {}
  for i = 0, 15 do
    if i == 0 then
      palette[i] = 0x00000000 -- transparent
    else
      palette[i] = bgr555ToARGB(palRaw[i])
    end
  end

  -- Build image
  local img = buildImage(tileBytes, palette, entry.width, entry.height, entry.hFlip, entry.vFlip)

  -- Update cache
  localCache.tileIndex = entry.tileIndex
  localCache.palBank = entry.palBank
  localCache.hFlip = entry.hFlip
  localCache.width = entry.width
  localCache.height = entry.height
  localCache.img = img
  localCache.tileBytes = tileBytes
  localCache.palette = palette
  localCache.changed = true
end

--[[
  Check if the local player's sprite changed since last capture.
]]
function Sprite.hasChanged()
  return localCache.changed
end

--[[
  Get serializable sprite data for network transmission.
  Returns table with tile bytes (as array of numbers), palette, and dimensions.
]]
function Sprite.getLocalSpriteData()
  if not localCache.tileBytes or not localCache.palette then
    return nil
  end

  -- Convert tile string to array of numbers for JSON serialization
  local tileArray = {}
  for i = 1, #localCache.tileBytes do
    tileArray[i] = string.byte(localCache.tileBytes, i)
  end

  -- Convert 0-indexed palette to 1-indexed array for JSON serialization
  -- (Lua JSON encoders use ipairs for arrays, which starts at index 1)
  local palArray = {}
  for i = 0, 15 do
    palArray[i + 1] = localCache.palette[i] or 0x00000000
  end

  return {
    width = localCache.width,
    height = localCache.height,
    hFlip = localCache.hFlip,
    tiles = tileArray,
    palette = palArray,
  }
end

--[[
  Update cached sprite for a remote player from network data.
  @param playerId  string  Remote player ID
  @param data      table   {width, height, hFlip, tiles (array of numbers), palette (table)}
]]
function Sprite.updateFromNetwork(playerId, data)
  if not data or not data.tiles or not data.palette then
    return
  end

  local width = data.width or 16
  local height = data.height or 32

  -- Convert tile number array back to string
  local bytes = {}
  for i = 1, #data.tiles do
    bytes[i] = string.char(data.tiles[i])
  end
  local tileBytes = table.concat(bytes)

  -- Palette arrives as 1-indexed array (palette[1] = color for index 0, etc.)
  local palette = {}
  for i = 0, 15 do
    if i == 0 then
      palette[i] = 0x00000000 -- index 0 always transparent
    else
      palette[i] = data.palette[i + 1] or 0x00000000
    end
  end

  local img = buildImage(tileBytes, palette, width, height, data.hFlip or false, false, GHOST_ALPHA)

  remoteCache[playerId] = {
    img = img,
    width = width,
    height = height,
  }
end

--[[
  Get the cached Image for a player (local or remote).
  @param playerId  string  Player ID
  @return Image object or nil, width, height
]]
function Sprite.getImageForPlayer(playerId)
  local remote = remoteCache[playerId]
  if remote and remote.img then
    return remote.img, remote.width, remote.height
  end
  return nil, 0, 0
end

--[[
  Get the local player's cached sprite image.
  @return Image or nil, width, height
]]
function Sprite.getLocalImage()
  if localCache.img then
    return localCache.img, localCache.width, localCache.height
  end
  return nil, 0, 0
end

--[[
  Remove cached sprite for a disconnected player.
]]
function Sprite.removePlayer(playerId)
  remoteCache[playerId] = nil
end

return Sprite
