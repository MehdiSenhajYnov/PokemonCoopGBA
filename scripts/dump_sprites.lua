--[[
  dump_sprites.lua
  Dumps all active sprites from gSprites array at 0x020212F0
  Run TWICE: once standing still, once after moving/turning.
  The entry whose tileNum changed is the player.

  Also dumps hardware OAM entries for cross-reference.
]]

local WRAM = emu.memory.wram
local OAM = emu.memory.oam

local GSPRITES_BASE = 0x020212F0 - 0x02000000  -- WRAM offset
local SPRITE_SIZE = 0x44
local MAX_SPRITES = 64

console:log("=============================================")
console:log("  gSprites Dump (base=0x020212F0)")
console:log("=============================================")
console:log("")

-- Dump ALL 64 sprite entries
local activeCount = 0
console:log("  idx | inUse | shape size | tileNum | pal | hFlip | sheet  | pos(x,y)     | ROM ptrs")
console:log("  ----|-------|------------|---------|-----|-------|--------|--------------|----------")

for idx = 0, MAX_SPRITES - 1 do
  local off = GSPRITES_BASE + idx * SPRITE_SIZE

  if off + SPRITE_SIZE <= 0x40000 then
    local flagsWord = WRAM:read16(off + 0x3E)
    local inUse = (flagsWord & 0x01) ~= 0

    if inUse then
      activeCount = activeCount + 1

      local a0 = WRAM:read16(off)
      local a1 = WRAM:read16(off + 0x02)
      local a2 = WRAM:read16(off + 0x04)

      local shape = (a0 >> 14) & 0x3
      local size = (a1 >> 14) & 0x3
      local tileNum = a2 & 0x3FF
      local palNum = (a2 >> 12) & 0xF
      local hFlip = ((a1 >> 12) & 1) ~= 0
      local sheet = WRAM:read16(off + 0x40)

      -- Screen position from Sprite struct
      local posX = WRAM:read16(off + 0x20)
      local posY = WRAM:read16(off + 0x22)
      -- sign-extend
      if posX >= 0x8000 then posX = posX - 0x10000 end
      if posY >= 0x8000 then posY = posY - 0x10000 end

      -- ROM pointer check (anims at +0x08, template at +0x14)
      local ptrAnims = WRAM:read32(off + 0x08)
      local ptrTemplate = WRAM:read32(off + 0x14)
      local hasRomPtrs = (ptrAnims >= 0x08000000 and ptrAnims < 0x0A000000)
                     and (ptrTemplate >= 0x08000000 and ptrTemplate < 0x0A000000)

      -- Size names
      local sizeNames = {
        [0] = {[0]="8x8",[1]="16x16",[2]="32x32",[3]="64x64"},
        [1] = {[0]="16x8",[1]="32x8",[2]="32x16",[3]="64x32"},
        [2] = {[0]="8x16",[1]="8x32",[2]="16x32",[3]="32x64"},
      }
      local sizeName = (sizeNames[shape] and sizeNames[shape][size]) or "?"

      local marker = ""
      if shape == 2 and size == 2 then marker = " <-- 16x32" end

      console:log(string.format(
        "  %3d | true  | %d    %d %-5s | %7d | %3d | %-5s | %6d | (%4d,%4d) | %s%s",
        idx, shape, size, sizeName, tileNum, palNum,
        tostring(hFlip), sheet, posX, posY,
        hasRomPtrs and "ROM" or "---", marker))
    end
  end
end

console:log("")
console:log(string.format("  Total active sprites: %d / %d", activeCount, MAX_SPRITES))

-- ===================================================================
-- Also dump hardware OAM for cross-reference
-- ===================================================================
console:log("")
console:log("=============================================")
console:log("  Hardware OAM (active 16x32 sprites)")
console:log("=============================================")
console:log("")
console:log("  oam | screenX | screenY | tileNum | pal | hFlip | shape size")
console:log("  ----|---------|---------|---------|-----|-------|----------")

for i = 0, 127 do
  local base = i * 8
  local oa0 = OAM:read16(base)
  local oa1 = OAM:read16(base + 2)
  local oa2 = OAM:read16(base + 4)

  local affine = (oa0 >> 8) & 0x3
  if affine ~= 2 then  -- not hidden
    local shape = (oa0 >> 14) & 0x3
    local size = (oa1 >> 14) & 0x3

    -- Only show 16x32 tall sprites (likely characters)
    if shape == 2 and size == 2 then
      local yPos = oa0 & 0xFF
      local xPos = oa1 & 0x1FF
      if xPos >= 256 then xPos = xPos - 512 end
      if yPos > 160 then yPos = yPos - 256 end

      local tileNum = oa2 & 0x3FF
      local palNum = (oa2 >> 12) & 0xF
      local hFlip = ((oa1 >> 12) & 1) ~= 0

      local marker = ""
      if xPos >= 100 and xPos <= 140 and yPos >= 40 and yPos <= 90 then
        marker = " <-- NEAR CENTER"
      end

      console:log(string.format("  %3d | %7d | %7d | %7d | %3d | %-5s | %d    %d%s",
        i, xPos, yPos, tileNum, palNum, tostring(hFlip), shape, size, marker))
    end
  end
end

console:log("")
console:log("Done. Move/turn your character and run this script again.")
console:log("The gSprites entry whose tileNum changed = player sprite.")
