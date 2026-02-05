--[[
  gBattleOutcome Finder - Two-round approach

  Round 1: WIN a battle → find bytes that become 1
  Round 2: FLEE a battle → find bytes that become 7
  Intersection = gBattleOutcome

  USAGE:
  1. Load this script OUTSIDE of battle
  2. Wait 3 seconds (calibration)
  3. Enter a battle and WIN it
  4. Go back outside, wait a moment
  5. Enter another battle and FLEE
  6. The script finds gBattleOutcome automatically
]]

local EWRAM_START = 0x02000000
local EWRAM_SIZE = 0x40000

-- Known addresses
local INBATTLE_ADDR = 0x020206AE
local INBATTLE_WRAM = INBATTLE_ADDR - EWRAM_START

local function readInBattle()
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, INBATTLE_WRAM)
  return ok and val == 1
end

local function readByte(offset)
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  if ok then return val end
  return nil
end

-- State machine
local state = "calibrating"
local frameCount = 0
local stateFrames = 0

-- Round tracking
local round = 1  -- 1 = WIN, 2 = FLEE
local baselineZeros = nil  -- offsets that are 0 before battle
local winCandidates = nil  -- offsets that are 1 after WIN
local fleeCandidates = nil -- offsets that are 7 after FLEE

-- Scan for all bytes that equal target value, from a candidate set
local function scanFromSet(candidates, target)
  local matches = {}
  for _, offset in ipairs(candidates) do
    local val = readByte(offset)
    if val == target then
      matches[#matches + 1] = offset
    end
  end
  return matches
end

-- Scan all EWRAM for bytes = 0
local function scanAllZeros()
  local zeros = {}
  for offset = 0, EWRAM_SIZE - 1 do
    local val = readByte(offset)
    if val == 0 then
      zeros[#zeros + 1] = offset
    end
  end
  return zeros
end

local function tick()
  frameCount = frameCount + 1
  if frameCount % 5 ~= 0 then return end

  local inBattle = readInBattle()

  if state == "calibrating" then
    if not inBattle then
      stateFrames = stateFrames + 1
      if stateFrames == 1 then
        console:log("[SCAN] Calibrating... stay outside")
      end
      if stateFrames >= 36 then  -- ~3 sec
        console:log("[SCAN] Scanning baseline zeros...")
        baselineZeros = scanAllZeros()
        console:log(string.format("[SCAN] Baseline: %d zero-bytes", #baselineZeros))
        console:log("")
        console:log("[SCAN] === ROUND 1: Enter a battle and WIN ===")
        state = "waiting_battle"
        stateFrames = 0
      end
    else
      stateFrames = 0
    end

  elseif state == "waiting_battle" then
    if inBattle then
      console:log(string.format("[SCAN] Battle detected! (round %d)", round))
      state = "in_battle"
      stateFrames = 0
    end

  elseif state == "in_battle" then
    if not inBattle then
      console:log("[SCAN] Battle ended! Checking values...")
      stateFrames = 0
      state = "checking"
    end

  elseif state == "checking" then
    -- Small delay for values to settle
    stateFrames = stateFrames + 1
    if stateFrames < 6 then return end

    if round == 1 then
      -- After WIN: find bytes that went from 0 → 1
      winCandidates = scanFromSet(baselineZeros, 1)
      console:log(string.format("[SCAN] Round 1 (WIN): %d candidates with val=1", #winCandidates))

      -- Show top candidates in battle address range
      local filtered = {}
      for _, offset in ipairs(winCandidates) do
        local addr = EWRAM_START + offset
        if addr >= 0x02008000 and addr <= 0x0203FFFF then
          filtered[#filtered + 1] = addr
        end
      end
      console:log(string.format("[SCAN] Filtered to battle range: %d candidates", #filtered))
      if #filtered <= 30 then
        for _, addr in ipairs(filtered) do
          console:log(string.format("  0x%08X = 1", addr))
        end
      end

      round = 2
      console:log("")
      console:log("[SCAN] === ROUND 2: Enter a battle and FLEE ===")
      console:log("[SCAN] (wait a few seconds outside first)")
      state = "waiting_reset"
      stateFrames = 0

    elseif round == 2 then
      -- After FLEE: find bytes that went from 0 → 7
      fleeCandidates = scanFromSet(baselineZeros, 7)
      console:log(string.format("[SCAN] Round 2 (FLEE): %d candidates with val=7", #fleeCandidates))

      -- Cross-reference: find offsets in BOTH win (=1) and flee (=7)
      local winSet = {}
      for _, offset in ipairs(winCandidates) do
        winSet[offset] = true
      end

      console:log("")
      console:log("========================================")
      console:log("=== CROSS-REFERENCE RESULTS ===")
      console:log("========================================")
      console:log("")

      local matches = {}
      for _, offset in ipairs(fleeCandidates) do
        if winSet[offset] then
          matches[#matches + 1] = EWRAM_START + offset
        end
      end

      if #matches > 0 then
        console:log(string.format("Addresses that were 1 after WIN and 7 after FLEE: %d", #matches))
        for _, addr in ipairs(matches) do
          console:log(string.format("  ★ 0x%08X  — LIKELY gBattleOutcome", addr))
        end
      else
        console:log("No perfect match (1 after WIN + 7 after FLEE)")
        console:log("")
        -- Fallback: show flee candidates that are in battle range
        console:log("Addresses with val=7 after FLEE (in battle range):")
        for _, offset in ipairs(fleeCandidates) do
          local addr = EWRAM_START + offset
          if addr >= 0x02008000 and addr <= 0x0203FFFF then
            console:log(string.format("  0x%08X = 7", addr))
          end
        end
        console:log("")
        -- Also check: what about val=2 after FLEE? (some games use 2 for flee)
        local flee2 = scanFromSet(baselineZeros, 2)
        local matches2 = {}
        for _, offset in ipairs(flee2) do
          if winSet[offset] then
            matches2[#matches2 + 1] = EWRAM_START + offset
          end
        end
        if #matches2 > 0 then
          console:log("Addresses that were 1 after WIN and 2 after FLEE:")
          for _, addr in ipairs(matches2) do
            console:log(string.format("  ★ 0x%08X  — might be gBattleOutcome (flee=2)", addr))
          end
        end
      end

      console:log("")
      console:log("========================================")
      console:log("Copy the address to config/run_and_bun.lua!")
      console:log("========================================")

      state = "done"
    end

  elseif state == "waiting_reset" then
    -- Wait outside for baseline to reset
    if not inBattle then
      stateFrames = stateFrames + 1
      if stateFrames >= 24 then  -- ~2 sec outside
        state = "waiting_battle"
        stateFrames = 0
      end
    else
      stateFrames = 0
    end

  elseif state == "done" then
    if cbId then
      callbacks:remove(cbId)
      cbId = nil
    end
  end
end

-- Manual helpers
function peekAddr(addr)
  local offset = addr - EWRAM_START
  local val = readByte(offset)
  console:log(string.format("0x%08X = %s", addr, val and tostring(val) or "nil"))
end

_G.peekAddr = peekAddr

-- Start
console:log("========================================")
console:log("gBattleOutcome Finder (2-round)")
console:log("========================================")
console:log("")
console:log("INSTRUCTIONS:")
console:log("  1. Stay outside for 3 seconds")
console:log("  2. Enter battle and WIN")
console:log("  3. Wait outside a moment")
console:log("  4. Enter battle and FLEE")
console:log("  5. Results appear automatically!")
console:log("")
console:log("Commands:")
console:log("  peekAddr(0x02XXXXXX)  - Read a specific address")
console:log("")

cbId = callbacks:add("frame", tick)
