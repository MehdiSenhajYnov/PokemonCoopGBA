--[[
  EWRAM Battle Variable Discovery — Runtime Diff Polling

  Discovers EWRAM battle variables by monitoring memory changes during a
  trainer battle. Automatically detects battle entry/exit via gMainInBattle
  and categorizes changed bytes by their behavior patterns.

  TARGET VARIABLES:
  1. gBattleCommunication  — u8[8], increments during battle init (stages 0→12+)
  2. gBattleControllerExecFlags — u32, bits 0-3 toggle during command processing
  3. gActiveBattler         — u8, cycles 0-3 as engine iterates battlers
  4. gLinkPlayers           — 5 × 28-byte structs (names, trainer IDs)

  KNOWN R&B ANCHORS (used to focus scan regions):
  - gBattleTypeFlags     = 0x020090E8 (battle BSS area)
  - gBattleResources     = 0x02023A18 (battle heap pointer)
  - gPlayerParty         = 0x02023A98
  - gEnemyParty          = 0x02023CF0
  - gMainInBattle        = 0x020206AE

  VANILLA EMERALD REFERENCE (NOT valid in R&B, for comparison only):
  - gBattleCommunication         = 0x02024332
  - gBattleControllerExecFlags   = 0x02024068
  - gActiveBattler               = 0x02024064
  - gLinkPlayers                 = 0x020229E8

  USAGE:
  1. Load this script in mGBA (Tools > Scripting > Load Script)
  2. Walk around in the overworld (script waits for battle)
  3. Enter a trainer battle — script auto-detects battle start
  4. Fight at least 2-3 turns (more data = better detection)
  5. Win/lose the battle — script prints summary when battle ends
  6. Press SELECT at any time to force-print interim results

  OUTPUT: Candidate addresses for each target variable, sorted by confidence.
]]

console:log("=== EWRAM BATTLE VARIABLE DISCOVERY ===")
console:log("")

--------------------------------------------------------------------------------
-- CONSTANTS
--------------------------------------------------------------------------------

local EWRAM_BASE = 0x02000000

-- gMainInBattle absolute address and WRAM offset
local GMAIN_INBATTLE_ABS  = 0x020206AE
local GMAIN_INBATTLE_OFF  = GMAIN_INBATTLE_ABS - EWRAM_BASE  -- 0x000206AE

-- Scan regions (absolute addresses): battle BSS + near-party area
-- Region 1: 0x02008000 - 0x0200C000 (battle BSS, near gBattleTypeFlags=0x020090E8)
-- Region 2: 0x02020000 - 0x02025000 (near gMain, party data, battle resources)
local SCAN_REGIONS = {
  { startAbs = 0x02008000, endAbs = 0x0200C000, name = "battle_BSS" },
  { startAbs = 0x02020000, endAbs = 0x02025000, name = "near_party"  },
}

-- Polling interval in frames
local POLL_INTERVAL        = 30   -- General polling during battle
local INIT_POLL_INTERVAL   = 2    -- Fast polling during battle init (first 120 frames)
local INIT_WINDOW_FRAMES   = 120  -- How many frames after battle start count as "init phase"
local EXEC_FLAGS_INTERVAL  = 60   -- Separate interval for u32 exec flags scan

-- Chunk size for readRange
local CHUNK_SIZE = 4096

-- Known volatile addresses to ignore (not battle variables)
local VOLATILE_IGNORE = {
  [0x02024CBC] = true,  -- PlayerX
  [0x02024CBE] = true,  -- PlayerY
  [0x02024CC0] = true,  -- MapGroup
  [0x02024CC1] = true,  -- MapID
  [0x02036934] = true,  -- Facing
  [0x0202064C] = true,  -- gMain.callback2
  [0x020206AE] = true,  -- gMainInBattle
}

-- Mark a range as volatile (gMain struct)
for i = 0x02020648, 0x020206C0 do
  VOLATILE_IGNORE[i] = true
end

--------------------------------------------------------------------------------
-- STATE
--------------------------------------------------------------------------------

local frameCount        = 0
local inBattle          = false
local battleStartFrame  = 0
local battleFrameCount  = 0  -- frames since battle started
local pollCount         = 0

-- Snapshot: taken at battle start. Table of { [regionIndex] = string_data }
local snapshot          = nil

-- Tracking tables:
-- byteHistory[absAddr] = { values = {v1,v2,...}, frames = {f1,f2,...}, snapshotVal = n }
local byteHistory       = {}

-- u32 tracking for gBattleControllerExecFlags:
-- u32History[absAddr] = { values = {v1,v2,...}, frames = {f1,f2,...}, bitToggles = n, zeroCount = n, nonZeroCount = n }
local u32History        = {}

-- Previous SELECT button state for edge detection
local selectPrev        = false

--------------------------------------------------------------------------------
-- HELPERS
--------------------------------------------------------------------------------

--- Read a chunk of EWRAM via readRange. Returns string or nil.
local function readChunk(absStart, size)
  local offset = absStart - EWRAM_BASE
  local ok, data = pcall(emu.memory.wram.readRange, emu.memory.wram, offset, size)
  if ok and data then
    return data
  end
  return nil
end

--- Read a single u8 from EWRAM.
local function readU8(absAddr)
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, absAddr - EWRAM_BASE)
  if ok then return val end
  return nil
end

--- Read a single u32 from EWRAM.
local function readU32(absAddr)
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, absAddr - EWRAM_BASE)
  if ok then return val end
  return nil
end

--- Check if an address is in the volatile ignore set.
local function isVolatile(absAddr)
  return VOLATILE_IGNORE[absAddr] == true
end

--- Format a u32 as hex.
local function hex32(v)
  return string.format("0x%08X", v)
end

--- Format a u8 as hex.
local function hex8(v)
  return string.format("0x%02X", v)
end

--- Count how many bits differ between two u32 values.
local function bitDiffCount(a, b)
  local x = a ~ b  -- XOR: bits that differ
  local count = 0
  while x ~= 0 do
    count = count + (x & 1)
    x = x >> 1
  end
  return count
end

--- Count the number of set bits in a u32.
local function popcount(x)
  local count = 0
  while x ~= 0 do
    count = count + (x & 1)
    x = x >> 1
  end
  return count
end

--------------------------------------------------------------------------------
-- SNAPSHOT & POLLING
--------------------------------------------------------------------------------

--- Take a snapshot of all scan regions. Returns table of { [regionIdx] = string_data }.
local function takeSnapshot()
  local snap = {}
  for idx, region in ipairs(SCAN_REGIONS) do
    local regionSize = region.endAbs - region.startAbs
    local chunks = {}
    for chunkStart = region.startAbs, region.endAbs - 1, CHUNK_SIZE do
      local chunkLen = math.min(CHUNK_SIZE, region.endAbs - chunkStart)
      local data = readChunk(chunkStart, chunkLen)
      if data then
        table.insert(chunks, data)
      else
        -- Fill with zeros if read fails
        table.insert(chunks, string.rep("\0", chunkLen))
      end
    end
    snap[idx] = table.concat(chunks)
    console:log(string.format("  Snapshot region %s: %d bytes", region.name, #snap[idx]))
  end
  return snap
end

--- Poll all scan regions: compare current bytes to snapshot, update byteHistory.
local function pollRegions()
  if not snapshot then return end

  pollCount = pollCount + 1

  for idx, region in ipairs(SCAN_REGIONS) do
    local regionSize = region.endAbs - region.startAbs
    local snapData = snapshot[idx]
    if not snapData then goto continue end

    -- Read the region in chunks
    local bytePos = 1  -- position in snapData (1-based for string.byte)
    for chunkStart = region.startAbs, region.endAbs - 1, CHUNK_SIZE do
      local chunkLen = math.min(CHUNK_SIZE, region.endAbs - chunkStart)
      local currentData = readChunk(chunkStart, chunkLen)
      if not currentData then
        bytePos = bytePos + chunkLen
        goto nextChunk
      end

      -- Compare byte by byte using string.byte for speed
      for i = 1, chunkLen do
        local absAddr = chunkStart + (i - 1)

        -- Skip volatile addresses
        if not isVolatile(absAddr) then
          local currentByte = string.byte(currentData, i)
          local snapByte = string.byte(snapData, bytePos + (i - 1))

          if currentByte ~= snapByte then
            -- This byte changed from snapshot
            if not byteHistory[absAddr] then
              byteHistory[absAddr] = {
                values = { snapByte },
                frames = { 0 },
                snapshotVal = snapByte,
                changeCount = 0,
                lastValue = snapByte,
                minVal = snapByte,
                maxVal = snapByte,
              }
            end

            local entry = byteHistory[absAddr]
            if currentByte ~= entry.lastValue then
              entry.changeCount = entry.changeCount + 1
              table.insert(entry.values, currentByte)
              table.insert(entry.frames, battleFrameCount)
              entry.lastValue = currentByte

              if currentByte < entry.minVal then entry.minVal = currentByte end
              if currentByte > entry.maxVal then entry.maxVal = currentByte end

              -- Cap stored values to avoid memory bloat (keep first 200 + last 50)
              if #entry.values > 300 then
                local trimmed = {}
                local trimmedF = {}
                for j = 1, 200 do
                  trimmed[j] = entry.values[j]
                  trimmedF[j] = entry.frames[j]
                end
                for j = #entry.values - 49, #entry.values do
                  table.insert(trimmed, entry.values[j])
                  table.insert(trimmedF, entry.frames[j])
                end
                entry.values = trimmed
                entry.frames = trimmedF
              end
            end
          end
        end
      end

      ::nextChunk::
      bytePos = bytePos + chunkLen
    end

    ::continue::
  end
end

--- Poll for u32 exec flags candidates (separate from byte polling).
--- Scans the battle BSS region for u32 values with bits 0-3 characteristics.
local function pollExecFlags()
  if not snapshot then return end

  local region = SCAN_REGIONS[1]  -- battle_BSS (0x02008000-0x0200C000)
  local regionSize = region.endAbs - region.startAbs

  for chunkStart = region.startAbs, region.endAbs - 4, CHUNK_SIZE do
    local chunkLen = math.min(CHUNK_SIZE, region.endAbs - chunkStart)
    if chunkLen < 4 then goto nextU32Chunk end

    local data = readChunk(chunkStart, chunkLen)
    if not data then goto nextU32Chunk end

    -- Read u32 values (little-endian from string bytes)
    for i = 1, chunkLen - 3, 4 do
      local absAddr = chunkStart + (i - 1)
      if not isVolatile(absAddr) then
        local b0 = string.byte(data, i)
        local b1 = string.byte(data, i + 1)
        local b2 = string.byte(data, i + 2)
        local b3 = string.byte(data, i + 3)
        local val = b0 + b1 * 0x100 + b2 * 0x10000 + b3 * 0x1000000

        if not u32History[absAddr] then
          u32History[absAddr] = {
            values = {},
            frames = {},
            lastValue = 0,
            zeroCount = 0,
            nonZeroCount = 0,
            bitToggles = 0,
            maxBitsSet = 0,
          }
        end

        local entry = u32History[absAddr]

        if val ~= entry.lastValue then
          -- Track bit toggles (bits that flipped)
          local flipped = val ~ entry.lastValue
          entry.bitToggles = entry.bitToggles + popcount(flipped)

          -- Track max bits set at any one time
          local bitsSet = popcount(val)
          if bitsSet > entry.maxBitsSet then entry.maxBitsSet = bitsSet end

          if #entry.values < 200 then
            table.insert(entry.values, val)
            table.insert(entry.frames, battleFrameCount)
          end

          entry.lastValue = val
        end

        if val == 0 then
          entry.zeroCount = entry.zeroCount + 1
        else
          entry.nonZeroCount = entry.nonZeroCount + 1
        end
      end
    end

    ::nextU32Chunk::
  end
end

--------------------------------------------------------------------------------
-- ANALYSIS & CANDIDATE SCORING
--------------------------------------------------------------------------------

--- Analyze byteHistory for gActiveBattler candidates (u8 cycling 0-3).
local function findActiveBattlerCandidates()
  local candidates = {}

  for absAddr, entry in pairs(byteHistory) do
    -- gActiveBattler: u8 that cycles through values 0, 1, 2, 3
    -- Must have: minVal=0, maxVal<=3, many changes, values only in {0,1,2,3}
    if entry.maxVal <= 3 and entry.minVal == 0 and entry.changeCount >= 10 then
      -- Verify all observed values are in range 0-3
      local allInRange = true
      local valueSeen = { [0]=false, [1]=false, [2]=false, [3]=false }
      for _, v in ipairs(entry.values) do
        if v > 3 then
          allInRange = false
          break
        end
        valueSeen[v] = true
      end

      if allInRange then
        -- Count how many distinct values {0,1,2,3} were seen
        local distinctCount = 0
        for i = 0, 3 do
          if valueSeen[i] then distinctCount = distinctCount + 1 end
        end

        -- Score: higher = better candidate
        -- Best: sees all 4 values (0-3), many changes, changes frequently
        local score = entry.changeCount * distinctCount

        table.insert(candidates, {
          addr = absAddr,
          score = score,
          changeCount = entry.changeCount,
          distinctValues = distinctCount,
          snapshotVal = entry.snapshotVal,
          sampleValues = entry.values,
        })
      end
    end
  end

  table.sort(candidates, function(a, b) return a.score > b.score end)
  return candidates
end

--- Analyze byteHistory for gBattleCommunication candidates (u8[8] incrementing block).
local function findBattleCommCandidates()
  local candidates = {}

  -- Look for bytes that started at 0 in snapshot and incremented to >=5
  -- during the init window. gBattleCommunication[0] goes 0→1→2→...→12+
  for absAddr, entry in pairs(byteHistory) do
    if entry.snapshotVal == 0 and entry.maxVal >= 5 then
      -- Check if values are monotonically incrementing (at least mostly)
      local isIncrementing = true
      local prevVal = 0
      local incrementCount = 0
      for i = 2, math.min(#entry.values, 50) do
        if entry.values[i] > entry.values[i-1] then
          incrementCount = incrementCount + 1
        elseif entry.values[i] < entry.values[i-1] - 1 then
          -- Allow small decreases (battle might re-process)
          isIncrementing = false
          break
        end
      end

      if isIncrementing and incrementCount >= 3 then
        -- Check if this could be the start of an 8-byte block:
        -- Look for adjacent bytes (absAddr+1..+7) that also changed from snapshot
        local adjacentChanged = 0
        for offset = 1, 7 do
          if byteHistory[absAddr + offset] then
            adjacentChanged = adjacentChanged + 1
          end
        end

        local score = entry.maxVal * 10 + incrementCount * 5 + adjacentChanged * 20

        -- Check if early changes happened during init window
        local initChanges = 0
        for i, f in ipairs(entry.frames) do
          if f > 0 and f <= INIT_WINDOW_FRAMES then
            initChanges = initChanges + 1
          end
        end
        score = score + initChanges * 15

        table.insert(candidates, {
          addr = absAddr,
          score = score,
          maxVal = entry.maxVal,
          incrementCount = incrementCount,
          adjacentChanged = adjacentChanged,
          initChanges = initChanges,
          snapshotVal = entry.snapshotVal,
          sampleValues = entry.values,
        })
      end
    end
  end

  table.sort(candidates, function(a, b) return a.score > b.score end)
  return candidates
end

--- Analyze u32History for gBattleControllerExecFlags candidates.
local function findExecFlagsCandidates()
  local candidates = {}

  for absAddr, entry in pairs(u32History) do
    -- gBattleControllerExecFlags: u32 that toggles bits 0-3
    -- Characteristics:
    -- - Alternates between 0 and small values (bits 0-3 = battler flags)
    -- - High bitToggle count (bits flip often)
    -- - Both zeroCount and nonZeroCount should be significant
    -- - maxBitsSet should be small (1-4 typically, one bit per battler)

    if entry.bitToggles >= 5
      and entry.zeroCount >= 3
      and entry.nonZeroCount >= 3
      and entry.maxBitsSet <= 8  -- typically 1-4 bits
    then
      -- Check that observed non-zero values are small (battler bits: 0x1, 0x2, 0x4, 0x8 or combos)
      local allSmall = true
      local seenNonZero = {}
      for _, v in ipairs(entry.values) do
        if v ~= 0 then
          if v > 0xFF then
            allSmall = false
            break
          end
          seenNonZero[v] = true
        end
      end

      if allSmall then
        -- Score based on toggle frequency, zero/nonzero balance, and bit range
        local balance = math.min(entry.zeroCount, entry.nonZeroCount)
        local score = entry.bitToggles * 3 + balance * 5

        -- Bonus: if values match typical battler bit patterns (0x1, 0x2, 0x3, 0x4, etc.)
        local typicalPatterns = 0
        for v, _ in pairs(seenNonZero) do
          if v == 0x1 or v == 0x2 or v == 0x3 or v == 0x4
            or v == 0x5 or v == 0x6 or v == 0x8 or v == 0xF then
            typicalPatterns = typicalPatterns + 1
          end
        end
        score = score + typicalPatterns * 20

        -- Count distinct non-zero values
        local distinctNZ = 0
        for _ in pairs(seenNonZero) do distinctNZ = distinctNZ + 1 end

        table.insert(candidates, {
          addr = absAddr,
          score = score,
          bitToggles = entry.bitToggles,
          zeroCount = entry.zeroCount,
          nonZeroCount = entry.nonZeroCount,
          maxBitsSet = entry.maxBitsSet,
          distinctNonZero = distinctNZ,
          typicalPatterns = typicalPatterns,
          sampleValues = entry.values,
        })
      end
    end
  end

  table.sort(candidates, function(a, b) return a.score > b.score end)
  return candidates
end

--- Scan for gLinkPlayers candidates (5 × 28-byte structs in EWRAM).
--- gLinkPlayers is typically zeroed outside of link battles. During a regular
--- trainer battle it's still zeroed, BUT if we set gReceivedRemoteLinkPlayers=1
--- some link init code may populate it. So instead we look for 140-byte aligned
--- blocks that are all zero during a trainer battle (will be populated during our
--- fake link battle) OR search for the structure near known BSS.
local function findLinkPlayersCandidates()
  local candidates = {}

  -- Strategy: gLinkPlayers is 140 bytes (5 * 28). In vanilla emerald it's at 0x020229E8.
  -- The delta from vanilla to R&B for gPlayerParty was 0x02023A98 - 0x020244EC = -0xA54.
  -- For gBattleTypeFlags: 0x020090E8 vs vanilla 0x02022FEC → delta = -0x19F04 (huge, different BSS)
  -- So deltas vary. Search broadly.

  -- During a trainer battle (non-link), gLinkPlayers should be all zeros (or have stale data).
  -- We look for 140-byte zero blocks at 4-byte alignment in the scan regions,
  -- especially near the battle BSS area.

  -- Also check: the vanilla address +/- reasonable deltas
  local checkAddrs = {
    0x020229E8,             -- vanilla exact
    0x020229E8 - 0xA54,     -- delta from party
    0x020229E8 + 0x878,     -- positive delta (like overworld)
  }

  -- Check specific predicted addresses first
  for _, addr in ipairs(checkAddrs) do
    if addr >= 0x02000000 and addr < 0x0203FC00 then
      local data = readChunk(addr, 140)
      if data then
        -- Check if it's all zeros (typical for non-link battle state)
        local allZero = true
        for i = 1, 140 do
          if string.byte(data, i) ~= 0 then
            allZero = false
            break
          end
        end

        table.insert(candidates, {
          addr = addr,
          allZero = allZero,
          source = "predicted",
          score = allZero and 50 or 10,
        })
      end
    end
  end

  -- Broader search: scan battle BSS for 140-byte blocks that are all zeros
  -- but have non-zero data before and after (suggesting an allocated but unused struct array)
  local region = SCAN_REGIONS[1]  -- battle_BSS
  for chunkStart = region.startAbs, region.endAbs - 140, CHUNK_SIZE do
    local chunkLen = math.min(CHUNK_SIZE, region.endAbs - chunkStart)
    if chunkLen < 140 then goto nextLPChunk end

    local data = readChunk(chunkStart, chunkLen)
    if not data then goto nextLPChunk end

    -- Scan for 140-byte zero blocks at 4-byte alignment
    for i = 1, chunkLen - 139, 4 do
      local absAddr = chunkStart + (i - 1)
      local allZero = true
      for j = i, i + 139 do
        if string.byte(data, j) ~= 0 then
          allZero = false
          break
        end
      end

      if allZero then
        -- Check that surrounding bytes are NOT all zero (this isn't just empty RAM)
        local beforeNonZero = false
        local afterNonZero = false
        if i > 4 then
          for j = math.max(1, i - 4), i - 1 do
            if string.byte(data, j) ~= 0 then
              beforeNonZero = true
              break
            end
          end
        end
        if i + 140 + 3 <= chunkLen then
          for j = i + 140, math.min(chunkLen, i + 143) do
            if string.byte(data, j) ~= 0 then
              afterNonZero = true
              break
            end
          end
        end

        -- Only interesting if surrounded by non-zero (it's an actual variable, not empty space)
        if beforeNonZero or afterNonZero then
          -- Additional check: does this address fall near other known battle vars?
          local nearBattle = false
          if absAddr >= 0x02008000 and absAddr <= 0x0200C000 then
            nearBattle = true
          end

          local score = 30
          if beforeNonZero and afterNonZero then score = score + 20 end
          if nearBattle then score = score + 10 end

          table.insert(candidates, {
            addr = absAddr,
            allZero = true,
            source = "bss_scan",
            beforeNonZero = beforeNonZero,
            afterNonZero = afterNonZero,
            score = score,
          })
        end
      end
    end

    ::nextLPChunk::
  end

  table.sort(candidates, function(a, b) return a.score > b.score end)
  return candidates
end

--------------------------------------------------------------------------------
-- PRINTING
--------------------------------------------------------------------------------

local function printSampleValues(values, maxCount)
  local parts = {}
  local count = math.min(#values, maxCount or 20)
  for i = 1, count do
    table.insert(parts, string.format("%d", values[i]))
  end
  if #values > count then
    table.insert(parts, "...")
  end
  return table.concat(parts, ", ")
end

local function printSampleValuesHex(values, maxCount)
  local parts = {}
  local count = math.min(#values, maxCount or 20)
  for i = 1, count do
    table.insert(parts, hex32(values[i]))
  end
  if #values > count then
    table.insert(parts, "...")
  end
  return table.concat(parts, ", ")
end

local function printResults()
  console:log("")
  console:log("===============================================================")
  console:log("=== EWRAM BATTLE VARIABLE DISCOVERY — RESULTS ===")
  console:log(string.format("=== Battle lasted %d frames, %d polls, %d tracked bytes ===",
    battleFrameCount, pollCount, 0))  -- count below
  console:log("===============================================================")
  console:log("")

  -- Count tracked bytes
  local trackedCount = 0
  for _ in pairs(byteHistory) do trackedCount = trackedCount + 1 end
  local u32Count = 0
  for _ in pairs(u32History) do u32Count = u32Count + 1 end
  console:log(string.format("  Tracked: %d changed bytes, %d u32 locations", trackedCount, u32Count))
  console:log("")

  ------------------------------------------------------------
  -- 1. gActiveBattler
  ------------------------------------------------------------
  console:log("=== CANDIDATE: gActiveBattler (u8, cycles 0-3) ===")
  local abCandidates = findActiveBattlerCandidates()
  if #abCandidates == 0 then
    console:log("  No candidates found. Need more battle turns?")
  else
    local showCount = math.min(#abCandidates, 10)
    for i = 1, showCount do
      local c = abCandidates[i]
      console:log(string.format("  #%d  %s  score=%d  changes=%d  distinct={0..%d}=%d values  snap=%d",
        i, hex32(c.addr), c.score, c.changeCount, 3, c.distinctValues, c.snapshotVal))
      console:log(string.format("       sample: %s", printSampleValues(c.sampleValues, 30)))
    end
    if #abCandidates > showCount then
      console:log(string.format("  ... and %d more candidates", #abCandidates - showCount))
    end
  end
  console:log("")

  ------------------------------------------------------------
  -- 2. gBattleCommunication
  ------------------------------------------------------------
  console:log("=== CANDIDATE: gBattleCommunication (u8[8], incrementing during init) ===")
  local bcCandidates = findBattleCommCandidates()
  if #bcCandidates == 0 then
    console:log("  No candidates found. Battle init phase may have been missed.")
    console:log("  TIP: Reload script, then immediately enter battle for init capture.")
  else
    local showCount = math.min(#bcCandidates, 10)
    for i = 1, showCount do
      local c = bcCandidates[i]
      console:log(string.format("  #%d  %s  score=%d  maxVal=%d  incr=%d  adj=%d  initChanges=%d",
        i, hex32(c.addr), c.score, c.maxVal, c.incrementCount, c.adjacentChanged, c.initChanges))
      console:log(string.format("       sample: %s", printSampleValues(c.sampleValues, 30)))

      -- Print adjacent bytes status
      local adjStr = "  adjacent: "
      for off = 0, 7 do
        local adjEntry = byteHistory[c.addr + off]
        if adjEntry then
          adjStr = adjStr .. string.format("[+%d: %d changes, max=%d] ", off, adjEntry.changeCount, adjEntry.maxVal)
        else
          adjStr = adjStr .. string.format("[+%d: no change] ", off)
        end
      end
      console:log(string.format("     %s", adjStr))
    end
    if #bcCandidates > showCount then
      console:log(string.format("  ... and %d more candidates", #bcCandidates - showCount))
    end
  end
  console:log("")

  ------------------------------------------------------------
  -- 3. gBattleControllerExecFlags
  ------------------------------------------------------------
  console:log("=== CANDIDATE: gBattleControllerExecFlags (u32, bit toggles) ===")
  local efCandidates = findExecFlagsCandidates()
  if #efCandidates == 0 then
    console:log("  No candidates found. Need more battle turns or check scan range.")
  else
    local showCount = math.min(#efCandidates, 10)
    for i = 1, showCount do
      local c = efCandidates[i]
      console:log(string.format("  #%d  %s  score=%d  toggles=%d  zero=%d  nonzero=%d  maxBits=%d  distinctNZ=%d  typical=%d",
        i, hex32(c.addr), c.score, c.bitToggles, c.zeroCount, c.nonZeroCount,
        c.maxBitsSet, c.distinctNonZero, c.typicalPatterns))
      console:log(string.format("       sample: %s", printSampleValuesHex(c.sampleValues, 15)))
    end
    if #efCandidates > showCount then
      console:log(string.format("  ... and %d more candidates", #efCandidates - showCount))
    end
  end
  console:log("")

  ------------------------------------------------------------
  -- 4. gLinkPlayers
  ------------------------------------------------------------
  console:log("=== CANDIDATE: gLinkPlayers (5 x 28-byte structs, 140 bytes total) ===")
  local lpCandidates = findLinkPlayersCandidates()
  if #lpCandidates == 0 then
    console:log("  No candidates found (no 140-byte zero blocks near battle data).")
  else
    local showCount = math.min(#lpCandidates, 10)
    for i = 1, showCount do
      local c = lpCandidates[i]
      console:log(string.format("  #%d  %s  score=%d  allZero=%s  source=%s",
        i, hex32(c.addr), c.score, tostring(c.allZero), c.source))
      if c.beforeNonZero ~= nil then
        console:log(string.format("       bordered: before=%s after=%s",
          tostring(c.beforeNonZero), tostring(c.afterNonZero)))
      end
    end
    if #lpCandidates > showCount then
      console:log(string.format("  ... and %d more candidates", #lpCandidates - showCount))
    end
  end
  console:log("")

  ------------------------------------------------------------
  -- 5. Cross-reference with vanilla deltas
  ------------------------------------------------------------
  console:log("=== CROSS-REFERENCE: Vanilla Address Deltas ===")
  console:log("  Known R&B deltas from vanilla Emerald:")
  console:log(string.format("    gBattleTypeFlags: R&B=0x020090E8  vanilla=0x02022FEC  delta=%+d",
    0x020090E8 - 0x02022FEC))
  console:log(string.format("    gPlayerParty:     R&B=0x02023A98  vanilla=0x020244EC  delta=%+d",
    0x02023A98 - 0x020244EC))
  console:log("")

  -- Apply the gBattleTypeFlags delta to vanilla addresses as predictions
  local btfDelta = 0x020090E8 - 0x02022FEC  -- = -0x19F04
  local partyDelta = 0x02023A98 - 0x020244EC  -- = -0xA54

  local predictions = {
    { name = "gActiveBattler",           vanillaAddr = 0x02024064, delta = btfDelta },
    { name = "gActiveBattler",           vanillaAddr = 0x02024064, delta = partyDelta },
    { name = "gBattleControllerExecFlags", vanillaAddr = 0x02024068, delta = btfDelta },
    { name = "gBattleControllerExecFlags", vanillaAddr = 0x02024068, delta = partyDelta },
    { name = "gBattleCommunication",     vanillaAddr = 0x02024332, delta = btfDelta },
    { name = "gBattleCommunication",     vanillaAddr = 0x02024332, delta = partyDelta },
    { name = "gLinkPlayers",             vanillaAddr = 0x020229E8, delta = btfDelta },
    { name = "gLinkPlayers",             vanillaAddr = 0x020229E8, delta = partyDelta },
  }

  for _, pred in ipairs(predictions) do
    local predicted = pred.vanillaAddr + pred.delta
    if predicted >= 0x02000000 and predicted < 0x02040000 then
      local val = readU32(predicted)
      local valStr = val and hex32(val) or "read_failed"
      console:log(string.format("    %s: vanilla %s + delta %+d = %s  current_u32=%s",
        pred.name, hex32(pred.vanillaAddr), pred.delta, hex32(predicted), valStr))
    end
  end
  console:log("")

  ------------------------------------------------------------
  -- 6. Bulk stats
  ------------------------------------------------------------
  console:log("=== MOST ACTIVE BYTES (top 20 by change count) ===")
  local sorted = {}
  for absAddr, entry in pairs(byteHistory) do
    table.insert(sorted, { addr = absAddr, changes = entry.changeCount, min = entry.minVal, max = entry.maxVal })
  end
  table.sort(sorted, function(a, b) return a.changes > b.changes end)
  for i = 1, math.min(20, #sorted) do
    local s = sorted[i]
    console:log(string.format("    %s  changes=%d  range=[%d..%d]",
      hex32(s.addr), s.changes, s.min, s.max))
  end
  console:log("")

  console:log("===============================================================")
  console:log("=== END OF DISCOVERY RESULTS ===")
  console:log("===============================================================")
  console:log("")
  console:log("NEXT STEPS:")
  console:log("  1. Check top gActiveBattler candidates — look for the one near")
  console:log("     gBattleControllerExecFlags (they are adjacent in vanilla BSS)")
  console:log("  2. gBattleCommunication[0] should increment 0→12+ during init")
  console:log("  3. gBattleControllerExecFlags should toggle bits 0-3")
  console:log("  4. gLinkPlayers is zeroed in trainer battles — verify in link mode")
  console:log("  5. Fill confirmed addresses in config/run_and_bun.lua battle_link section")
  console:log("")
end

--------------------------------------------------------------------------------
-- FRAME CALLBACK
--------------------------------------------------------------------------------

local function onFrame()
  frameCount = frameCount + 1

  -- Read gMainInBattle
  local inBattleNow = false
  local val = readU8(GMAIN_INBATTLE_ABS)
  if val and val == 1 then
    inBattleNow = true
  end

  -- Detect battle start (overworld → battle: 0 → 1)
  if inBattleNow and not inBattle then
    inBattle = true
    battleStartFrame = frameCount
    battleFrameCount = 0
    pollCount = 0

    -- Reset tracking
    byteHistory = {}
    u32History = {}

    console:log("")
    console:log(string.format("[Frame %d] BATTLE START detected — taking snapshot...", frameCount))

    snapshot = takeSnapshot()

    console:log("  Snapshot complete. Polling will begin next frame.")
    console:log("  Fight at least 2-3 turns for best results.")
    console:log("  Press SELECT for interim results, or wait for battle end.")
    console:log("")
  end

  -- During battle: poll at intervals
  if inBattle and inBattleNow then
    battleFrameCount = frameCount - battleStartFrame

    -- Determine poll rate: fast during init, normal otherwise
    local currentPollInterval = POLL_INTERVAL
    if battleFrameCount <= INIT_WINDOW_FRAMES then
      currentPollInterval = INIT_POLL_INTERVAL
    end

    -- Byte-level polling
    if battleFrameCount % currentPollInterval == 0 then
      pollRegions()
    end

    -- u32 exec flags polling (separate, slower interval)
    if battleFrameCount % EXEC_FLAGS_INTERVAL == 0 then
      pollExecFlags()
    end

    -- Progress indicator every 300 frames (~5 sec)
    if battleFrameCount % 300 == 0 and battleFrameCount > 0 then
      local trackedCount = 0
      for _ in pairs(byteHistory) do trackedCount = trackedCount + 1 end
      console:log(string.format("  [Battle +%d frames] %d polls, %d changed bytes tracked...",
        battleFrameCount, pollCount, trackedCount))
    end
  end

  -- Detect battle end (battle → overworld: 1 → 0)
  if not inBattleNow and inBattle then
    inBattle = false
    console:log("")
    console:log(string.format("[Frame %d] BATTLE END detected (lasted %d frames)", frameCount, battleFrameCount))
    console:log("  Analyzing collected data...")

    printResults()

    -- Don't clear data — user can press SELECT to re-print
  end

  -- SELECT button: force-print interim/final results
  local ok, keys = pcall(function() return emu.memory.io:read16(0x0130) end)
  if ok then
    local selectNow = ((~keys) & 0x0004) ~= 0
    if selectNow and not selectPrev then
      if snapshot then
        console:log("")
        console:log("[SELECT pressed] Printing current results...")
        printResults()
      else
        console:log("[SELECT pressed] No data yet — enter a battle first.")
      end
    end
    selectPrev = selectNow
  end
end

-- Register frame callback
callbacks:add("frame", onFrame)

--------------------------------------------------------------------------------
-- STARTUP
--------------------------------------------------------------------------------

console:log("")
console:log("Configuration:")
console:log(string.format("  gMainInBattle:  %s (monitor for battle start/end)", hex32(GMAIN_INBATTLE_ABS)))
console:log(string.format("  Scan region 1:  0x%08X - 0x%08X (%s)",
  SCAN_REGIONS[1].startAbs, SCAN_REGIONS[1].endAbs, SCAN_REGIONS[1].name))
console:log(string.format("  Scan region 2:  0x%08X - 0x%08X (%s)",
  SCAN_REGIONS[2].startAbs, SCAN_REGIONS[2].endAbs, SCAN_REGIONS[2].name))
console:log(string.format("  Poll interval:  %d frames (init: %d frames for first %d frames)",
  POLL_INTERVAL, INIT_POLL_INTERVAL, INIT_WINDOW_FRAMES))
console:log(string.format("  ExecFlags poll: every %d frames", EXEC_FLAGS_INTERVAL))
console:log("")
console:log("Instructions:")
console:log("  1. Walk around in the overworld (script watches for battle)")
console:log("  2. Enter a TRAINER battle (wild also works, trainer has more turns)")
console:log("  3. Fight at least 2-3 turns for good data collection")
console:log("  4. Win or lose the battle — results print automatically on exit")
console:log("  5. Press SELECT at any time for interim results")
console:log("")
console:log("  The script snapshots EWRAM at battle start, then polls for changes.")
console:log("  Changed bytes are categorized by pattern (cycling, incrementing, toggling).")
console:log("")
console:log("=== READY — waiting for battle ===")
