--[[
  find_sprite_structs.lua v2
  Scan EWRAM to locate gSprites and gPlayerAvatar for Run & Bun.

  Run in mGBA scripting console while in overworld (player visible).

  Uses three independent strategies and cross-validates:
  1. Find gSprites via ROM pointer pattern (0x08xxxxxx at specific offsets)
  2. Find gObjectEvents via known player X/Y coordinates
  3. Cross-validate with user's tile observation (~tile 6 in OBJ VRAM)
]]

local WRAM = emu.memory.wram

-- Known Run & Bun addresses
local PLAYER_X_ADDR = 0x02024CBC
local PLAYER_Y_ADDR = 0x02024CBE

console:log("=============================================")
console:log("  Sprite Structure Scanner v2 - Run & Bun")
console:log("=============================================")
console:log("")

-- Read current player position for cross-validation
local playerX = WRAM:read16(PLAYER_X_ADDR - 0x02000000)
local playerY = WRAM:read16(PLAYER_Y_ADDR - 0x02000000)
console:log(string.format("Current player position: X=%d, Y=%d", playerX, playerY))
console:log("")

-- Helper: check if value looks like a ROM pointer
local function isRomPointer(val)
  return val >= 0x08000000 and val < 0x0A000000
end

-- ===================================================================
-- STRATEGY 1: Find gSprites via ROM pointer signature
-- Each struct Sprite (0x44 bytes) has ROM pointers at offsets:
--   +0x08 = anims (ptr to ROM)
--   +0x0C = images (ptr to ROM or NULL)
--   +0x14 = template (ptr to ROM)
-- We look for 4-byte-aligned arrays with 0x44 stride where
-- multiple consecutive entries have ROM pointers at these offsets.
-- ===================================================================

console:log("[Strategy 1] Scanning for gSprites via ROM pointer pattern...")

local spriteCandidates = {}

-- Scan only 4-byte-aligned addresses
for base = 0x00000, 0x3A000, 4 do
  -- Check entry 0 at this base
  local ptr08_0 = WRAM:read32(base + 0x08)
  local ptr14_0 = WRAM:read32(base + 0x14)

  if isRomPointer(ptr08_0) and isRomPointer(ptr14_0) then
    -- Entry 0 has ROM pointers. Check entry 1 (at base + 0x44)
    local entry1 = base + 0x44
    if entry1 + 0x44 <= 0x40000 then
      local ptr08_1 = WRAM:read32(entry1 + 0x08)
      local ptr14_1 = WRAM:read32(entry1 + 0x14)

      if isRomPointer(ptr08_1) and isRomPointer(ptr14_1) then
        -- Two consecutive entries match. Check more entries.
        local matchCount = 2
        local inUseCount = 0

        for idx = 2, 15 do
          local entryOff = base + idx * 0x44
          if entryOff + 0x44 <= 0x40000 then
            local p08 = WRAM:read32(entryOff + 0x08)
            local p14 = WRAM:read32(entryOff + 0x14)
            if isRomPointer(p08) and isRomPointer(p14) then
              matchCount = matchCount + 1
            end
            -- Check inUse flag
            local flags = WRAM:read16(entryOff + 0x3E)
            if (flags & 0x01) ~= 0 then
              inUseCount = inUseCount + 1
            end
          end
        end

        -- Also count entry 0 and 1 inUse
        local f0 = WRAM:read16(base + 0x3E)
        local f1 = WRAM:read16(entry1 + 0x3E)
        if (f0 & 0x01) ~= 0 then inUseCount = inUseCount + 1 end
        if (f1 & 0x01) ~= 0 then inUseCount = inUseCount + 1 end

        -- Need at least 5 entries with ROM pointers and some in use
        if matchCount >= 5 and inUseCount >= 3 then
          table.insert(spriteCandidates, {
            base = base,
            matchCount = matchCount,
            inUseCount = inUseCount,
          })
        end
      end
    end
  end
end

console:log(string.format("  Found %d candidate(s) for gSprites array", #spriteCandidates))

for ci, c in ipairs(spriteCandidates) do
  local absBase = c.base + 0x02000000
  console:log(string.format("  Candidate #%d: 0x%08X (ROM-ptr entries=%d, inUse=%d)",
    ci, absBase, c.matchCount, c.inUseCount))

  -- Dump first few entries' OAM data
  for idx = 0, math.min(7, 63) do
    local off = c.base + idx * 0x44
    if off + 0x44 <= 0x40000 then
      local flags = WRAM:read16(off + 0x3E)
      local inUse = (flags & 0x01) ~= 0
      if inUse then
        local a0 = WRAM:read16(off)
        local a1 = WRAM:read16(off + 0x02)
        local a2 = WRAM:read16(off + 0x04)
        local shape = (a0 >> 14) & 0x3
        local size = (a1 >> 14) & 0x3
        local tileNum = a2 & 0x3FF
        local palNum = (a2 >> 12) & 0xF
        local hFlip = ((a1 >> 12) & 1) ~= 0
        local sheet = WRAM:read16(off + 0x40)
        console:log(string.format(
          "    [%d] tileNum=%d pal=%d shape=%d size=%d hFlip=%s sheet=%d",
          idx, tileNum, palNum, shape, size, tostring(hFlip), sheet))
      end
    end
  end
end

console:log("")

-- ===================================================================
-- STRATEGY 2: Find gObjectEvents via known player X/Y
-- ObjectEvent.currentCoords is at offset 0x10 (x, s16) and 0x12 (y, s16)
-- The player entry has localId = 0xFF at offset 0x08
-- Scan 4-byte-aligned addresses only
-- ===================================================================

console:log("[Strategy 2] Scanning for gObjectEvents via player X/Y coords...")

local objEventCandidates = {}

for base = 0x20000, 0x3F000, 4 do
  local cx = WRAM:read16(base + 0x10)
  local cy = WRAM:read16(base + 0x12)

  if cx == playerX and cy == playerY then
    local localId = WRAM:read8(base + 0x08)
    local flagsByte2 = WRAM:read8(base + 0x02)
    local isPlayer = (flagsByte2 & 0x01) ~= 0
    local activeByte = WRAM:read8(base)
    local active = (activeByte & 0x01) ~= 0
    local spriteId = WRAM:read8(base + 0x04)

    if active and localId == 0xFF and spriteId < 64 then
      local absAddr = base + 0x02000000
      table.insert(objEventCandidates, {
        base = base,
        absAddr = absAddr,
        spriteId = spriteId,
        graphicsId = WRAM:read8(base + 0x05),
        isPlayer = isPlayer,
      })
      console:log(string.format(
        "  MATCH at 0x%08X: spriteId=%d, graphicsId=%d, isPlayer=%s, localId=0xFF, coords=(%d,%d)",
        absAddr, spriteId, WRAM:read8(base + 0x05), tostring(isPlayer), cx, cy))
    end
  end
end

if #objEventCandidates == 0 then
  console:log("  No matches found with strict criteria. Relaxing localId check...")

  for base = 0x20000, 0x3F000, 4 do
    local cx = WRAM:read16(base + 0x10)
    local cy = WRAM:read16(base + 0x12)

    if cx == playerX and cy == playerY then
      local spriteId = WRAM:read8(base + 0x04)
      if spriteId < 64 then
        local absAddr = base + 0x02000000
        console:log(string.format(
          "  Relaxed match at 0x%08X: spriteId=%d, localId=0x%02X, bytes: %02X %02X %02X %02X %02X %02X %02X %02X",
          absAddr, spriteId, WRAM:read8(base + 0x08),
          WRAM:read8(base), WRAM:read8(base+1), WRAM:read8(base+2), WRAM:read8(base+3),
          WRAM:read8(base+4), WRAM:read8(base+5), WRAM:read8(base+6), WRAM:read8(base+7)))
      end
    end
  end
end

console:log("")

-- ===================================================================
-- STRATEGY 3: Cross-validate gSprites with gObjectEvents
-- If we found both, check if gSprites[spriteId] from ObjectEvent
-- has reasonable player sprite data
-- ===================================================================

console:log("[Strategy 3] Cross-validation...")

if #spriteCandidates > 0 and #objEventCandidates > 0 then
  local bestSprites = spriteCandidates[1]
  local bestObjEvent = objEventCandidates[1]
  local spriteId = bestObjEvent.spriteId

  -- Read sprite data from gSprites[spriteId]
  local spriteOff = bestSprites.base + spriteId * 0x44
  if spriteOff + 0x44 <= 0x40000 then
    local a0 = WRAM:read16(spriteOff)
    local a1 = WRAM:read16(spriteOff + 0x02)
    local a2 = WRAM:read16(spriteOff + 0x04)
    local flags = WRAM:read16(spriteOff + 0x3E)
    local sheet = WRAM:read16(spriteOff + 0x40)
    local inUse = (flags & 0x01) ~= 0

    local shape = (a0 >> 14) & 0x3
    local size = (a1 >> 14) & 0x3
    local tileNum = a2 & 0x3FF
    local palNum = (a2 >> 12) & 0xF
    local hFlip = ((a1 >> 12) & 1) ~= 0

    console:log(string.format("  gSprites[%d] -> inUse=%s, shape=%d, size=%d, tileNum=%d, pal=%d, hFlip=%s, sheet=%d",
      spriteId, tostring(inUse), shape, size, tileNum, palNum, tostring(hFlip), sheet))

    if inUse and shape == 2 and size == 2 then
      console:log("  VALIDATED: 16x32 tall sprite, in use")
    elseif inUse then
      console:log(string.format("  WARNING: sprite is in use but unexpected shape/size (%d/%d)", shape, size))
    else
      console:log("  WARNING: sprite not in use! SpriteId may be wrong.")
    end
  end

  -- Try to derive gPlayerAvatar from gObjectEvents
  -- gPlayerAvatar is at gObjectEvents_base + 16 * 0x24 (= +0x240)
  -- First, figure out which index in gObjectEvents this entry is
  -- Try index 0 first (most common for player)
  for idx = 0, 15 do
    local arrayBase = bestObjEvent.base - idx * 0x24
    if arrayBase >= 0x20000 then
      local avatarOffset = arrayBase + 0x240
      if avatarOffset + 0x24 <= 0x40000 then
        local avatarSpriteId = WRAM:read8(avatarOffset + 0x04)
        local avatarObjEventId = WRAM:read8(avatarOffset + 0x05)

        if avatarSpriteId == bestObjEvent.spriteId and avatarObjEventId == idx then
          local gObjEventsAddr = arrayBase + 0x02000000
          local gPlayerAvatarAddr = avatarOffset + 0x02000000

          console:log("")
          console:log("=============================================")
          console:log("  VALIDATED RESULTS")
          console:log("=============================================")
          console:log(string.format("  gObjectEvents:          0x%08X", gObjEventsAddr))
          console:log(string.format("  Player at index:        %d", idx))
          console:log(string.format("  gPlayerAvatar:          0x%08X", gPlayerAvatarAddr))
          console:log(string.format("  gPlayerAvatar.spriteId: 0x%08X (value=%d)",
            gPlayerAvatarAddr + 0x04, avatarSpriteId))
          console:log(string.format("  gSprites:               0x%08X", bestSprites.base + 0x02000000))
          console:log("")

          -- Final player sprite readout
          local sOff = bestSprites.base + avatarSpriteId * 0x44
          local fa2 = WRAM:read16(sOff + 0x04)
          local fTile = fa2 & 0x3FF
          local fPal = (fa2 >> 12) & 0xF
          local fa1 = WRAM:read16(sOff + 0x02)
          local fHFlip = ((fa1 >> 12) & 1) ~= 0
          local fSheet = WRAM:read16(sOff + 0x40)

          console:log(string.format("  Current player OAM: tileNum=%d, palette=%d, hFlip=%s", fTile, fPal, tostring(fHFlip)))
          console:log(string.format("  sheetTileStart:     %d", fSheet))
          console:log(string.format("  VRAM tile offset:   0x%05X (= 0x0601%04X)", fTile * 32, fTile * 32))
          console:log("")
          console:log("  Copy these for hal.lua config:")
          console:log(string.format("    gPlayerAvatarSpriteId = 0x%08X", gPlayerAvatarAddr + 0x04))
          console:log(string.format("    gSpritesBase           = 0x%08X", bestSprites.base + 0x02000000))
          console:log(string.format("    spriteStructSize       = 0x44"))
          console:log("=============================================")
          return
        end
      end
    end
  end

  console:log("  Could not validate gPlayerAvatar via gObjectEvents cross-check.")
  console:log("  Dumping gPlayerAvatar candidate region:")
  local arrayBase = bestObjEvent.base -- assuming player is index 0
  local avatarOffset = arrayBase + 0x240
  if avatarOffset + 0x24 <= 0x40000 then
    for i = 0, 0x24 - 1, 4 do
      console:log(string.format("    0x%08X (+0x%02X): %02X %02X %02X %02X",
        avatarOffset + i + 0x02000000, i,
        WRAM:read8(avatarOffset+i), WRAM:read8(avatarOffset+i+1),
        WRAM:read8(avatarOffset+i+2), WRAM:read8(avatarOffset+i+3)))
    end
  end

elseif #spriteCandidates > 0 then
  console:log("  Have gSprites but no gObjectEvents. Scanning gSprites for 16x32 sprites...")
  local best = spriteCandidates[1]
  for idx = 0, 63 do
    local off = best.base + idx * 0x44
    if off + 0x44 <= 0x40000 then
      local flags = WRAM:read16(off + 0x3E)
      if (flags & 0x01) ~= 0 then
        local a0 = WRAM:read16(off)
        local a1 = WRAM:read16(off + 0x02)
        local a2 = WRAM:read16(off + 0x04)
        local shape = (a0 >> 14) & 0x3
        local size = (a1 >> 14) & 0x3
        if shape == 2 and size == 2 then
          local tileNum = a2 & 0x3FF
          local palNum = (a2 >> 12) & 0xF
          console:log(string.format("  [%d] 16x32 sprite: tileNum=%d, pal=%d (VRAM 0x0601%04X)",
            idx, tileNum, palNum, tileNum * 32))
        end
      end
    end
  end

else
  console:log("  Neither gSprites nor gObjectEvents found reliably.")
  console:log("  Make sure you're in overworld with the player visible.")
end

console:log("")
console:log("Scan complete. Move your character and run again for comparison.")
