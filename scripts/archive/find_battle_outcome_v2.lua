--[[
  gBattleOutcome Finder v2 - Instant capture

  Captures values at the EXACT frame when inBattle transitions 1→0.
  No delay, no value assumptions.

  Also verifies candidate 0x020265CA from previous scan.

  pokeemerald outcome values (for reference):
    1 = B_OUTCOME_WON
    2 = B_OUTCOME_LOST
    3 = B_OUTCOME_DREW
    4 = B_OUTCOME_RAN (flee)
    7 = B_OUTCOME_CAUGHT

  USAGE:
  1. Load outside of battle
  2. Wait 3 seconds
  3. Enter battle and WIN → note result
  4. Enter battle and FLEE → note result
  5. Compare: same address with val=1 (win) and val=4 (flee) = gBattleOutcome
]]

local EWRAM_START = 0x02000000
local EWRAM_SIZE  = 0x40000

local INBATTLE_ADDR = 0x020206AE
local INBATTLE_WRAM = INBATTLE_ADDR - EWRAM_START

-- Previous candidate to verify
local CANDIDATE_ADDR = 0x020265CA
local CANDIDATE_WRAM = CANDIDATE_ADDR - EWRAM_START

local function readInBattle()
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, INBATTLE_WRAM)
  if ok then return val end
  return nil
end

local function readByte(offset)
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  if ok then return val end
  return nil
end

-- State
local prevInBattle = nil
local battleNum = 0
local baselineSnap = nil  -- snapshot taken at battle START
local state = "calibrating"
local stateFrames = 0
local frameCount = 0

-- Results per battle
local allResults = {}

-- Take snapshot of all EWRAM
local function takeSnapshot()
  local snap = {}
  for offset = 0, EWRAM_SIZE - 1 do
    snap[offset] = readByte(offset) or -1
  end
  return snap
end

-- Fast comparison: find bytes that were 0 at start and are now non-zero
local function findChangedFromZero()
  local changed = {}
  for offset = 0, EWRAM_SIZE - 1 do
    if baselineSnap[offset] == 0 then
      local val = readByte(offset)
      if val and val ~= 0 and val <= 10 then  -- outcome values are small (1-10)
        changed[#changed + 1] = {offset = offset, addr = EWRAM_START + offset, val = val}
      end
    end
  end
  return changed
end

local function showCandidate()
  local val = readByte(CANDIDATE_WRAM)
  console:log(string.format("[MONITOR] Candidate 0x%08X = %s", CANDIDATE_ADDR, val and tostring(val) or "nil"))
end

local function tick()
  frameCount = frameCount + 1

  local inBattle = readInBattle()
  if inBattle == nil then return end

  if state == "calibrating" then
    if inBattle == 0 then
      stateFrames = stateFrames + 1
      if stateFrames == 1 then
        console:log("[SCAN] Calibrating... stay outside")
      end
      if stateFrames >= 180 then  -- 3 seconds at 60fps
        state = "ready"
        console:log("[SCAN] Ready! Enter a battle (WIN first, then FLEE)")
        showCandidate()
      end
    else
      stateFrames = 0
    end

  elseif state == "ready" then
    -- Detect battle start
    if prevInBattle == 0 and inBattle == 1 then
      battleNum = battleNum + 1
      console:log(string.format("\n[SCAN] === BATTLE #%d START ===", battleNum))
      console:log("[SCAN] Taking baseline snapshot...")
      baselineSnap = takeSnapshot()
      console:log("[SCAN] Baseline taken. Fight the battle!")
      showCandidate()
      state = "in_battle"
    end

  elseif state == "in_battle" then
    -- Detect battle end — read IMMEDIATELY, same frame
    if prevInBattle == 1 and inBattle == 0 then
      console:log(string.format("[SCAN] === BATTLE #%d END (frame %d) ===", battleNum, frameCount))

      -- Read candidate IMMEDIATELY
      local candVal = readByte(CANDIDATE_WRAM)
      console:log(string.format("[SCAN] Candidate 0x%08X = %s (INSTANT read)", CANDIDATE_ADDR, candVal and tostring(candVal) or "nil"))

      -- Full scan for all bytes that changed from 0 to small non-zero value
      local changed = findChangedFromZero()
      console:log(string.format("[SCAN] Found %d bytes that changed from 0 to non-zero (1-10)", #changed))

      -- Group by value
      local byVal = {}
      for _, c in ipairs(changed) do
        if not byVal[c.val] then byVal[c.val] = {} end
        table.insert(byVal[c.val], c)
      end

      for val = 1, 10 do
        if byVal[val] and #byVal[val] > 0 then
          local count = #byVal[val]
          if count <= 20 then
            console:log(string.format("\n  Value = %d (%d addresses):", val, count))
            for _, c in ipairs(byVal[val]) do
              local marker = c.addr == CANDIDATE_ADDR and " ← PREV CANDIDATE" or ""
              console:log(string.format("    0x%08X%s", c.addr, marker))
            end
          else
            console:log(string.format("\n  Value = %d (%d addresses — too many, showing first 10):", val, count))
            for i = 1, 10 do
              local c = byVal[val][i]
              local marker = c.addr == CANDIDATE_ADDR and " ← PREV CANDIDATE" or ""
              console:log(string.format("    0x%08X%s", c.addr, marker))
            end
          end
        end
      end

      -- Store result
      allResults[battleNum] = {changed = changed, candidateVal = candVal}

      -- Cross-reference if we have 2+ battles
      if battleNum >= 2 then
        console:log("\n========================================")
        console:log("=== CROSS-REFERENCE ===")
        console:log("========================================")

        -- Find addresses present in ALL battles with consistent small values
        local addrVals = {}  -- addr -> {battle1_val, battle2_val, ...}
        for bn, res in pairs(allResults) do
          for _, c in ipairs(res.changed) do
            if not addrVals[c.addr] then addrVals[c.addr] = {} end
            addrVals[c.addr][bn] = c.val
          end
        end

        console:log("\nAddresses present in ALL battles with different values:")
        local found = false
        for addr, vals in pairs(addrVals) do
          -- Must be in all battles
          local inAll = true
          for i = 1, battleNum do
            if not vals[i] then inAll = false; break end
          end
          if inAll then
            -- Values must differ (win=1 vs flee=4 etc.)
            local allSame = true
            for i = 2, battleNum do
              if vals[i] ~= vals[1] then allSame = false; break end
            end
            if not allSame then
              local valStr = ""
              for i = 1, battleNum do
                valStr = valStr .. string.format("battle%d=%d ", i, vals[i])
              end
              console:log(string.format("  ★ 0x%08X: %s", addr, valStr))
              found = true
            end
          end
        end

        if not found then
          console:log("  (none found — try more battles)")
          console:log("\nAddresses in ALL battles (even same value):")
          for addr, vals in pairs(addrVals) do
            local inAll = true
            for i = 1, battleNum do
              if not vals[i] then inAll = false; break end
            end
            if inAll then
              local valStr = ""
              for i = 1, battleNum do
                valStr = valStr .. string.format("b%d=%d ", i, vals[i])
              end
              console:log(string.format("    0x%08X: %s", addr, valStr))
            end
          end
        end

        console:log("========================================")
      end

      state = "ready"
      console:log("\n[SCAN] Ready for next battle (or stopScan() to finish)")
    end
  end

  prevInBattle = inBattle
end

function stopScan()
  if cbId then
    callbacks:remove(cbId)
    cbId = nil
    console:log("[SCAN] Stopped.")
  end
end

_G.stopScan = stopScan

-- Start
console:log("========================================")
console:log("gBattleOutcome Finder v2 (instant capture)")
console:log("========================================")
console:log("")
console:log("Verifying previous candidate: 0x020265CA")
console:log("")
console:log("INSTRUCTIONS:")
console:log("  1. Wait 3 seconds outside")
console:log("  2. Battle #1: WIN")
console:log("  3. Battle #2: FLEE")
console:log("  4. Cross-reference shows gBattleOutcome")
console:log("")
console:log("pokeemerald values: 1=won, 2=lost, 4=fled")
console:log("")

cbId = callbacks:add("frame", tick)
