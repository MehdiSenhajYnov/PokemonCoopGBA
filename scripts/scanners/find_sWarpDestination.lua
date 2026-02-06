--[[
  find_sWarpDestination.lua — Find sWarpDestination address for Run & Bun

  PURPOSE:
  sWarpDestination is an EWRAM_DATA static struct WarpData in overworld.c.
  CB2_LoadMap reads from sWarpDestination (NOT SaveBlock1) to determine the
  destination map. Writing to SaveBlock1->location alone is insufficient for
  a proper warp — we must also write sWarpDestination.

  HOW IT WORKS:
  sWarpDestination mirrors SaveBlock1->location after every completed warp
  (ApplyCurrentWarp copies sWarpDestination -> SaveBlock1->location, and
  SetWarpDestination writes both). So after game boot or any door warp,
  sWarpDestination should contain identical bytes to SaveBlock1->location.

  The scanner reads the current SaveBlock1->location (8 bytes: mapGroup,
  mapNum, warpId, pad, x, y) and scans LOW EWRAM for exact 8-byte matches.
  It excludes SaveBlock1->location itself and any addresses in the party/PC
  storage region to avoid false positives.

  METHODS:
  1. IMMEDIATE SCAN — runs at script load. If the game has already booted
     and the player is on the overworld, sWarpDestination should already
     match. This finds it without any user action.
  2. POST-WARP SCAN — watches for CB2_LoadMap -> CB2_Overworld transitions
     (door warps). Rescans after each warp for confirmation.
  3. RELAXED SCAN — if exact 8-byte match fails, tries matching only
     mapGroup + mapNum + x + y (ignoring warpId and padding).

  HOW TO USE:
  1. Load this script in mGBA while in the overworld (game fully booted)
  2. Results appear immediately if a match is found
  3. For confirmation, walk through a door — the scanner re-checks after each warp
  4. Consistent address across multiple warps = high confidence

  KNOWN CONTEXT (Run & Bun):
    SaveBlock1 base     = 0x02024CBC (playerX = pos.x)
    SaveBlock1->location = 0x02024CC0 (mapGroup)
    Struct WarpData = 8 bytes: mapGroup(s8), mapNum(s8), warpId(s8), pad(1), x(s16), y(s16)
    sWarpDestination is EWRAM_DATA static, placed by linker in low EWRAM (BSS section)
    Expected range: 0x02000000 - 0x02010000 (well before SaveBlock1 at 0x02024CBC)
]]

-- ============================================================
-- CONFIG
-- ============================================================
-- Known Run & Bun addresses
local PLAYER_X_ADDR  = 0x02024CBC  -- SaveBlock1->pos.x (s16)
local PLAYER_Y_ADDR  = 0x02024CBE  -- SaveBlock1->pos.y (s16)
local MAP_GROUP_ADDR = 0x02024CC0  -- SaveBlock1->location.mapGroup (s8)
local MAP_ID_ADDR    = 0x02024CC1  -- SaveBlock1->location.mapNum (s8)

-- SaveBlock1->location starts at MAP_GROUP_ADDR and is 8 bytes
local SB1_LOCATION_OFF = MAP_GROUP_ADDR - 0x02000000  -- WRAM offset of SaveBlock1->location

-- gMain callback tracking
local GMAIN_BASE_WRAM = 0x02020648 - 0x02000000
local CALLBACK2_OFF   = 4
local CB2_LOAD_MAP    = 0x08007441
local CB2_OVERWORLD   = 0x080A89A5

-- Scan range: only low EWRAM (BSS static variables)
-- sWarpDestination is declared near other static vars in overworld.c
-- It should be well before SaveBlock1 (0x02024CBC)
local SCAN_START = 0x00000000
local SCAN_END   = 0x00024000  -- 144KB — safely below SaveBlock1

-- Regions to exclude from results (known data structures that might
-- accidentally match the 8-byte pattern)
local EXCLUDE_REGIONS = {
  { from = SB1_LOCATION_OFF - 4, to = SB1_LOCATION_OFF + 0x30 },  -- SaveBlock1->location + other warps
  { from = 0x00028000, to = 0x00040000 },  -- gPokemonStorage (PC boxes) and beyond
}

-- ============================================================
-- STATE
-- ============================================================
local prevCb2 = 0
local warpCount = 0
local allResults = {}  -- track addresses found across warps for consistency check

-- ============================================================
-- HELPERS
-- ============================================================
local function isExcluded(offset)
  for _, region in ipairs(EXCLUDE_REGIONS) do
    if offset >= region.from and offset < region.to then
      return true
    end
  end
  return false
end

-- Read the 8-byte WarpData pattern from SaveBlock1->location
local function readSB1Location()
  local ok1, w1 = pcall(emu.memory.wram.read32, emu.memory.wram, SB1_LOCATION_OFF)
  local ok2, w2 = pcall(emu.memory.wram.read32, emu.memory.wram, SB1_LOCATION_OFF + 4)
  if not ok1 or not ok2 then return nil, nil end
  return w1, w2
end

-- Extract individual fields from the first 32-bit word
local function parseWarpWord1(w1)
  local mapGroup = w1 & 0xFF
  local mapNum   = (w1 >> 8) & 0xFF
  local warpId   = (w1 >> 16) & 0xFF
  local pad      = (w1 >> 24) & 0xFF
  return mapGroup, mapNum, warpId, pad
end

-- Extract x,y from the second 32-bit word
local function parseWarpWord2(w2)
  local x = w2 & 0xFFFF
  local y = (w2 >> 16) & 0xFFFF
  return x, y
end

-- ============================================================
-- EXACT 8-BYTE SCAN
-- ============================================================
-- Scans EWRAM for an exact match of the 8-byte WarpData pattern.
-- Reads in 4-byte chunks for speed.
local function scanExact(ref32a, ref32b, label)
  local mapGroup, mapNum, warpId, pad = parseWarpWord1(ref32a)
  local x, y = parseWarpWord2(ref32b)

  console:log(string.format("[%s] Pattern: mapGroup=%d mapNum=%d warpId=%d pad=%d x=%d y=%d",
    label, mapGroup, mapNum, warpId, pad, x, y))
  console:log(string.format("[%s] Raw: word1=0x%08X word2=0x%08X", label, ref32a, ref32b))
  console:log(string.format("[%s] Scan range: 0x%05X - 0x%05X", label, SCAN_START, SCAN_END))

  -- Skip if pattern is all zeros (game not initialized)
  if ref32a == 0 and ref32b == 0 then
    console:log(string.format("[%s] Pattern is all zeros — game not initialized yet", label))
    return {}
  end

  local matches = {}

  -- Scan every 4 bytes (WarpData is 8-byte aligned due to s16 members)
  -- But also try 2-byte alignment in case linker placed it at odd offset
  for offset = SCAN_START, SCAN_END - 8, 2 do
    if not isExcluded(offset) then
      local ok1, val1 = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
      if ok1 and val1 == ref32a then
        local ok2, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
        if ok2 and val2 == ref32b then
          local absAddr = 0x02000000 + offset
          matches[#matches + 1] = {
            offset = offset,
            addr = absAddr,
            method = "exact_8byte",
          }
          console:log(string.format("[%s] EXACT MATCH at 0x%08X", label, absAddr))
        end
      end
    end
  end

  return matches
end

-- ============================================================
-- RELAXED SCAN (mapGroup + mapNum + x + y, ignore warpId/pad)
-- ============================================================
local function scanRelaxed(ref32a, ref32b, label)
  local mapGroup = ref32a & 0xFF
  local mapNum = (ref32a >> 8) & 0xFF
  local x = ref32b & 0xFFFF
  local y = (ref32b >> 16) & 0xFFFF

  console:log(string.format("[%s] Relaxed: mapGroup=%d mapNum=%d x=%d y=%d (ignoring warpId/pad)",
    label, mapGroup, mapNum, x, y))

  local matches = {}

  for offset = SCAN_START, SCAN_END - 8, 2 do
    if not isExcluded(offset) then
      local ok1, b0 = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
      if ok1 and b0 == mapGroup then
        local ok2, b1 = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 1)
        if ok2 and b1 == mapNum then
          -- Check x at +4 and y at +6
          local ok3, vx = pcall(emu.memory.wram.read16, emu.memory.wram, offset + 4)
          local ok4, vy = pcall(emu.memory.wram.read16, emu.memory.wram, offset + 6)
          if ok3 and ok4 and vx == x and vy == y then
            -- Read warpId and pad for info
            local _, wid = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 2)
            local _, pd  = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 3)
            local absAddr = 0x02000000 + offset

            -- Check if this was already found by exact scan
            local alreadyExact = false
            -- (caller will deduplicate)

            matches[#matches + 1] = {
              offset = offset,
              addr = absAddr,
              method = "relaxed",
              warpId = wid or 0,
              pad = pd or 0,
            }
            console:log(string.format("[%s] RELAXED MATCH at 0x%08X (warpId=%d pad=%d)",
              label, absAddr, wid or 0, pd or 0))
          end
        end
      end
    end
  end

  return matches
end

-- ============================================================
-- CONTEXT SCAN: check nearby EWRAM_DATA variables
-- ============================================================
-- In overworld.c, sWarpDestination is declared between:
--   sObjectEventLoadFlag (u8)
--   gLastUsedWarp (struct WarpData, 8 bytes)
--   sWarpDestination (struct WarpData, 8 bytes) <-- TARGET
--   sFixedDiveWarp (struct WarpData, 8 bytes)
--   sFixedHoleWarp (struct WarpData, 8 bytes)
--   sLastMapSectionId (u16)
-- If we find sWarpDestination, verify neighbors look like WarpData structs
local function checkNeighborContext(offset)
  local info = {}

  -- Check gLastUsedWarp at offset - 8 (should be a valid WarpData)
  local ok1, prevMG = pcall(emu.memory.wram.read8, emu.memory.wram, offset - 8)
  local ok2, prevMN = pcall(emu.memory.wram.read8, emu.memory.wram, offset - 8 + 1)
  if ok1 and ok2 then
    info.prevWarp = string.format("gLastUsedWarp? mapGroup=%d mapNum=%d", prevMG, prevMN)
  end

  -- Check sFixedDiveWarp at offset + 8 (should be WarpData, often zeroed or -1/-1)
  local ok3, nextMG = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 8)
  local ok4, nextMN = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 8 + 1)
  local ok5, nextWI = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 8 + 2)
  if ok3 and ok4 and ok5 then
    info.nextWarp = string.format("sFixedDiveWarp? mapGroup=%d mapNum=%d warpId=%d", nextMG, nextMN, nextWI)
    -- sDummyWarpData = {-1, -1, -1, 0, 0, 0} = {0xFF, 0xFF, 0xFF, 0, 0x0000, 0x0000}
    if nextMG == 0xFF and nextMN == 0xFF and nextWI == 0xFF then
      info.diveIsDummy = true
    end
  end

  -- Check sFixedHoleWarp at offset + 16
  local ok6, holeG = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 16)
  local ok7, holeN = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 16 + 1)
  local ok8, holeW = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 16 + 2)
  if ok6 and ok7 and ok8 then
    info.holeWarp = string.format("sFixedHoleWarp? mapGroup=%d mapNum=%d warpId=%d", holeG, holeN, holeW)
    if holeG == 0xFF and holeN == 0xFF and holeW == 0xFF then
      info.holeIsDummy = true
    end
  end

  -- Check sObjectEventLoadFlag at offset - 12 (u8, before gLastUsedWarp)
  -- gLastUsedWarp is 8 bytes, sObjectEventLoadFlag is u8 + alignment padding
  -- With struct packing: flag(1 byte) + pad(3 bytes) + gLastUsedWarp(8 bytes) = 12 bytes before target
  -- OR: flag(1 byte) + pad(1 byte) + gLastUsedWarp(8 bytes) = 10 bytes before target
  -- Let's check a few possibilities
  local ok9, flagVal = pcall(emu.memory.wram.read8, emu.memory.wram, offset - 12)
  if ok9 then
    info.flagBefore12 = string.format("offset-12: %d (sObjectEventLoadFlag?)", flagVal)
  end

  return info
end

-- ============================================================
-- FULL SCAN ROUTINE
-- ============================================================
local function runFullScan(label)
  console:log("")
  console:log("============================================")
  console:log(string.format("=== sWarpDestination Scan (%s) ===", label))
  console:log("============================================")

  local ref32a, ref32b = readSB1Location()
  if not ref32a then
    console:log("ERROR: Cannot read SaveBlock1->location")
    return
  end

  -- Method 1: Exact 8-byte match
  local exactMatches = scanExact(ref32a, ref32b, label)

  -- Method 2: Relaxed match (if no exact matches, or for additional candidates)
  local relaxedMatches = {}
  if #exactMatches == 0 then
    console:log("")
    console:log("No exact matches — trying relaxed scan...")
    relaxedMatches = scanRelaxed(ref32a, ref32b, label)
  end

  -- Combine results (deduplicate by address)
  local allMatches = {}
  local seen = {}
  for _, m in ipairs(exactMatches) do
    if not seen[m.offset] then
      allMatches[#allMatches + 1] = m
      seen[m.offset] = true
    end
  end
  for _, m in ipairs(relaxedMatches) do
    if not seen[m.offset] then
      allMatches[#allMatches + 1] = m
      seen[m.offset] = true
    end
  end

  -- Report results
  console:log("")
  if #allMatches == 0 then
    console:log("NO CANDIDATES FOUND")
    console:log("Possible reasons:")
    console:log("  - Game not fully initialized (try after loading a save)")
    console:log("  - sWarpDestination cleared between warps (walk through a door first)")
    console:log("  - Address is outside scan range (unlikely for EWRAM_DATA static)")
    return
  end

  console:log(string.format("FOUND %d CANDIDATE(S):", #allMatches))
  console:log("")

  for i, m in ipairs(allMatches) do
    console:log(string.format("  #%d: 0x%08X [%s]", i, m.addr, m.method))

    -- Contextual neighbor check
    local ctx = checkNeighborContext(m.offset)
    if ctx.prevWarp then
      console:log(string.format("       -8 bytes: %s", ctx.prevWarp))
    end
    if ctx.nextWarp then
      console:log(string.format("       +8 bytes: %s", ctx.nextWarp))
      if ctx.diveIsDummy then
        console:log("       +8 bytes: ^^ MATCHES sDummyWarpData (-1,-1,-1) — STRONG CONFIRMATION")
      end
    end
    if ctx.holeWarp then
      console:log(string.format("       +16 bytes: %s", ctx.holeWarp))
      if ctx.holeIsDummy then
        console:log("       +16 bytes: ^^ MATCHES sDummyWarpData (-1,-1,-1) — STRONG CONFIRMATION")
      end
    end
    console:log("")

    -- Track across warps for consistency
    if not allResults[m.addr] then
      allResults[m.addr] = 0
    end
    allResults[m.addr] = allResults[m.addr] + 1
  end

  -- If we have multiple warps worth of data, show consistency
  if warpCount > 0 then
    console:log("--- Consistency across warps ---")
    for addr, count in pairs(allResults) do
      console:log(string.format("  0x%08X: found in %d/%d scans %s",
        addr, count, warpCount + 1,
        count == warpCount + 1 and "CONSISTENT" or ""))
    end
    console:log("")
  end

  -- Recommendation
  local best = allMatches[1]
  console:log("========================================")
  console:log("RECOMMENDED sWarpDestination address:")
  console:log(string.format("  sWarpDataAddr = 0x%08X,", best.addr))
  console:log("========================================")
  console:log("")
  console:log("To use: update config/run_and_bun.lua warp section:")
  console:log("  warp = {")
  console:log("    ...,")
  console:log(string.format("    sWarpDataAddr = 0x%08X,", best.addr))
  console:log("  },")
end

-- ============================================================
-- IMMEDIATE SCAN (on script load)
-- ============================================================
console:log("")
console:log("================================================")
console:log("  sWarpDestination Scanner for Run & Bun")
console:log("================================================")
console:log("")
console:log("Struct WarpData layout (8 bytes):")
console:log("  +0: mapGroup (s8)")
console:log("  +1: mapNum   (s8)")
console:log("  +2: warpId   (s8)")
console:log("  +3: padding  (u8)")
console:log("  +4: x        (s16)")
console:log("  +6: y        (s16)")
console:log("")
console:log("SaveBlock1->location at WRAM offset 0x" .. string.format("%05X", SB1_LOCATION_OFF))
console:log("")

-- Try immediate scan (works if game is already booted)
runFullScan("immediate")

-- ============================================================
-- POST-WARP FRAME CALLBACK
-- ============================================================
callbacks:add("frame", function()
  -- Read callback2
  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, GMAIN_BASE_WRAM + CALLBACK2_OFF)
  if not ok then return end

  -- Detect CB2_LoadMap -> CB2_Overworld (warp just completed)
  if prevCb2 == CB2_LOAD_MAP and cb2 == CB2_OVERWORLD then
    warpCount = warpCount + 1
    console:log("")
    console:log(string.format(">>> WARP #%d COMPLETED — rescanning <<<", warpCount))
    runFullScan("post-warp #" .. warpCount)
  end

  prevCb2 = cb2
end)

console:log("")
console:log("Frame callback active — walk through doors for re-scan confirmation.")
console:log("Consistent results across warps = high confidence.")
