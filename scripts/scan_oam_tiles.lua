--[[
  scan_oam_tiles.lua
  Scans hardware OAM to find which entry has tileNum pointing to the
  known player VRAM tiles (~tile 6 at 0x060100C0).

  Also dumps ALL visible OAM entries with their tile info and VRAM content
  fingerprints so we can cross-reference with the Tiles viewer.

  Runs a background monitor to track which OAM entry is the player
  by matching tileNum, regardless of OAM index shuffling.
]]

local OAM  = emu.memory.oam
local VRAM = emu.memory.vram
local PAL  = emu.memory.palette

local VRAM_OBJ_OFFSET = 0x10000  -- OBJ tiles start at 0x06010000

-- Size lookup
local SIZE_TABLE = {
  [0] = { [0] = {8,8},   [1] = {16,16}, [2] = {32,32}, [3] = {64,64} },
  [1] = { [0] = {16,8},  [1] = {32,8},  [2] = {32,16}, [3] = {64,32} },
  [2] = { [0] = {8,16},  [1] = {8,32},  [2] = {16,32}, [3] = {32,64} },
}

-- Read a VRAM tile's first 8 bytes as a fingerprint
local function tileFingerprintAt(tileNum)
  local off = VRAM_OBJ_OFFSET + tileNum * 32
  local b = {}
  for i = 0, 7 do
    b[i] = VRAM:read8(off + i)
  end
  return string.format("%02X%02X%02X%02X%02X%02X%02X%02X",
    b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7])
end

-- Read known player tile fingerprint (tile 6)
local playerTileFP = tileFingerprintAt(6)

console:log("=============================================")
console:log("  Hardware OAM Scanner")
console:log("=============================================")
console:log("")
console:log("Known player VRAM tile 6 fingerprint: " .. playerTileFP)
console:log("")

-- ===================================================================
-- SNAPSHOT: Dump ALL visible OAM entries
-- ===================================================================

console:log("All visible hardware OAM entries:")
console:log("")
console:log("  oam | xPos  | yPos | tileNum | pal | hFlip | shape/size | dim    | VRAM fingerprint   | match?")
console:log("  ----|-------|------|---------|-----|-------|------------|--------|--------------------|---------")

local screenCenterEntries = {}

for i = 0, 127 do
  local base = i * 8
  local a0 = OAM:read16(base)
  local a1 = OAM:read16(base + 2)
  local a2 = OAM:read16(base + 4)

  local affine = (a0 >> 8) & 0x3
  if affine ~= 2 then  -- not hidden
    local yPos = a0 & 0xFF
    local shape = (a0 >> 14) & 0x3
    local xPos = a1 & 0x1FF
    if xPos >= 256 then xPos = xPos - 512 end
    local hFlip = ((a1 >> 12) & 1) ~= 0
    local sizeCode = (a1 >> 14) & 0x3
    local tileNum = a2 & 0x3FF
    local palNum = (a2 >> 12) & 0xF

    -- Handle Y wrap
    local displayY = yPos
    if displayY > 160 then displayY = displayY - 256 end

    local dims = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]
    local w = dims and dims[1] or 0
    local h = dims and dims[2] or 0
    local dimStr = string.format("%dx%d", w, h)

    -- Get VRAM fingerprint for this sprite's base tile
    local fp = tileFingerprintAt(tileNum)

    -- Check if fingerprint matches player tile
    local matchStr = ""
    if fp == playerTileFP and playerTileFP ~= "0000000000000000" then
      matchStr = "MATCH!"
    end

    -- Check if near screen center
    local centerX = xPos + w / 2
    local centerY = displayY + h / 2
    local nearCenter = (math.abs(centerX - 120) <= 24 and math.abs(centerY - 80) <= 24)
    if nearCenter then
      matchStr = matchStr .. " CENTER"
      table.insert(screenCenterEntries, {
        idx = i, tileNum = tileNum, palNum = palNum,
        xPos = xPos, yPos = displayY, w = w, h = h,
        hFlip = hFlip, shape = shape, sizeCode = sizeCode
      })
    end

    -- Mark likely player entries
    local marker = ""
    if tileNum >= 4 and tileNum <= 15 then
      marker = " <-- low tile"
    end

    -- Show entry (filter: only show entries with non-zero tiles or near center)
    local isEmpty = (fp == "0000000000000000")
    if not isEmpty or nearCenter or tileNum <= 20 then
      console:log(string.format("  %3d | %5d | %4d | %7d | %3d | %-5s | %d/%d        | %-6s | %s | %s%s",
        i, xPos, displayY, tileNum, palNum, tostring(hFlip),
        shape, sizeCode, dimStr, fp, matchStr, marker))
    end
  end
end

console:log("")

-- ===================================================================
-- Analysis: entries near screen center (likely player)
-- ===================================================================

console:log("Entries near screen center (120,80):")
console:log("")

if #screenCenterEntries > 0 then
  for _, e in ipairs(screenCenterEntries) do
    console:log(string.format("  OAM[%d]: tile=%d pal=%d %dx%d pos=(%d,%d) hFlip=%s shape=%d size=%d",
      e.idx, e.tileNum, e.palNum, e.w, e.h, e.xPos, e.yPos,
      tostring(e.hFlip), e.shape, e.sizeCode))

    -- Show VRAM data for all tiles of this sprite
    local tilesW = e.w / 8
    local tilesH = e.h / 8
    local numTiles = tilesW * tilesH
    console:log(string.format("    Tiles %d-%d (%d tiles for %dx%d):",
      e.tileNum, e.tileNum + numTiles - 1, numTiles, e.w, e.h))

    for t = 0, numTiles - 1 do
      local tIdx = e.tileNum + t
      local fp = tileFingerprintAt(tIdx)
      local vramAddr = 0x06010000 + tIdx * 32
      local emptyStr = (fp == "0000000000000000") and " (EMPTY)" or ""
      console:log(string.format("      tile %3d (0x%08X): %s%s", tIdx, vramAddr, fp, emptyStr))
    end
  end
else
  console:log("  No OAM entries found near screen center!")
end

console:log("")

-- ===================================================================
-- Direct scan: which OAM entry has tileNum in range 4-7?
-- ===================================================================

console:log("OAM entries with tileNum in range 0-20 (low tiles, likely characters):")
console:log("")

for i = 0, 127 do
  local base = i * 8
  local a0 = OAM:read16(base)
  local a1 = OAM:read16(base + 2)
  local a2 = OAM:read16(base + 4)

  local affine = (a0 >> 8) & 0x3
  if affine ~= 2 then
    local tileNum = a2 & 0x3FF
    if tileNum <= 20 then
      local yPos = a0 & 0xFF
      local shape = (a0 >> 14) & 0x3
      local xPos = a1 & 0x1FF
      if xPos >= 256 then xPos = xPos - 512 end
      local hFlip = ((a1 >> 12) & 1) ~= 0
      local sizeCode = (a1 >> 14) & 0x3
      local palNum = (a2 >> 12) & 0xF
      if yPos > 160 then yPos = yPos - 256 end

      local dims = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]
      local w = dims and dims[1] or 0
      local h = dims and dims[2] or 0

      console:log(string.format("  OAM[%3d]: tile=%3d pal=%d %dx%d pos=(%d,%d) hFlip=%s",
        i, tileNum, palNum, w, h, xPos, yPos, tostring(hFlip)))
    end
  end
end

console:log("")

-- ===================================================================
-- BACKGROUND MONITOR: Track player by tileNum match
-- ===================================================================

console:log("Starting background monitor...")
console:log("Tracking OAM entries by tileNum + center proximity.")
console:log("Walk and turn to identify the player.")
console:log("")

local monFrame = 0
local prevPlayerTile = nil
local prevPlayerHFlip = nil
local prevPlayerOAMIdx = nil
local flipCount = 0
local totalSamples = 0

-- Track which tileNum values appear near center most often
local centerTileFreq = {}  -- tileNum -> count

local function findPlayerInOAM()
  -- Strategy: find the OAM entry near screen center with the lowest tileNum
  -- (player tiles are allocated first, so low tileNum = likely player)
  local best = nil
  local bestScore = 999999

  for i = 0, 127 do
    local base = i * 8
    local a0 = OAM:read16(base)
    local a1 = OAM:read16(base + 2)
    local a2 = OAM:read16(base + 4)

    local affine = (a0 >> 8) & 0x3
    if affine ~= 2 then
      local yPos = a0 & 0xFF
      local shape = (a0 >> 14) & 0x3
      local xPos = a1 & 0x1FF
      if xPos >= 256 then xPos = xPos - 512 end
      local sizeCode = (a1 >> 14) & 0x3
      local tileNum = a2 & 0x3FF
      local palNum = (a2 >> 12) & 0xF
      local hFlip = ((a1 >> 12) & 1) ~= 0
      if yPos > 160 then yPos = yPos - 256 end

      local dims = SIZE_TABLE[shape] and SIZE_TABLE[shape][sizeCode]
      local w = dims and dims[1] or 0
      local h = dims and dims[2] or 0

      local cx = xPos + w / 2
      local cy = yPos + h / 2
      local distToCenter = math.abs(cx - 120) + math.abs(cy - 80)

      -- Score: prioritize near-center + character-sized sprites
      -- Lower score = better match
      if distToCenter <= 40 and w >= 16 and h >= 16 then
        -- Bonus for 16x32 (typical character)
        local sizeBonus = 0
        if shape == 2 and sizeCode == 2 then sizeBonus = -100 end

        local score = distToCenter + sizeBonus

        if score < bestScore then
          bestScore = score
          best = {
            idx = i, tileNum = tileNum, palNum = palNum,
            xPos = xPos, yPos = yPos, w = w, h = h,
            hFlip = hFlip, shape = shape, sizeCode = sizeCode,
            distToCenter = distToCenter,
          }
        end
      end
    end
  end

  return best
end

local function onFrame()
  monFrame = monFrame + 1
  if monFrame % 5 ~= 0 then return end  -- Sample every 5 frames

  totalSamples = totalSamples + 1

  local player = findPlayerInOAM()
  if not player then return end

  -- Track tileNum frequency at center
  centerTileFreq[player.tileNum] = (centerTileFreq[player.tileNum] or 0) + 1

  -- Report changes
  local changes = {}

  if prevPlayerOAMIdx and prevPlayerOAMIdx ~= player.idx then
    table.insert(changes, string.format("oamIdx %d->%d", prevPlayerOAMIdx, player.idx))
  end

  if prevPlayerTile and prevPlayerTile ~= player.tileNum then
    table.insert(changes, string.format("tile %d->%d", prevPlayerTile, player.tileNum))
  end

  if prevPlayerHFlip ~= nil and prevPlayerHFlip ~= player.hFlip then
    flipCount = flipCount + 1
    table.insert(changes, string.format("hFlip %s->%s", tostring(prevPlayerHFlip), tostring(player.hFlip)))
  end

  if #changes > 0 then
    console:log(string.format("  [frame %d] Player OAM[%d]: %s (tile=%d %dx%d pos=(%d,%d))",
      monFrame, player.idx, table.concat(changes, ", "),
      player.tileNum, player.w, player.h, player.xPos, player.yPos))
  end

  prevPlayerOAMIdx = player.idx
  prevPlayerTile = player.tileNum
  prevPlayerHFlip = player.hFlip

  -- Periodic summary
  if monFrame % 300 == 0 then
    console:log(string.format("  [frame %d] Summary: %d samples, %d hFlip changes. OAM[%d] tile=%d %dx%d",
      monFrame, totalSamples, flipCount,
      player.idx, player.tileNum, player.w, player.h))

    -- Show top tileNums seen at center
    local sorted = {}
    for tn, count in pairs(centerTileFreq) do
      table.insert(sorted, { tileNum = tn, count = count })
    end
    table.sort(sorted, function(a, b) return a.count > b.count end)

    console:log("    Most frequent tileNums near center:")
    for rank, entry in ipairs(sorted) do
      if rank > 5 then break end
      local pct = entry.count / totalSamples * 100
      console:log(string.format("      tile %3d: %d times (%.0f%%)", entry.tileNum, entry.count, pct))
    end
  end
end

callbacks:add("frame", onFrame)
console:log("Monitor active. Walk and turn your character!")
