--[[
  Find gMain.inBattle offset in Run & Bun

  Run & Bun has modified the gMain struct, so inBattle is NOT at the
  vanilla offset +0x37. This script monitors all bytes in a wide range
  around gMain base to find which one changes between 0 and non-zero
  when entering/exiting battle.

  USAGE:
  1. Load this script OUTSIDE of battle
  2. Wait 3 seconds (calibration)
  3. Enter a wild or trainer battle
  4. Win or flee the battle
  5. The script shows which bytes changed

  gMain base = 0x02020648 (derived from callback2Addr 0x0202064C - 4)
]]

local EWRAM_START = 0x02000000
local GMAIN_BASE = 0x02020648
local SCAN_SIZE = 0x100  -- scan 256 bytes from gMain base (generous range)

-- Snapshot storage
local outsideSnapshot = {}
local battleSnapshot = {}

-- State machine
local state = "calibrating"
local frameCount = 0
local calibrateFrames = 0
local battleDetected = false

-- We don't know where inBattle is, so detect battle via callback2
-- CB2_Overworld = 0x080A89A5 means we're in overworld
-- Any other callback2 after seeing overworld transition = potential battle
local CB2_OVERWORLD = 0x080A89A5
local CB2_LOADMAP   = 0x08007441
local CB2_WRAM_OFFSET = 0x0202064C - EWRAM_START

local prevCb2 = nil
local wasOverworld = false
local battleConfirmed = false
local returnedToOverworld = false

local function readByte(addr)
  local offset = addr - EWRAM_START
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  if ok then return val end
  return nil
end

local function readCb2()
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, CB2_WRAM_OFFSET)
  if ok then return val end
  return nil
end

local function takeSnapshot()
  local snap = {}
  for i = 0, SCAN_SIZE - 1 do
    snap[i] = readByte(GMAIN_BASE + i) or -1
  end
  return snap
end

local function compareSnapshots(before, during, after)
  console:log("")
  console:log("========================================")
  console:log("=== COMPARISON RESULTS ===")
  console:log("========================================")
  console:log("")

  -- Find bytes that went from 0 outside → non-zero in battle
  console:log("--- Bytes: 0 outside → non-zero in battle ---")
  local candidates = {}
  for i = 0, SCAN_SIZE - 1 do
    if before[i] == 0 and during[i] ~= 0 then
      local addr = GMAIN_BASE + i
      table.insert(candidates, {offset = i, addr = addr, outside = before[i], battle = during[i]})
      console:log(string.format("  +0x%02X (0x%08X): %d → %d", i, addr, before[i], during[i]))
    end
  end

  if #candidates == 0 then
    console:log("  (none found)")
  end

  -- Find bytes that went from non-zero in battle → 0 after
  if after then
    console:log("")
    console:log("--- Bytes: non-zero in battle → 0 after battle ---")
    local returnCandidates = {}
    for i = 0, SCAN_SIZE - 1 do
      if during[i] ~= 0 and after[i] == 0 and during[i] ~= before[i] then
        local addr = GMAIN_BASE + i
        table.insert(returnCandidates, {offset = i, addr = addr, battle = during[i], after = after[i]})
        console:log(string.format("  +0x%02X (0x%08X): %d → %d", i, addr, during[i], after[i]))
      end
    end

    if #returnCandidates == 0 then
      console:log("  (none found)")
    end

    -- Best candidates: 0 outside, 1 in battle, 0 after battle
    console:log("")
    console:log("=== BEST CANDIDATES (0 → 1 → 0 pattern) ===")
    local best = {}
    for i = 0, SCAN_SIZE - 1 do
      if before[i] == 0 and during[i] == 1 and after[i] == 0 then
        local addr = GMAIN_BASE + i
        table.insert(best, {offset = i, addr = addr})
        console:log(string.format("  ★ +0x%02X (0x%08X)  — LIKELY gMain.inBattle", i, addr))
      end
    end

    if #best == 0 then
      console:log("  (none with exact 0→1→0 pattern)")
      console:log("")
      console:log("=== WIDER CANDIDATES (0 → any → 0 pattern) ===")
      for i = 0, SCAN_SIZE - 1 do
        if before[i] == 0 and during[i] ~= 0 and after[i] == 0 then
          local addr = GMAIN_BASE + i
          console:log(string.format("  +0x%02X (0x%08X): 0 → %d → 0", i, addr, during[i]))
        end
      end
    end
  end

  console:log("")
  console:log("========================================")
  console:log("Copy the best candidate to config/run_and_bun.lua!")
  console:log("========================================")
end

local afterSnapshot = nil

local function tick()
  frameCount = frameCount + 1
  if frameCount % 5 ~= 0 then return end

  local cb2 = readCb2()

  if state == "calibrating" then
    if cb2 == CB2_OVERWORLD then
      calibrateFrames = calibrateFrames + 1
      if calibrateFrames == 1 then
        console:log("[SCAN] In overworld, calibrating...")
      end
      if calibrateFrames >= 36 then  -- ~3 seconds
        outsideSnapshot = takeSnapshot()
        console:log("[SCAN] Outside snapshot taken!")
        console:log("[SCAN] Now ENTER a battle (wild or trainer)")
        state = "waiting_battle"
        wasOverworld = true
      end
    else
      calibrateFrames = 0
      console:log("[SCAN] Not in overworld yet... walk around on the map")
    end

  elseif state == "waiting_battle" then
    -- Detect: we were in overworld, now callback2 changed to something else
    -- (not LoadMap, not Overworld)
    if cb2 ~= CB2_OVERWORLD and cb2 ~= CB2_LOADMAP and cb2 ~= prevCb2 then
      console:log(string.format("[SCAN] callback2 changed to 0x%08X — possible battle!", cb2))
      -- Wait a moment for battle to fully init
      state = "confirming_battle"
      calibrateFrames = 0
    end

  elseif state == "confirming_battle" then
    calibrateFrames = calibrateFrames + 1
    if calibrateFrames >= 24 then  -- wait ~2 seconds for battle to stabilize
      battleSnapshot = takeSnapshot()
      console:log("[SCAN] Battle snapshot taken!")
      console:log(string.format("[SCAN] Current callback2: 0x%08X", cb2 or 0))

      -- Show preliminary comparison
      console:log("")
      console:log("--- Quick preview: bytes that changed ---")
      local count = 0
      for i = 0, SCAN_SIZE - 1 do
        if outsideSnapshot[i] ~= battleSnapshot[i] then
          count = count + 1
          if count <= 30 then
            console:log(string.format("  +0x%02X (0x%08X): %d → %d",
              i, GMAIN_BASE + i, outsideSnapshot[i], battleSnapshot[i]))
          end
        end
      end
      console:log(string.format("  Total changed: %d bytes", count))

      console:log("")
      console:log("[SCAN] Now WIN or FLEE the battle for final comparison")
      state = "in_battle"
    end

  elseif state == "in_battle" then
    if cb2 == CB2_OVERWORLD then
      console:log("[SCAN] Back to overworld! Taking after-battle snapshot...")
      calibrateFrames = 0
      state = "confirming_return"
    end

  elseif state == "confirming_return" then
    calibrateFrames = calibrateFrames + 1
    if calibrateFrames >= 12 then  -- wait ~1 second
      afterSnapshot = takeSnapshot()
      console:log("[SCAN] After-battle snapshot taken!")
      compareSnapshots(outsideSnapshot, battleSnapshot, afterSnapshot)
      state = "done"
    end

  elseif state == "done" then
    if cbId then
      callbacks:remove(cbId)
      cbId = nil
    end
  end

  prevCb2 = cb2
end

-- Manual commands
function dumpRange(from, to)
  from = from or 0
  to = to or SCAN_SIZE - 1
  console:log(string.format("=== gMain bytes +0x%02X to +0x%02X ===", from, to))
  for i = from, to do
    local val = readByte(GMAIN_BASE + i)
    console:log(string.format("  +0x%02X (0x%08X) = %d (0x%02X)",
      i, GMAIN_BASE + i, val or -1, val or 0))
  end
end

function manualCompare()
  if outsideSnapshot and battleSnapshot then
    compareSnapshots(outsideSnapshot, battleSnapshot, afterSnapshot)
  else
    console:log("Need both snapshots first. Follow the instructions.")
  end
end

function snapNow(name)
  local snap = takeSnapshot()
  console:log(string.format("[SNAP] '%s' snapshot taken", name or "manual"))
  return snap
end

_G.dumpRange = dumpRange
_G.manualCompare = manualCompare
_G.snapNow = snapNow

-- Start
console:log("========================================")
console:log("Find gMain.inBattle Offset")
console:log("========================================")
console:log("")
console:log(string.format("Scanning %d bytes from gMain base 0x%08X", SCAN_SIZE, GMAIN_BASE))
console:log("")
console:log("INSTRUCTIONS:")
console:log("  1. Walk around OUTSIDE of battle (3 seconds)")
console:log("  2. Enter a wild or trainer battle")
console:log("  3. Wait 2 seconds in battle")
console:log("  4. Win or flee")
console:log("  5. Results appear automatically!")
console:log("")
console:log("Commands:")
console:log("  dumpRange(0, 0x60)  - Dump raw bytes in range")
console:log("  manualCompare()     - Re-show comparison")
console:log("")

cbId = callbacks:add("frame", tick)
