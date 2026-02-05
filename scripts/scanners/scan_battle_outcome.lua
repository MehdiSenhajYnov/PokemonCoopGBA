--[[
  gBattleOutcome Scanner - More reliable method

  Uses delta prediction from vanilla Emerald + live validation.

  gBattleOutcome values:
  - 0 = battle ongoing
  - 1 = player won
  - 2 = player lost
  - 7 = player fled

  USAGE:
  1. Load this script
  2. Follow the prompts (enter battle, win, lose, flee)
]]

local EWRAM_START = 0x02000000

-- Predict using multiple methods
local function getPredictions()
  local predictions = {}

  -- Method 1: Delta from gBattleTypeFlags
  -- Vanilla: gBattleOutcome is often near gBattleTypeFlags
  -- Our gBattleTypeFlags = 0x020090E8
  -- Try offsets commonly seen in Emerald-based hacks
  table.insert(predictions, {addr = 0x020090E8 + 0x04, name = "gBattleTypeFlags+4"})
  table.insert(predictions, {addr = 0x020090E8 + 0x08, name = "gBattleTypeFlags+8"})
  table.insert(predictions, {addr = 0x020090E8 - 0x04, name = "gBattleTypeFlags-4"})
  table.insert(predictions, {addr = 0x020090E8 - 0x08, name = "gBattleTypeFlags-8"})

  -- Method 2: Delta from gBattleControllerExecFlags
  -- Our gBattleControllerExecFlags = 0x020239FC
  -- In vanilla, gBattleOutcome is typically before this
  table.insert(predictions, {addr = 0x020239FC - 0x10, name = "ExecFlags-0x10"})
  table.insert(predictions, {addr = 0x020239FC - 0x14, name = "ExecFlags-0x14"})
  table.insert(predictions, {addr = 0x020239FC - 0x18, name = "ExecFlags-0x18"})
  table.insert(predictions, {addr = 0x020239FC - 0x20, name = "ExecFlags-0x20"})

  -- Method 3: Near gMain.inBattle (0x020206AE, found via find_inbattle_offset.lua)
  -- gBattleOutcome might be in the same struct area
  table.insert(predictions, {addr = 0x020206AE + 0x01, name = "inBattle+1"})
  table.insert(predictions, {addr = 0x020206AE + 0x02, name = "inBattle+2"})
  table.insert(predictions, {addr = 0x020206AE + 0x04, name = "inBattle+4"})
  table.insert(predictions, {addr = 0x020206AE - 0x01, name = "inBattle-1"})
  table.insert(predictions, {addr = 0x020206AE - 0x02, name = "inBattle-2"})

  -- Method 4: Common addresses in Emerald hacks
  -- Vanilla gBattleOutcome = around 0x0202xxxx
  table.insert(predictions, {addr = 0x02023A00, name = "common area 1"})
  table.insert(predictions, {addr = 0x02023A04, name = "common area 2"})
  table.insert(predictions, {addr = 0x02023A08, name = "common area 3"})

  return predictions
end

local function readAddr(addr)
  local offset = addr - EWRAM_START
  if offset < 0 or offset >= 0x40000 then return nil end
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  if ok then return val end
  return nil
end

-- State
local predictions = getPredictions()
local state = "monitoring"
local gMainInBattle = 0x020206AE  -- FOUND: gMain+0x66 via find_inbattle_offset.lua

local function isInBattle()
  local val = readAddr(gMainInBattle)
  return val == 1
end

local prevInBattle = false
local lastBattleValues = {}
local afterBattleValues = {}

local function tick()
  local inBattle = isInBattle()

  -- Detect battle end
  if prevInBattle and not inBattle then
    console:log("")
    console:log("=== BATTLE ENDED - Checking candidates ===")

    -- Read all predictions now (after battle)
    afterBattleValues = {}
    for _, p in ipairs(predictions) do
      afterBattleValues[p.addr] = readAddr(p.addr)
    end

    -- Compare with during-battle values
    console:log("")
    console:log("Candidates where value changed from 0 to 1/2/7:")
    local found = false
    for _, p in ipairs(predictions) do
      local during = lastBattleValues[p.addr]
      local after = afterBattleValues[p.addr]

      if during == 0 and (after == 1 or after == 2 or after == 7) then
        console:log(string.format("  0x%08X = %d  (%s) <-- LIKELY!", p.addr, after, p.name))
        found = true
      end
    end

    if not found then
      console:log("  No candidates matched. Showing all values:")
      for _, p in ipairs(predictions) do
        local during = lastBattleValues[p.addr] or -1
        local after = afterBattleValues[p.addr] or -1
        console:log(string.format("  0x%08X: %d -> %d  (%s)", p.addr, during, after, p.name))
      end
    end

    console:log("")
    console:log("If you WON, the correct address shows: 0 -> 1")
    console:log("If you LOST, it shows: 0 -> 2")
    console:log("If you FLED, it shows: 0 -> 7")
  end

  -- During battle, record values
  if inBattle then
    for _, p in ipairs(predictions) do
      lastBattleValues[p.addr] = readAddr(p.addr)
    end
  end

  prevInBattle = inBattle
end

-- Also allow manual check
function checkNow()
  console:log("=== Current values at all predicted addresses ===")
  for _, p in ipairs(predictions) do
    local val = readAddr(p.addr)
    console:log(string.format("  0x%08X = %d  (%s)", p.addr, val or -1, p.name))
  end
end

-- Allow testing a specific address
function testAddr(addr)
  local val = readAddr(addr)
  console:log(string.format("0x%08X = %d", addr, val or -1))
end

_G.checkNow = checkNow
_G.testAddr = testAddr

console:log("========================================")
console:log("gBattleOutcome Scanner")
console:log("========================================")
console:log("")
console:log("Monitoring battle state...")
console:log("1. Enter a battle")
console:log("2. WIN, LOSE, or FLEE")
console:log("3. Results will show automatically")
console:log("")
console:log("Commands:")
console:log("  checkNow()      - Show all predicted addresses now")
console:log("  testAddr(0x..)  - Test a specific address")
console:log("")

cbId = callbacks:add("frame", tick)
