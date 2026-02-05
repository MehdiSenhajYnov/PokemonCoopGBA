--[[
  Battle Callback Scanner

  Auto-detects CB2_InitBattle, CB2_ReturnToField (and potentially CB2_WhiteOut)
  by monitoring gMain.callback2 transitions correlated with gMain.inBattle changes.

  Uses FLAG-BASED watchpoint approach (same pattern as hal.lua:606-636):
  - Watchpoint callback only sets a flag (no memory access — crash risk)
  - Frame callback checks the flag and reads memory safely

  USAGE:
  1. Load this script in mGBA (Tools > Scripting > Load Script)
  2. Enter a wild battle or trainer battle
  3. Win or flee the battle
  4. The script auto-detects the callback addresses

  KNOWN ADDRESSES:
    gMain.callback2 = 0x0202064C
    gMain.inBattle  = 0x0202067F (derived: callback2Addr - 4 + 0x37)
    CB2_LoadMap     = 0x08007441
    CB2_Overworld   = 0x080A89A5
]]

local EWRAM_START = 0x02000000

-- Known addresses from config
local CALLBACK2_ADDR  = 0x0202064C
local GMAIN_BASE      = CALLBACK2_ADDR - 0x04  -- 0x02020648
local INBATTLE_ADDR   = 0x020206AE             -- gMain+0x66, found via find_inbattle_offset.lua
local CB2_LOADMAP     = 0x08007441
local CB2_OVERWORLD   = 0x080A89A5

-- WRAM offsets
local CB2_WRAM_OFFSET      = CALLBACK2_ADDR - EWRAM_START  -- 0x2064C
local INBATTLE_WRAM_OFFSET = INBATTLE_ADDR - EWRAM_START   -- 0x206AE

-- State
local watchpointFired = false
local watchpointId = nil
local frameCallbackId = nil
local prevInBattle = nil
local prevCallback2 = nil
local frameCount = 0

-- Results
local results = {
  CB2_InitBattle = nil,
  CB2_ReturnToField = nil,
  CB2_WhiteOut = nil,
}

-- All unique callback2 values observed
local allCallbacks = {}

-- Log buffer for detailed output
local logBuf = console:createBuffer("Battle Callbacks")

local function readCallback2()
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, CB2_WRAM_OFFSET)
  if ok then return val end
  return nil
end

local function readInBattle()
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, INBATTLE_WRAM_OFFSET)
  if ok then return val end
  return nil
end

local function formatAddr(addr)
  if addr then
    return string.format("0x%08X", addr)
  end
  return "nil"
end

local function isROMAddr(addr)
  return addr and addr >= 0x08000000 and addr < 0x0A000000
end

local function labelFor(addr)
  if addr == CB2_LOADMAP then return "CB2_LoadMap (known)" end
  if addr == CB2_OVERWORLD then return "CB2_Overworld (known)" end
  if results.CB2_InitBattle and addr == results.CB2_InitBattle then return "CB2_InitBattle" end
  if results.CB2_ReturnToField and addr == results.CB2_ReturnToField then return "CB2_ReturnToField" end
  return ""
end

local function updateDisplay()
  logBuf:clear()
  logBuf:print("=== Battle Callback Scanner ===\n\n")
  logBuf:print(string.format("CB2_InitBattle:     %s\n", formatAddr(results.CB2_InitBattle)))
  logBuf:print(string.format("CB2_ReturnToField:  %s\n", formatAddr(results.CB2_ReturnToField)))
  logBuf:print(string.format("CB2_WhiteOut:       %s\n", formatAddr(results.CB2_WhiteOut)))
  logBuf:print("\n--- All unique callback2 values seen ---\n")

  local sorted = {}
  for addr, info in pairs(allCallbacks) do
    sorted[#sorted + 1] = { addr = addr, count = info.count, label = info.label }
  end
  table.sort(sorted, function(a, b) return a.addr < b.addr end)

  for _, entry in ipairs(sorted) do
    local lbl = entry.label ~= "" and (" ← " .. entry.label) or ""
    logBuf:print(string.format("  %s  (seen %dx)%s\n", formatAddr(entry.addr), entry.count, lbl))
  end
end

local function recordCallback(addr)
  if not addr then return end
  if not allCallbacks[addr] then
    allCallbacks[addr] = { count = 0, label = labelFor(addr) }
  end
  allCallbacks[addr].count = allCallbacks[addr].count + 1
end

local function tick()
  frameCount = frameCount + 1

  local cb2 = readCallback2()
  local inBattle = readInBattle()

  if cb2 == nil or inBattle == nil then return end

  -- Track all callback2 values
  if cb2 ~= prevCallback2 then
    recordCallback(cb2)

    local lbl = labelFor(cb2)
    if lbl == "" then lbl = "UNKNOWN" end
    console:log(string.format("[SCAN] callback2 changed: %s → %s (%s) | inBattle=%d",
      formatAddr(prevCallback2), formatAddr(cb2), lbl, inBattle))
  end

  -- Detect inBattle transitions
  if prevInBattle ~= nil and inBattle ~= prevInBattle then
    if prevInBattle == 0 and inBattle == 1 then
      -- Entering battle
      console:log("")
      console:log(string.format("[SCAN] ★ BATTLE START detected! inBattle: 0 → 1"))
      console:log(string.format("[SCAN] ★ Current callback2: %s", formatAddr(cb2)))

      if isROMAddr(cb2) and cb2 ~= CB2_LOADMAP and cb2 ~= CB2_OVERWORLD then
        results.CB2_InitBattle = cb2
        allCallbacks[cb2] = allCallbacks[cb2] or { count = 0, label = "" }
        allCallbacks[cb2].label = "CB2_InitBattle"
        console:log(string.format("[SCAN] ★★★ CB2_InitBattle FOUND: %s ★★★", formatAddr(cb2)))
      else
        console:log(string.format("[SCAN] callback2 is %s — checking next frame...", labelFor(cb2)))
      end
      console:log("")

    elseif prevInBattle == 1 and inBattle == 0 then
      -- Exiting battle
      console:log("")
      console:log(string.format("[SCAN] ★ BATTLE END detected! inBattle: 1 → 0"))
      console:log(string.format("[SCAN] ★ Current callback2: %s", formatAddr(cb2)))

      if isROMAddr(cb2) and cb2 ~= CB2_LOADMAP and cb2 ~= CB2_OVERWORLD then
        if not results.CB2_ReturnToField then
          results.CB2_ReturnToField = cb2
          allCallbacks[cb2] = allCallbacks[cb2] or { count = 0, label = "" }
          allCallbacks[cb2].label = "CB2_ReturnToField"
          console:log(string.format("[SCAN] ★★★ CB2_ReturnToField FOUND: %s ★★★", formatAddr(cb2)))
        end
      end
      console:log("")
    end
  end

  -- Also check if watchpoint fired (callback2 write detected)
  if watchpointFired then
    watchpointFired = false
    -- The watchpoint just confirms callback2 changed — we already handle it above
  end

  prevCallback2 = cb2
  prevInBattle = inBattle

  -- Update display buffer every 30 frames
  if frameCount % 30 == 0 then
    updateDisplay()
  end
end

-- Setup watchpoint on callback2 (flag-based, same as hal.lua)
local function setupWatchpoint()
  local ok, wpId = pcall(function()
    return emu:setWatchpoint(function()
      -- MINIMAL work: just set flag. Memory access in watchpoint = crash risk.
      watchpointFired = true
    end, CALLBACK2_ADDR, C.WATCHPOINT_TYPE.WRITE_CHANGE)
  end)

  if ok and wpId then
    watchpointId = wpId
    console:log(string.format("[SCAN] Watchpoint set on callback2 (0x%08X), id=%d", CALLBACK2_ADDR, wpId))
    return true
  else
    console:log("[SCAN] WARNING: Failed to set watchpoint (requires mGBA 0.11+)")
    console:log("[SCAN] Scanner will still work via polling (slightly less precise)")
    return false
  end
end

-- Cleanup function
function stopScan()
  if watchpointId then
    pcall(emu.clearBreakpoint, emu, watchpointId)
    watchpointId = nil
    console:log("[SCAN] Watchpoint removed")
  end
  if frameCallbackId then
    callbacks:remove(frameCallbackId)
    frameCallbackId = nil
    console:log("[SCAN] Frame callback removed")
  end
  console:log("[SCAN] Scanner stopped")

  -- Print final results
  console:log("")
  console:log("========================================")
  console:log("=== FINAL RESULTS ===")
  console:log("========================================")
  console:log(string.format("CB2_InitBattle     = %s", formatAddr(results.CB2_InitBattle)))
  console:log(string.format("CB2_ReturnToField  = %s", formatAddr(results.CB2_ReturnToField)))
  console:log(string.format("CB2_WhiteOut       = %s", formatAddr(results.CB2_WhiteOut)))
  console:log("========================================")
  console:log("")
  console:log("Copy these to config/run_and_bun.lua battle section!")
end

_G.stopScan = stopScan
_G.scanResults = results

-- Start
console:log("========================================")
console:log("Battle Callback Scanner")
console:log("========================================")
console:log("")
console:log(string.format("Monitoring gMain.callback2 at 0x%08X", CALLBACK2_ADDR))
console:log(string.format("Monitoring gMain.inBattle  at 0x%08X", INBATTLE_ADDR))
console:log("")
console:log("INSTRUCTIONS:")
console:log("  1. Enter a wild or trainer battle")
console:log("  2. Win or flee the battle")
console:log("  3. Addresses are detected automatically")
console:log("")
console:log("  For WhiteOut: lose a battle (all Pokemon faint)")
console:log("")
console:log("Commands:")
console:log("  stopScan()     - Stop scanner and show results")
console:log("  scanResults    - View current results table")
console:log("")

setupWatchpoint()
frameCallbackId = callbacks:add("frame", tick)
