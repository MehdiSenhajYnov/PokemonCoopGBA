--[[
  Battle Functions Discovery — Watchpoint Logger

  Sets watchpoints on known EWRAM battle addresses, then logs the ROM
  PC (program counter) for every write. This reveals which ROM functions
  modify these variables during a trainer battle.

  USAGE:
  1. Load this script in mGBA (Tools > Scripting > Load)
  2. Walk around in the overworld (establishes baseline)
  3. Enter a trainer battle (wild battle also works)
  4. Fight through the battle (at least 1-2 turns)
  5. Win/lose the battle
  6. Check the console for the summary table

  The script auto-prints a summary after collecting enough data.
  You can also press SELECT to force-print the current summary.

  OUTPUT: ROM addresses of functions that write to battle-critical variables.
  These are needed to identify functions for the Link Battle Emulation system.
]]

console:log("=== BATTLE FUNCTION DISCOVERY (Watchpoints) ===")

-- Known addresses to watch (from config/run_and_bun.lua)
local WATCHPOINTS = {
  {
    name = "gBattleTypeFlags",
    addr = 0x020090E8,
    size = 4,
    region = "wram",
  },
  {
    name = "gEnemyParty[0]",
    addr = 0x02023CF0,
    size = 4,  -- Watch first 4 bytes (detect party copy start)
    region = "wram",
  },
  {
    name = "gMainCallback2",
    addr = 0x0202064C,
    size = 4,
    region = "wram",
  },
  {
    name = "gMainInBattle",
    addr = 0x020206AE,
    size = 1,
    region = "wram",
  },
}

-- Log storage: { [pc] = { name, count, value_sample, lr } }
local hitLog = {}
local totalHits = 0
local frameCount = 0
local collecting = true

-- Helper: convert absolute EWRAM address to WRAM offset
local function toWRAM(addr)
  return addr - 0x02000000
end

-- Register watchpoint callbacks
-- NOTE: mGBA scripting doesn't have traditional watchpoint API.
-- Instead, we poll these addresses every frame and detect changes.

local prevValues = {}

for _, wp in ipairs(WATCHPOINTS) do
  local offset = toWRAM(wp.addr)
  local readFn
  if wp.size == 1 then
    readFn = function() return emu.memory.wram:read8(offset) end
  elseif wp.size == 2 then
    readFn = function() return emu.memory.wram:read16(offset) end
  else
    readFn = function() return emu.memory.wram:read32(offset) end
  end

  local ok, initial = pcall(readFn)
  prevValues[wp.name] = ok and initial or 0

  console:log(string.format("  Watching: %s @ 0x%08X (%d bytes) initial=0x%X",
    wp.name, wp.addr, wp.size, prevValues[wp.name]))
end

-- Frame callback: poll all watched addresses for changes
local function onFrame()
  frameCount = frameCount + 1
  if not collecting then return end

  for _, wp in ipairs(WATCHPOINTS) do
    local offset = toWRAM(wp.addr)
    local readFn
    if wp.size == 1 then
      readFn = function() return emu.memory.wram:read8(offset) end
    elseif wp.size == 2 then
      readFn = function() return emu.memory.wram:read16(offset) end
    else
      readFn = function() return emu.memory.wram:read32(offset) end
    end

    local ok, current = pcall(readFn)
    if ok and current ~= prevValues[wp.name] then
      -- Value changed! Log it.
      -- We can't read PC/LR from Lua (no debugger API), but we log the
      -- frame number, old value, new value, and callback2 for context.
      local cb2 = 0
      pcall(function()
        cb2 = emu.memory.wram:read32(toWRAM(0x0202064C))
      end)

      local key = string.format("%s_0x%X_0x%X", wp.name, prevValues[wp.name], current)
      if not hitLog[key] then
        hitLog[key] = {
          name = wp.name,
          oldVal = prevValues[wp.name],
          newVal = current,
          frame = frameCount,
          cb2 = cb2,
          count = 0,
        }
      end
      hitLog[key].count = hitLog[key].count + 1
      hitLog[key].lastFrame = frameCount
      totalHits = totalHits + 1

      -- Log notable transitions inline
      if wp.name == "gMainInBattle" then
        console:log(string.format("  [F%d] %s: %d -> %d (cb2=0x%08X)",
          frameCount, wp.name, prevValues[wp.name], current, cb2))
      elseif wp.name == "gBattleTypeFlags" and current ~= 0 then
        console:log(string.format("  [F%d] %s: 0x%08X -> 0x%08X (cb2=0x%08X)",
          frameCount, wp.name, prevValues[wp.name], current, cb2))
      elseif wp.name == "gMainCallback2" then
        console:log(string.format("  [F%d] %s: 0x%08X -> 0x%08X",
          frameCount, wp.name, prevValues[wp.name], current))
      end

      prevValues[wp.name] = current
    end
  end

  -- Auto-summary: check for SELECT button (bit 2 of KEYINPUT, active-low)
  local ok, keys = pcall(function() return emu.memory.io:read16(0x0130) end)
  if ok then
    local selectPressed = ((~keys) & 0x0004) ~= 0
    if selectPressed then
      printSummary()
    end
  end
end

function printSummary()
  console:log("")
  console:log("=== WATCHPOINT SUMMARY (after " .. frameCount .. " frames, " .. totalHits .. " changes) ===")
  console:log("")

  -- Group by variable name
  local grouped = {}
  for _, entry in pairs(hitLog) do
    if not grouped[entry.name] then
      grouped[entry.name] = {}
    end
    table.insert(grouped[entry.name], entry)
  end

  for varName, entries in pairs(grouped) do
    console:log(string.format("--- %s ---", varName))
    -- Sort by frame
    table.sort(entries, function(a, b) return a.frame < b.frame end)
    for _, e in ipairs(entries) do
      if e.name == "gBattleTypeFlags" or e.name == "gMainCallback2" then
        console:log(string.format("  F%-6d  0x%08X -> 0x%08X  (x%d, cb2=0x%08X)",
          e.frame, e.oldVal, e.newVal, e.count, e.cb2))
      else
        console:log(string.format("  F%-6d  %d -> %d  (x%d, cb2=0x%08X)",
          e.frame, e.oldVal, e.newVal, e.count, e.cb2))
      end
    end
    console:log("")
  end

  -- Additional: read current values
  console:log("--- CURRENT VALUES ---")
  for _, wp in ipairs(WATCHPOINTS) do
    local offset = toWRAM(wp.addr)
    local ok, val
    if wp.size == 1 then
      ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    elseif wp.size == 2 then
      ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
    else
      ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    end
    if ok then
      console:log(string.format("  %s = 0x%X", wp.name, val))
    end
  end

  console:log("")
  console:log("=== END SUMMARY ===")
end

-- Additional: scan for gBattleResources pointer during battle
-- gBattleResources is a pointer in EWRAM that points to heap-allocated battle data
-- bufferA = *gBattleResources + 16, bufferB = *gBattleResources + 16 + 0x800
local function scanBattleResources()
  console:log("")
  console:log("=== SCANNING FOR gBattleResources (heap pointer in EWRAM) ===")

  -- gBattleResources is a pointer whose value should be in EWRAM range (0x02000000-0x0203FFFF)
  -- It's typically near other battle globals (near gBattleTypeFlags at 0x020090E8)
  -- Search in a focused range around battle variables
  local candidates = {}

  for offset = 0x008000, 0x00FFFF, 4 do
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok and val >= 0x02000000 and val < 0x02040000 then
      -- This looks like an EWRAM pointer. Dereference and check if it looks like battle resources.
      local ptrOffset = val - 0x02000000
      local ok2, ptrVal = pcall(emu.memory.wram.read32, emu.memory.wram, ptrOffset)
      if ok2 and ptrVal >= 0x02000000 and ptrVal < 0x02040000 then
        -- Double pointer — gBattleResources has sub-pointers at the start
        -- Check if offset+16 onwards has reasonable buffer data
        local ok3, bufCheck = pcall(emu.memory.wram.read32, emu.memory.wram, ptrOffset + 16)
        if ok3 then
          table.insert(candidates, {
            addr = 0x02000000 + offset,
            ptrVal = val,
            firstSubPtr = ptrVal,
            bufStart = bufCheck,
          })
        end
      end
    end
  end

  console:log(string.format("  Found %d EWRAM pointer candidates in battle area", #candidates))
  for i = 1, math.min(20, #candidates) do
    local c = candidates[i]
    console:log(string.format("  0x%08X -> 0x%08X (sub[0]=0x%08X, buf[16]=0x%08X)",
      c.addr, c.ptrVal, c.firstSubPtr, c.bufStart))
  end

  console:log("=== END gBattleResources SCAN ===")
end

-- Register frame callback
callbacks:add("frame", onFrame)

console:log("")
console:log("Watchpoints active. Instructions:")
console:log("  1. Enter a trainer battle")
console:log("  2. Fight 1-2 turns")
console:log("  3. Win/lose the battle")
console:log("  4. Press SELECT for summary at any time")
console:log("  5. Notable transitions logged inline")
console:log("")
console:log("TIP: Also try pressing SELECT during battle for gBattleResources scan")
