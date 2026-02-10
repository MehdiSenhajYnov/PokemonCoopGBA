--[[
  gBattleResources Verifier

  APPROACH: gBattleResources is NULL (0) in overworld, non-NULL in battle.

  Step 1 (overworld): Snapshot all 4-byte aligned EWRAM positions that are 0
  Step 2 (battle): Check which of those positions now hold EWRAM pointers
  Step 3: For each candidate, dereference and measure allocation size

  The one with the largest allocation (~4368 bytes) is gBattleResources.

  Also verifies the previous candidate: 0x02023A18

  USAGE:
  1. Load script in OVERWORLD (not in battle!)
  2. Press START to take overworld snapshot
  3. Enter battle, wait for Fight/Bag/Pokemon/Run
  4. Press SELECT to scan
]]

console:log("=== gBattleResources VERIFIER ===")
console:log("")

local frameCount = 0
local startPrev = false
local selectPrev = false

-- Overworld zero-positions snapshot
local zeroPositions = nil
local snapshotFrame = 0

local CHUNK = 4096
local EWRAM_SIZE = 0x40000

local function readU32(addr)
  if addr < 0x02000000 or addr > 0x0203FFFC then return nil end
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, addr - 0x02000000)
  if ok then return val else return nil end
end

local function readU8(addr)
  if addr < 0x02000000 or addr > 0x0203FFFF then return nil end
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, addr - 0x02000000)
  if ok then return val else return nil end
end

local function isEwramPtr(val)
  return val and val >= 0x02000100 and val <= 0x0203FFFF
end

-- Measure how many non-zero bytes exist starting from addr (up to maxLen)
local function measureAllocationSize(addr, maxLen)
  local lastNonZero = 0
  for i = 0, maxLen - 1, 4 do
    local val = readU32(addr + i)
    if val and val ~= 0 then
      lastNonZero = i + 4
    end
  end
  return lastNonZero
end

local function hexDump(addr, len)
  local parts = {}
  for i = 0, math.min(len, 16) - 1 do
    local b = readU8(addr + i)
    if b then table.insert(parts, string.format("%02X", b)) end
  end
  return table.concat(parts, " ")
end

-- STEP 1: Take overworld snapshot (find all zero u32 positions)
local function takeOverworldSnapshot()
  console:log("")
  console:log("[START] Taking overworld snapshot (finding zero positions)...")

  -- Verify not in battle
  local btf = readU32(0x020090E8)
  if btf and btf ~= 0 then
    console:log("  WARNING: gBattleTypeFlags != 0 — you might be in battle!")
    console:log("  Do this in the OVERWORLD for best results.")
  end

  -- Quick check of previous candidate
  local prevCandidate = readU32(0x02023A18)
  console:log(string.format("  Previous candidate 0x02023A18 = 0x%08X %s",
    prevCandidate or 0,
    (prevCandidate == 0) and "(NULL — good, expected in overworld)" or "(NON-ZERO — suspicious)"))

  -- Collect positions where value is 0
  -- Focus on likely BSS regions (0x02008000 - 0x0203F000)
  -- Battle globals are typically in BSS, not low heap
  zeroPositions = {}

  for base = 0x8000, EWRAM_SIZE - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.wram.readRange, emu.memory.wram, base, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do
        local b0 = string.byte(data, i)
        local b1 = string.byte(data, i + 1)
        local b2 = string.byte(data, i + 2)
        local b3 = string.byte(data, i + 3)
        if b0 == 0 and b1 == 0 and b2 == 0 and b3 == 0 then
          table.insert(zeroPositions, 0x02000000 + base + (i - 1))
        end
      end
    end
  end

  snapshotFrame = frameCount
  console:log(string.format("  Found %d zero u32 positions in EWRAM (0x02008000+)", #zeroPositions))
  console:log("  Now enter battle and press SELECT.")
end

-- STEP 2: Check which zeros became EWRAM pointers
local function doBattleScan()
  console:log("")
  console:log("[SELECT] Scanning for NULL->pointer transitions...")

  if not zeroPositions then
    console:log("  ERROR: Take overworld snapshot first (press START)!")
    return
  end

  local btf = readU32(0x020090E8)
  console:log(string.format("  gBattleTypeFlags = 0x%08X %s",
    btf or 0, (btf and btf ~= 0) and "(IN BATTLE)" or "(NOT IN BATTLE!)"))

  if not btf or btf == 0 then
    console:log("  ERROR: Not in battle! Enter a battle first.")
    return
  end

  -- Check previous candidate first
  local prevVal = readU32(0x02023A18)
  console:log(string.format("  Previous candidate 0x02023A18 = 0x%08X %s",
    prevVal or 0,
    isEwramPtr(prevVal) and "(EWRAM POINTER — promising!)" or "(not a pointer)"))

  -- Find NULL->pointer transitions
  local transitions = {}
  for _, addr in ipairs(zeroPositions) do
    local val = readU32(addr)
    if isEwramPtr(val) then
      -- Measure allocation size at the pointed-to address
      local allocSize = measureAllocationSize(val, 8192)

      table.insert(transitions, {
        varAddr = addr,
        ptrVal = val,
        allocSize = allocSize,
      })
    end
  end

  console:log(string.format("  Found %d NULL->pointer transitions", #transitions))
  console:log("")

  -- Sort by allocation size (largest = most likely gBattleResources at ~4368 bytes)
  table.sort(transitions, function(a, b) return a.allocSize > b.allocSize end)

  -- Print top candidates
  console:log("  TOP CANDIDATES (sorted by allocation size, target ~4368 bytes):")
  console:log("")

  for i = 1, math.min(20, #transitions) do
    local t = transitions[i]
    local match = ""
    if t.allocSize >= 4000 and t.allocSize <= 5000 then
      match = " *** LIKELY gBattleResources! ***"
    elseif t.allocSize >= 2000 then
      match = " ** large allocation"
    end

    console:log(string.format("  [%d] 0x%08X -> 0x%08X (alloc ~%d bytes)%s",
      i, t.varAddr, t.ptrVal, t.allocSize, match))

    -- Show struct start
    console:log(string.format("       +0x00: %s", hexDump(t.ptrVal, 16)))
    console:log(string.format("       +0x10: %s", hexDump(t.ptrVal + 0x10, 16)))

    -- If it's in the right size range, show buffer locations
    if t.allocSize >= 4000 and t.allocSize <= 5000 then
      console:log(string.format("       +0x810 (bufferB): %s", hexDump(t.ptrVal + 0x810, 16)))
      console:log(string.format("       +0x1010 (xferBuf): %s", hexDump(t.ptrVal + 0x1010, 16)))
    end

    console:log("")
  end

  -- Also do ROM literal scan for top candidates
  console:log("--- ROM VERIFICATION ---")
  console:log("  Checking if top candidates are referenced in ROM literal pools...")
  console:log("")

  local ROM_SIZE = 0x800000
  for ci = 1, math.min(5, #transitions) do
    local targetAddr = transitions[ci].varAddr
    local b0 = targetAddr & 0xFF
    local b1 = (targetAddr >> 8) & 0xFF
    local b2 = (targetAddr >> 16) & 0xFF
    local b3 = (targetAddr >> 24) & 0xFF

    local romRefs = 0
    for base = 0, ROM_SIZE - CHUNK, CHUNK do
      local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
      if ok and data then
        for i = 1, #data - 3, 4 do
          if string.byte(data, i) == b0 and
             string.byte(data, i+1) == b1 and
             string.byte(data, i+2) == b2 and
             string.byte(data, i+3) == b3 then
            romRefs = romRefs + 1
          end
        end
      end
    end

    console:log(string.format("  0x%08X: %d ROM refs %s",
      targetAddr, romRefs,
      romRefs > 0 and "(CONFIRMED — ROM accesses this variable!)" or "(no ROM refs)"))
  end

  console:log("")
  console:log("=== VERIFICATION COMPLETE ===")
end

local function onFrame()
  frameCount = frameCount + 1
  local ok, keys = pcall(function() return emu.memory.io:read16(0x0130) end)
  if not ok then return end
  local pressed = (~keys) & 0x000F
  local startNow = (pressed & 0x0008) ~= 0
  local selectNow = (pressed & 0x0004) ~= 0

  if startNow and not startPrev then takeOverworldSnapshot() end
  if selectNow and not selectPrev then doBattleScan() end

  startPrev = startNow
  selectPrev = selectNow
end

callbacks:add("frame", onFrame)

console:log("Instructions:")
console:log("  1. In OVERWORLD: press START (snapshot zeros)")
console:log("  2. Enter battle, wait for Fight/Bag/Pokemon/Run")
console:log("  3. Press SELECT (find NULL->pointer transitions)")
console:log("")
console:log("=== READY ===")
