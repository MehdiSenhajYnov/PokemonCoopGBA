--[[
  diagnose_and_fix_warp.lua

  COMPREHENSIVE warp diagnostic and fix script.
  Combines ROM scanning + natural warp observation + forced warp testing.

  USAGE:
  1. Load this script in mGBA
  2. The script automatically scans ROM for warp functions
  3. Walk through a door (natural warp) — script captures gMain state
  4. Press START to test forced warp using best available method
  5. Press SELECT to try the next method if current one fails

  METHODS TESTED (in order):
  A. SetCB2WarpAndLoadMap (if found in ROM) — calls WarpIntoMap internally
  B. gMain snapshot replay — copies exact gMain state from natural warp
  C. Direct CB2_LoadMap (current approach, for comparison)
]]

local CB2_ADDR = 0x0202064C     -- gMain.callback2 (confirmed)
local GMAIN_BASE = 0x02020648   -- gMain base
local SB1_LOC = 0x02024CC0     -- SaveBlock1->location
local SWARP = 0x020318A8        -- sWarpDestination (CONFIRMED)
local CB2_LOADMAP = 0x08007441
local CB2_OVERWORLD = 0x080A89A5

local DEST_GROUP = 28
local DEST_MAP = 24
local DEST_X = 5
local DEST_Y = 5

local function toOff(addr) return addr - 0x02000000 end

-- ============================================================
-- PHASE 1: ROM SCAN — Find SetCB2WarpAndLoadMap
-- ============================================================
console:log("=== PHASE 1: ROM SCAN ===")

local warpFuncCandidates = {}
local scanEnd = 0x01800000  -- 24MB should cover most ROMs

-- Find literal pool references to CB2_LoadMap
local litRefs = {}
for offset = 0, scanEnd - 4, 4 do
  local ok, val = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
  if ok and val == CB2_LOADMAP then
    table.insert(litRefs, offset)
  end
end
console:log(string.format("Found %d ROM references to CB2_LoadMap", #litRefs))

-- Analyze each reference to find small functions (SetCB2WarpAndLoadMap candidates)
for _, litOffset in ipairs(litRefs) do
  -- Look backwards for PUSH (function start)
  for back = 2, 48, 2 do
    local codeStart = litOffset - back
    if codeStart >= 0 then
      local ok, instr = pcall(emu.memory.cart0.read16, emu.memory.cart0, codeStart)
      if ok and ((instr & 0xFF00) == 0xB400 or (instr & 0xFF00) == 0xB500) then
        local codeSize = litOffset - codeStart
        -- Count BL instructions in the function
        local blCount = 0
        local blTargets = {}
        for i = 0, codeSize - 4, 2 do
          local okH, hi = pcall(emu.memory.cart0.read16, emu.memory.cart0, codeStart + i)
          local okL, lo = pcall(emu.memory.cart0.read16, emu.memory.cart0, codeStart + i + 2)
          if okH and okL and (hi & 0xF800) == 0xF000 and (lo & 0xF800) == 0xF800 then
            blCount = blCount + 1
            -- Decode BL target
            local oh = hi & 0x07FF
            local ol = lo & 0x07FF
            local fullOff = (oh << 12) | (ol << 1)
            if fullOff >= 0x400000 then fullOff = fullOff - 0x800000 end
            local target = 0x08000000 + codeStart + i + 4 + fullOff
            table.insert(blTargets, target)
          end
        end

        -- SetCB2WarpAndLoadMap: small (4-20 bytes code), exactly 2 BL calls
        if codeSize >= 4 and codeSize <= 20 and blCount == 2 then
          local funcAddr = 0x08000000 + codeStart + 1  -- THUMB
          table.insert(warpFuncCandidates, {
            addr = funcAddr,
            size = codeSize,
            blTargets = blTargets,
            priority = 1,  -- Best candidate
          })
          console:log(string.format("  CANDIDATE SetCB2WarpAndLoadMap: 0x%08X (%d bytes, BL→0x%08X, BL→0x%08X)",
            funcAddr, codeSize, blTargets[1] or 0, blTargets[2] or 0))
        -- Slightly larger functions might be DoWarp variants
        elseif codeSize >= 8 and codeSize <= 40 and blCount >= 2 then
          local funcAddr = 0x08000000 + codeStart + 1
          table.insert(warpFuncCandidates, {
            addr = funcAddr,
            size = codeSize,
            blTargets = blTargets,
            priority = 2,
          })
        end
        break  -- Found the function start, no need to look further back
      end
    end
  end
end

-- Sort candidates by priority (smallest/best first)
table.sort(warpFuncCandidates, function(a, b)
  if a.priority ~= b.priority then return a.priority < b.priority end
  return a.size < b.size
end)

console:log(string.format("\nTotal candidates: %d (priority 1: SetCB2WarpAndLoadMap, priority 2: DoWarp-like)", #warpFuncCandidates))
for i, c in ipairs(warpFuncCandidates) do
  if i <= 5 then
    local targets = ""
    for _, t in ipairs(c.blTargets) do
      targets = targets .. string.format("0x%08X ", t)
    end
    console:log(string.format("  #%d [P%d] 0x%08X (%d bytes) → %s", i, c.priority, c.addr, c.size, targets))
  end
end

-- ============================================================
-- PHASE 2: NATURAL WARP OBSERVATION — Capture gMain state
-- ============================================================
console:log("\n=== PHASE 2: WAITING FOR NATURAL WARP ===")
console:log("Walk through a door to capture gMain state during warp.")

local GMAIN_SNAPSHOT_SIZE = 112  -- Capture 112 bytes of gMain (0x00-0x6F)
local gMainSnapshot = nil        -- Captured during natural warp
local naturalWarpObserved = false
local prevCb2 = nil
local inWarp = false
local warpFrameCount = 0
local gMainDuringWarp = {}       -- Per-frame gMain dumps during warp

-- Read N bytes from gMain
local function readGMain(numBytes)
  local data = {}
  local base = toOff(GMAIN_BASE)
  for i = 0, numBytes - 1 do
    local ok, v = pcall(emu.memory.wram.read8, emu.memory.wram, base + i)
    data[i] = ok and v or 0
  end
  return data
end

-- Write gMain bytes (excluding callback2 at +4..+7 and specific overrides)
local function writeGMainSnapshot(snapshot, overrides)
  local base = toOff(GMAIN_BASE)
  for i = 0, #snapshot do
    -- Skip callback2 (+4..+7), we set that separately
    if i < 4 or i >= 8 then
      local val = snapshot[i]
      if overrides and overrides[i] then
        val = overrides[i]
      end
      if val then
        pcall(emu.memory.wram.write8, emu.memory.wram, base + i, val)
      end
    end
  end
end

-- Format gMain bytes as hex string
local function formatGMain(data, from, to)
  local s = ""
  for i = from, to do
    s = s .. string.format("%02X", data[i] or 0)
    if (i - from + 1) % 4 == 0 then s = s .. " " end
  end
  return s
end

-- ============================================================
-- PHASE 3: FORCED WARP TESTING
-- ============================================================
local phase = "observing"  -- observing, ready, testing
local testMethod = 0       -- 0 = not started, 1 = SetCB2Warp, 2 = snapshot, 3 = direct
local testFrames = 0
local prevStart = false
local prevSelect = false

-- Write sWarpDestination + SaveBlock1
local function writeWarpDest()
  local swOff = toOff(SWARP)
  emu.memory.wram:write8(swOff, DEST_GROUP)
  emu.memory.wram:write8(swOff + 1, DEST_MAP)
  emu.memory.wram:write8(swOff + 2, 0xFF)  -- warpId = -1
  emu.memory.wram:write8(swOff + 3, 0)     -- pad
  emu.memory.wram:write16(swOff + 4, DEST_X)
  emu.memory.wram:write16(swOff + 6, DEST_Y)

  local sbOff = toOff(SB1_LOC)
  emu.memory.wram:write8(sbOff, DEST_GROUP)
  emu.memory.wram:write8(sbOff + 1, DEST_MAP)
  emu.memory.wram:write8(sbOff + 2, 0xFF)
  emu.memory.wram:write8(sbOff + 3, 0)
  emu.memory.wram:write16(sbOff + 4, DEST_X)
  emu.memory.wram:write16(sbOff + 6, DEST_Y)
  emu.memory.wram:write16(toOff(0x02024CBC), DEST_X)
  emu.memory.wram:write16(toOff(0x02024CBE), DEST_Y)
end

-- Dump current state for diagnostics
local function dumpState(label)
  local base = toOff(GMAIN_BASE)
  local cb2 = emu.memory.wram:read32(base + 0x04)
  local state65 = emu.memory.wram:read8(base + 0x65)
  local state66 = emu.memory.wram:read8(base + 0x66)
  local sw0 = emu.memory.wram:read32(toOff(SWARP))
  local sw4 = emu.memory.wram:read32(toOff(SWARP) + 4)
  console:log(string.format("  [%s] cb2=0x%08X s65=%d s66=%d sWarp=0x%08X_%08X",
    label, cb2, state65, state66, sw0, sw4))
end

local methodNames = {
  [1] = "SetCB2WarpAndLoadMap (ROM function)",
  [2] = "gMain snapshot replay",
  [3] = "Direct CB2_LoadMap (baseline)",
}

callbacks:add("frame", function()
  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, toOff(CB2_ADDR))
  if not ok then return end

  -- Read keys
  local startKey = emu:readKey("start")
  local selectKey = emu:readKey("select")
  local startPressed = startKey and not prevStart
  local selectPressed = selectKey and not prevSelect
  prevStart = startKey
  prevSelect = selectKey

  -- === PHASE 2: Observe natural warps ===
  if not inWarp and prevCb2 == CB2_OVERWORLD and cb2 ~= CB2_OVERWORLD then
    inWarp = true
    warpFrameCount = 0
    gMainDuringWarp = {}
    console:log("\n=== NATURAL WARP DETECTED ===")
  end

  if inWarp then
    warpFrameCount = warpFrameCount + 1
    local snapshot = readGMain(GMAIN_SNAPSHOT_SIZE)
    table.insert(gMainDuringWarp, snapshot)

    if warpFrameCount <= 5 then
      console:log(string.format("  Warp frame %d: cb2=0x%08X", warpFrameCount, cb2))
      console:log(string.format("    gMain[00-0F]: %s", formatGMain(snapshot, 0, 15)))
      console:log(string.format("    gMain[10-1F]: %s", formatGMain(snapshot, 16, 31)))
      console:log(string.format("    gMain[20-3F]: %s", formatGMain(snapshot, 32, 63)))
      console:log(string.format("    gMain[60-6F]: %s", formatGMain(snapshot, 96, 111)))
    end

    if cb2 == CB2_OVERWORLD then
      console:log(string.format("=== NATURAL WARP COMPLETE after %d frames ===", warpFrameCount))
      inWarp = false

      -- Save the FIRST frame's snapshot (closest to pre-CB2_LoadMap state)
      if #gMainDuringWarp > 0 then
        gMainSnapshot = gMainDuringWarp[1]
        naturalWarpObserved = true
        console:log("gMain snapshot captured from warp frame 1!")
        console:log(string.format("  gMain[00-0F]: %s", formatGMain(gMainSnapshot, 0, 15)))
        console:log(string.format("  gMain[60-6F]: %s", formatGMain(gMainSnapshot, 96, 111)))

        -- Analyze which byte is the state counter
        if #gMainDuringWarp >= 3 then
          console:log("\n  State counter analysis (bytes that increment 0→1→2 across frames):")
          local frame1 = gMainDuringWarp[1]
          local frame2 = gMainDuringWarp[2]
          local frame3 = gMainDuringWarp[3]
          for i = 0, GMAIN_SNAPSHOT_SIZE - 1 do
            if i < 4 or i >= 8 then  -- Skip callback2 bytes
              local v1 = frame1[i] or 0
              local v2 = frame2[i] or 0
              local v3 = frame3[i] or 0
              -- Look for incrementing pattern
              if v2 == v1 + 1 and v3 == v2 + 1 then
                console:log(string.format("    +0x%02X: %d → %d → %d  *** STATE COUNTER ***", i, v1, v2, v3))
              elseif v1 ~= v2 or v2 ~= v3 then
                -- Show any changing bytes
                if i >= 0x30 then  -- Skip low bytes (callback1, counters, keys)
                  console:log(string.format("    +0x%02X: %d → %d → %d (changed)", i, v1, v2, v3))
                end
              end
            end
          end
        end

        if phase == "observing" then
          phase = "ready"
          testMethod = 1
          console:log("\n=== READY TO TEST ===")
          console:log("Press START to test forced warp (method 1: " .. methodNames[1] .. ")")
          console:log("Press SELECT to cycle to next method")
        end
      end
    end

    if warpFrameCount > 300 then
      console:log("Natural warp timeout, resetting...")
      inWarp = false
    end
  end

  prevCb2 = cb2

  -- === PHASE 3: Test forced warp ===
  if phase == "ready" then
    if selectPressed then
      testMethod = testMethod % 3 + 1
      console:log(string.format("Method changed to #%d: %s", testMethod, methodNames[testMethod]))
      if testMethod == 1 and #warpFuncCandidates == 0 then
        console:log("  (No ROM candidates found, will skip to method 2)")
        testMethod = 2
      end
    end

    if startPressed then
      console:log(string.format("\n=== TESTING METHOD %d: %s ===", testMethod, methodNames[testMethod]))
      dumpState("BEFORE")

      -- Write warp destination
      writeWarpDest()
      console:log("  Warp destination written to sWarpDest + SaveBlock1")

      local base = toOff(GMAIN_BASE)

      if testMethod == 1 and #warpFuncCandidates > 0 then
        -- Method 1: Use SetCB2WarpAndLoadMap from ROM
        local funcAddr = warpFuncCandidates[1].addr
        console:log(string.format("  Setting callback2 = 0x%08X (SetCB2WarpAndLoadMap)", funcAddr))
        -- NULL callback1 (SetCB2WarpAndLoadMap will handle the rest)
        emu.memory.wram:write32(base + 0x00, 0)
        emu.memory.wram:write32(base + 0x04, funcAddr)

      elseif testMethod == 2 and gMainSnapshot then
        -- Method 2: Replay gMain snapshot from natural warp
        console:log("  Restoring gMain snapshot from natural warp...")
        local overrides = {
          -- Force state to 0 (natural warp frame 1 has state=1 since CB2_LoadMap ran once)
          -- We need to find the state byte and decrement it
        }
        -- Find state counter offset from analysis
        if #gMainDuringWarp >= 2 then
          for i = 0x30, GMAIN_SNAPSHOT_SIZE - 1 do
            if i < 4 or i >= 8 then
              local v1 = gMainDuringWarp[1][i] or 0
              local v2 = gMainDuringWarp[2][i] or 0
              if v2 == v1 + 1 then
                -- This is likely the state counter. Set it to 0.
                overrides[i] = 0
                console:log(string.format("  State counter at +0x%02X, setting to 0 (was %d)", i, v1))
              end
            end
          end
        end
        writeGMainSnapshot(gMainSnapshot, overrides)
        emu.memory.wram:write32(base + 0x04, CB2_LOADMAP)
        console:log("  gMain snapshot applied, callback2 = CB2_LoadMap")

      else
        -- Method 3: Direct CB2_LoadMap (current approach, baseline)
        console:log("  Direct approach: NULL cb1, zero state, set CB2_LoadMap")
        emu.memory.wram:write32(base + 0x00, 0)
        emu.memory.wram:write8(base + 0x65, 0)
        emu.memory.wram:write32(base + 0x04, CB2_LOADMAP)
      end

      dumpState("AFTER_TRIGGER")
      phase = "testing"
      testFrames = 0
    end

  elseif phase == "testing" then
    testFrames = testFrames + 1

    if testFrames <= 10 or testFrames % 20 == 0 then
      dumpState(string.format("F%d", testFrames))
    end

    if cb2 == CB2_OVERWORLD then
      console:log(string.format("\n*** SUCCESS! Method %d worked after %d frames! ***", testMethod, testFrames))
      console:log(string.format("Method: %s", methodNames[testMethod]))
      dumpState("SUCCESS")
      phase = "done"

    elseif testFrames >= 120 then
      console:log(string.format("\n*** TIMEOUT! Method %d failed after %d frames ***", testMethod, testFrames))
      dumpState("TIMEOUT")
      -- Restore CB2_Overworld
      local base = toOff(GMAIN_BASE)
      emu.memory.wram:write32(base + 0x04, CB2_OVERWORLD)
      console:log("  Restored CB2_Overworld to unfreeze game")
      phase = "ready"
      testMethod = testMethod % 3 + 1
      console:log(string.format("  Next method: #%d: %s", testMethod, methodNames[testMethod]))
      console:log("  Press START to try next method, SELECT to cycle")
    end

  elseif phase == "done" then
    -- Warp succeeded, log final state
    if startPressed then
      console:log("\n=== RESETTING FOR NEW TEST ===")
      phase = "ready"
      testMethod = 1
    end
  end
end)

console:log("\nScript ready. Walk through a door first, then press START to test.")
