--[[
  find_tile_references.lua
  Scans memory for references to known player tile VRAM addresses.

  The player sprite tiles in mGBA's Tiles viewer are at known VRAM
  addresses (e.g. 0x060100C0, 0x060100E0, ...). This script:

  1. Shows the tile data at those addresses (to confirm they're populated)
  2. Scans gSprites[] for entries whose tileNum/sheetTileStart match
  3. Scans all of WRAM for 32-bit pointers to those VRAM addresses
  4. Scans all of WRAM for 16-bit values matching the tile indices
  5. Runs in background to track if any of it changes over time
]]

local WRAM = emu.memory.wram
local VRAM = emu.memory.vram
local OAM  = emu.memory.oam

-- Known VRAM base for OBJ tiles
local OBJ_VRAM_BASE = 0x06010000

-- Player tile addresses from mGBA Tiles viewer (user-reported)
-- 0x060100C0 = tile index 6 (offset 0xC0 / 32 = 6)
-- For a 16x32 4bpp sprite, 8 consecutive tiles: indices 6-13
local PLAYER_TILE_BASE = 0x060100C0
local PLAYER_TILE_INDEX = (PLAYER_TILE_BASE - OBJ_VRAM_BASE) / 32  -- = 6

-- gSprites known base
local GSPRITES_BASE = 0x020212F0 - 0x02000000
local SPRITE_SIZE = 0x44
local MAX_SPRITES = 64

console:log("=============================================")
console:log("  Tile Reference Scanner")
console:log("  Player tiles at VRAM 0x060100C0 (index 6)")
console:log("=============================================")
console:log("")

-- ===================================================================
-- STEP 1: Show tile data at the known VRAM addresses
-- Confirm tiles are populated (not all zeros)
-- ===================================================================

console:log("[Step 1] Tile data at known VRAM addresses:")
console:log("")

-- OBJ VRAM starts at offset 0x10000 in the VRAM address space
-- emu.memory.vram maps 0x06000000, so OBJ tiles are at offset 0x10000+
local VRAM_OBJ_OFFSET = 0x10000

for tileIdx = 4, 15 do
  local vramAddr = OBJ_VRAM_BASE + tileIdx * 32
  local vramOffset = VRAM_OBJ_OFFSET + tileIdx * 32

  -- Read first 8 bytes of tile to check if populated
  local b0 = VRAM:read8(vramOffset)
  local b1 = VRAM:read8(vramOffset + 1)
  local b2 = VRAM:read8(vramOffset + 2)
  local b3 = VRAM:read8(vramOffset + 3)
  local b4 = VRAM:read8(vramOffset + 4)
  local b5 = VRAM:read8(vramOffset + 5)
  local b6 = VRAM:read8(vramOffset + 6)
  local b7 = VRAM:read8(vramOffset + 7)

  local isEmpty = (b0 == 0 and b1 == 0 and b2 == 0 and b3 == 0
               and b4 == 0 and b5 == 0 and b6 == 0 and b7 == 0)

  local marker = ""
  if tileIdx >= 6 and tileIdx <= 13 then
    marker = " <-- player tile?"
  end
  if isEmpty then
    marker = marker .. " (EMPTY)"
  end

  console:log(string.format("  Tile %2d (0x%08X): %02X %02X %02X %02X %02X %02X %02X %02X ...%s",
    tileIdx, vramAddr, b0, b1, b2, b3, b4, b5, b6, b7, marker))
end

console:log("")

-- ===================================================================
-- STEP 2: Scan gSprites for entries with matching tileNum or sheetTileStart
-- ===================================================================

console:log("[Step 2] gSprites entries with tileNum or sheet near index 6:")
console:log("")

local foundInGSprites = {}

for idx = 0, MAX_SPRITES - 1 do
  local off = GSPRITES_BASE + idx * SPRITE_SIZE
  if off + SPRITE_SIZE <= 0x40000 then
    local flagsWord = WRAM:read16(off + 0x3E)
    local inUse = (flagsWord & 0x01) ~= 0

    if inUse then
      local a0 = WRAM:read16(off)
      local a1 = WRAM:read16(off + 0x02)
      local a2 = WRAM:read16(off + 0x04)
      local tileNum = a2 & 0x3FF
      local palNum = (a2 >> 12) & 0xF
      local hFlip = ((a1 >> 12) & 1) ~= 0
      local shape = (a0 >> 14) & 0x3
      local size = (a1 >> 14) & 0x3
      local sheet = WRAM:read16(off + 0x40)

      local posX = WRAM:read16(off + 0x20)
      local posY = WRAM:read16(off + 0x22)
      if posX >= 0x8000 then posX = posX - 0x10000 end
      if posY >= 0x8000 then posY = posY - 0x10000 end

      -- Also read x2/y2 sub-offsets (+0x24, +0x26)
      local x2 = WRAM:read16(off + 0x24)
      local y2 = WRAM:read16(off + 0x26)
      if x2 >= 0x8000 then x2 = x2 - 0x10000 end
      if y2 >= 0x8000 then y2 = y2 - 0x10000 end

      -- Check if tileNum or sheet matches player tile range (4-15 for broad search)
      local matchTile = (tileNum >= 4 and tileNum <= 15)
      local matchSheet = (sheet >= 4 and sheet <= 15)

      -- Also show all 16x32 sprites regardless
      local is16x32 = (shape == 2 and size == 2)

      if matchTile or matchSheet or is16x32 then
        local marker = ""
        if tileNum == PLAYER_TILE_INDEX then marker = marker .. " TILE=6!" end
        if sheet == PLAYER_TILE_INDEX then marker = marker .. " SHEET=6!" end
        if is16x32 then marker = marker .. " [16x32]" end

        console:log(string.format(
          "  gSprites[%2d]: tileNum=%3d sheet=%3d pal=%d shape=%d size=%d hFlip=%-5s pos=(%d,%d) x2/y2=(%d,%d)%s",
          idx, tileNum, sheet, palNum, shape, size, tostring(hFlip), posX, posY, x2, y2, marker))

        table.insert(foundInGSprites, {
          idx = idx, tileNum = tileNum, sheet = sheet,
          posX = posX, posY = posY, shape = shape, size = size
        })
      end
    end
  end
end

if #foundInGSprites == 0 then
  console:log("  No gSprites entries found matching tile range 4-15 or 16x32 shape.")
end

console:log("")

-- ===================================================================
-- STEP 3: Scan WRAM for 32-bit pointers to VRAM tile addresses
-- Looking for any word == 0x060100C0, 0x060100E0, etc.
-- ===================================================================

console:log("[Step 3] Scanning WRAM for 32-bit pointers to player VRAM tiles...")
console:log("")

local pointerHits = {}

-- Search for pointers to tile addresses (tiles 6-13)
for tileIdx = 6, 13 do
  local targetAddr = OBJ_VRAM_BASE + tileIdx * 32
  local found = false

  -- Scan WRAM 4-byte aligned
  for wramOff = 0, 0x3FFFC, 4 do
    local val = WRAM:read32(wramOff)
    if val == targetAddr then
      local absAddr = wramOff + 0x02000000
      console:log(string.format("  0x%08X contains pointer 0x%08X (tile %d)",
        absAddr, targetAddr, tileIdx))
      table.insert(pointerHits, { addr = wramOff, target = targetAddr, tileIdx = tileIdx })
      found = true
    end
  end

  if not found then
    -- Also try unaligned (2-byte aligned)
    for wramOff = 2, 0x3FFFE, 4 do
      local val = WRAM:read32(wramOff)
      if val == targetAddr then
        local absAddr = wramOff + 0x02000000
        console:log(string.format("  0x%08X contains pointer 0x%08X (tile %d) [unaligned]",
          absAddr, targetAddr, tileIdx))
        table.insert(pointerHits, { addr = wramOff, target = targetAddr, tileIdx = tileIdx })
        found = true
      end
    end
  end
end

if #pointerHits == 0 then
  console:log("  No 32-bit pointers to tile VRAM addresses found in WRAM.")
end

console:log("")

-- ===================================================================
-- STEP 4: Scan WRAM for 16-bit values matching tile index 6
-- This would match oam.tileNum or sheetTileStart fields
-- Only show results near known struct arrays to reduce noise
-- ===================================================================

console:log("[Step 4] Scanning WRAM for 16-bit value = 6 (tile index)...")
console:log("  (Filtering: only showing hits in gSprites region or near known structs)")
console:log("")

local tileIdxHits = 0

-- Focused scan: within gSprites array region
local gspritesStart = GSPRITES_BASE
local gspritesEnd = GSPRITES_BASE + MAX_SPRITES * SPRITE_SIZE

for wramOff = gspritesStart, gspritesEnd, 2 do
  local val = WRAM:read16(wramOff)
  if val == PLAYER_TILE_INDEX then
    local absAddr = wramOff + 0x02000000
    -- Figure out which sprite entry and which offset within it
    local relToBase = wramOff - gspritesStart
    local spriteIdx = math.floor(relToBase / SPRITE_SIZE)
    local offsetInSprite = relToBase % SPRITE_SIZE

    console:log(string.format("  0x%08X = %d  (gSprites[%d] + 0x%02X)",
      absAddr, val, spriteIdx, offsetInSprite))
    tileIdxHits = tileIdxHits + 1
  end
end

if tileIdxHits == 0 then
  console:log("  No 16-bit value = 6 found in gSprites region.")
end

console:log("")

-- ===================================================================
-- STEP 5: Also scan WRAM broadly for the tile index in sheetTileStart
-- positions (offset 0x40 within each potential 0x44-aligned struct)
-- ===================================================================

console:log("[Step 5] Broad scan: WRAM 16-bit = 6 at 0x44-aligned +0x40 offsets...")
console:log("  (Matching sheetTileStart field pattern)")
console:log("")

local broadHits = 0
for base = 0, 0x3FF00, 0x44 do
  local off = base + 0x40
  if off + 2 <= 0x40000 then
    local val = WRAM:read16(off)
    if val == PLAYER_TILE_INDEX then
      local absAddr = off + 0x02000000
      -- Check if this looks like a sprite entry (inUse flag at +0x3E)
      local flags = WRAM:read16(base + 0x3E)
      local inUse = (flags & 0x01) ~= 0
      if inUse then
        local a2 = WRAM:read16(base + 0x04)
        local tileNum = a2 & 0x3FF
        console:log(string.format("  0x%08X: sheetTileStart=6, inUse=true, oam.tileNum=%d  (struct at 0x%08X)",
          absAddr, tileNum, base + 0x02000000))
        broadHits = broadHits + 1
      end
    end
  end
end

if broadHits == 0 then
  console:log("  No matching sheetTileStart=6 found at 0x44-stride.")
end

console:log("")

-- ===================================================================
-- STEP 6: Check IWRAM too (0x03000000 region)
-- ===================================================================

console:log("[Step 6] Scanning IWRAM for pointers to player VRAM tiles...")
console:log("")

local IWRAM = emu.memory.iwram
local iwramHits = 0

for tileIdx = 6, 13 do
  local targetAddr = OBJ_VRAM_BASE + tileIdx * 32

  for iwramOff = 0, 0x7FFC, 4 do
    local val = IWRAM:read32(iwramOff)
    if val == targetAddr then
      local absAddr = iwramOff + 0x03000000
      console:log(string.format("  0x%08X contains pointer 0x%08X (tile %d)",
        absAddr, targetAddr, tileIdx))
      iwramHits = iwramHits + 1
    end
  end
end

if iwramHits == 0 then
  console:log("  No pointers to player VRAM tiles in IWRAM.")
end

console:log("")

-- ===================================================================
-- STEP 7: Summary of all gSprites entries (quick overview)
-- Show tileNum and sheet for all active sprites to see the full picture
-- ===================================================================

console:log("[Step 7] All active gSprites - tileNum and sheetTileStart overview:")
console:log("")
console:log("  idx | tileNum | sheet | pal | shape/size | pos(x,y)      | x2/y2")
console:log("  ----|---------|-------|-----|------------|---------------|------")

for idx = 0, MAX_SPRITES - 1 do
  local off = GSPRITES_BASE + idx * SPRITE_SIZE
  if off + SPRITE_SIZE <= 0x40000 then
    local flagsWord = WRAM:read16(off + 0x3E)
    local inUse = (flagsWord & 0x01) ~= 0

    if inUse then
      local a0 = WRAM:read16(off)
      local a1 = WRAM:read16(off + 0x02)
      local a2 = WRAM:read16(off + 0x04)
      local tileNum = a2 & 0x3FF
      local palNum = (a2 >> 12) & 0xF
      local shape = (a0 >> 14) & 0x3
      local size = (a1 >> 14) & 0x3
      local hFlip = ((a1 >> 12) & 1) ~= 0
      local sheet = WRAM:read16(off + 0x40)

      local posX = WRAM:read16(off + 0x20)
      local posY = WRAM:read16(off + 0x22)
      if posX >= 0x8000 then posX = posX - 0x10000 end
      if posY >= 0x8000 then posY = posY - 0x10000 end

      local x2 = WRAM:read16(off + 0x24)
      local y2 = WRAM:read16(off + 0x26)
      if x2 >= 0x8000 then x2 = x2 - 0x10000 end
      if y2 >= 0x8000 then y2 = y2 - 0x10000 end

      local sizeNames = {
        [0] = {[0]="8x8",[1]="16x16",[2]="32x32",[3]="64x64"},
        [1] = {[0]="16x8",[1]="32x8",[2]="32x16",[3]="64x32"},
        [2] = {[0]="8x16",[1]="8x32",[2]="16x32",[3]="32x64"},
      }
      local sizeName = (sizeNames[shape] and sizeNames[shape][size]) or "?"

      local marker = ""
      if tileNum == 6 then marker = marker .. " <-- TILE=6" end
      if sheet == 6 then marker = marker .. " <-- SHEET=6" end
      if shape == 2 and size == 2 then marker = marker .. " [16x32]" end
      -- Screen center check (player is always ~120,80)
      if math.abs(posX - 120) <= 16 and math.abs(posY - 80) <= 16 then
        marker = marker .. " NEAR_CENTER"
      end

      console:log(string.format("  %3d | %7d | %5d | %3d | %d/%d %-5s | (%4d,%4d) | (%d,%d)%s",
        idx, tileNum, sheet, palNum, shape, size, sizeName,
        posX, posY, x2, y2, marker))
    end
  end
end

console:log("")

-- ===================================================================
-- STEP 8: Background monitor - track if tile data or references change
-- ===================================================================

console:log("[Step 8] Starting background monitor...")
console:log("  Tracking VRAM tile 6 content + gSprites references every 60 frames.")
console:log("  Walk around and turn to see what changes.")
console:log("")

local monitorFrame = 0
local prevTileHash = nil      -- hash of tile 6 content
local prevSpriteStates = {}   -- idx -> {tileNum, sheet, hFlip, posX, posY}
local changeLog = {}

-- Simple hash: sum of first 32 bytes of a tile
local function tileHash(tileIdx)
  local off = VRAM_OBJ_OFFSET + tileIdx * 32
  local sum = 0
  for i = 0, 31 do
    sum = sum + VRAM:read8(off + i)
  end
  return sum
end

-- Read current state of all active sprites
local function snapshotSprites()
  local snap = {}
  for idx = 0, MAX_SPRITES - 1 do
    local off = GSPRITES_BASE + idx * SPRITE_SIZE
    if off + SPRITE_SIZE <= 0x40000 then
      local flags = WRAM:read16(off + 0x3E)
      if (flags & 0x01) ~= 0 then
        local a1 = WRAM:read16(off + 0x02)
        local a2 = WRAM:read16(off + 0x04)
        snap[idx] = {
          tileNum = a2 & 0x3FF,
          palNum = (a2 >> 12) & 0xF,
          hFlip = ((a1 >> 12) & 1) ~= 0,
          posX = WRAM:read16(off + 0x20),
          posY = WRAM:read16(off + 0x22),
          sheet = WRAM:read16(off + 0x40),
        }
      end
    end
  end
  return snap
end

prevTileHash = tileHash(PLAYER_TILE_INDEX)
prevSpriteStates = snapshotSprites()

local function onFrame()
  monitorFrame = monitorFrame + 1
  if monitorFrame % 10 ~= 0 then return end  -- Check every 10 frames

  -- Check VRAM tile content change
  local curHash = tileHash(PLAYER_TILE_INDEX)
  if curHash ~= prevTileHash then
    console:log(string.format("  [frame %d] VRAM tile 6 content CHANGED (hash %d -> %d)",
      monitorFrame, prevTileHash, curHash))
    prevTileHash = curHash
  end

  -- Check sprite state changes (for sprites we care about)
  local curSprites = snapshotSprites()

  for idx, cur in pairs(curSprites) do
    local prev = prevSpriteStates[idx]
    if prev then
      local changes = {}
      if cur.tileNum ~= prev.tileNum then
        table.insert(changes, string.format("tileNum %d->%d", prev.tileNum, cur.tileNum))
      end
      if cur.hFlip ~= prev.hFlip then
        table.insert(changes, string.format("hFlip %s->%s", tostring(prev.hFlip), tostring(cur.hFlip)))
      end
      if cur.sheet ~= prev.sheet then
        table.insert(changes, string.format("sheet %d->%d", prev.sheet, cur.sheet))
      end
      -- Only report position changes for sprites near center (reduce noise)
      local px = cur.posX
      if px >= 0x8000 then px = px - 0x10000 end
      local py = cur.posY
      if py >= 0x8000 then py = py - 0x10000 end
      if math.abs(px - 120) <= 40 and math.abs(py - 80) <= 40 then
        local ppx = prev.posX
        if ppx >= 0x8000 then ppx = ppx - 0x10000 end
        local ppy = prev.posY
        if ppy >= 0x8000 then ppy = ppy - 0x10000 end
        if ppx ~= px or ppy ~= py then
          table.insert(changes, string.format("pos (%d,%d)->(%d,%d)", ppx, ppy, px, py))
        end
      end

      if #changes > 0 then
        console:log(string.format("  [frame %d] gSprites[%d]: %s",
          monitorFrame, idx, table.concat(changes, ", ")))
      end
    end
  end

  prevSpriteStates = curSprites

  -- Periodic summary every 5 seconds
  if monitorFrame % 300 == 0 then
    console:log(string.format("  [frame %d] Monitor alive. VRAM tile 6 hash=%d. Walk/turn to see changes.",
      monitorFrame, curHash))
  end
end

callbacks:add("frame", onFrame)
console:log("Background monitor active. Walk and turn your character!")
console:log("Changes will be logged in real-time.")
