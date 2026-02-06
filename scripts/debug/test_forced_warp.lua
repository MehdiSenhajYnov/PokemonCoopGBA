--[[
  test_forced_warp.lua

  Isolated test: force a warp to map 28:24 (duel room) and log
  everything frame-by-frame to diagnose why CB2_LoadMap gets stuck.

  Press START to trigger the forced warp.
  Logs callback2, gMain.state, and other fields every frame.
]]

local CB2_ADDR = 0x0202064C    -- gMain.callback2
local GMAIN_BASE = 0x02020648  -- gMain base
local SB1_LOC = 0x02024CC0    -- SaveBlock1->location
local SWARP = 0x020318A8       -- sWarpDestination (CONFIRMED)
local CB2_LOADMAP = 0x08007441
local CB2_OVERWORLD = 0x080A89A5

local DEST_GROUP = 28
local DEST_MAP = 24
local DEST_X = 5
local DEST_Y = 5

local function toOff(addr) return addr - 0x02000000 end

local phase = "idle"  -- idle, triggered, loading
local loadFrames = 0
local prevStart = false

console:log("=== Forced Warp Test ===")
console:log("Press START to trigger warp to 28:24 (5,5)")
console:log(string.format("sWarpDestination: 0x%08X (CONFIRMED)", SWARP))
console:log("")

-- Dump current state
local function dumpState(label)
  local base = toOff(GMAIN_BASE)
  local cb1 = emu.memory.wram:read32(base + 0x00)
  local cb2 = emu.memory.wram:read32(base + 0x04)
  local f08 = emu.memory.wram:read32(base + 0x08)
  local f0C = emu.memory.wram:read32(base + 0x0C)
  local f10 = emu.memory.wram:read32(base + 0x10)
  local s65 = emu.memory.wram:read8(base + 0x65)
  local s66 = emu.memory.wram:read8(base + 0x66)

  -- Also try state at other offsets
  local s34 = emu.memory.wram:read8(base + 0x34)
  local s35 = emu.memory.wram:read8(base + 0x35)
  local s36 = emu.memory.wram:read8(base + 0x36)
  local s37 = emu.memory.wram:read8(base + 0x37)
  local s38 = emu.memory.wram:read8(base + 0x38)

  -- Read sWarpDestination content
  local sw0 = emu.memory.wram:read32(toOff(SWARP))
  local sw4 = emu.memory.wram:read32(toOff(SWARP) + 4)

  -- Read SaveBlock1->location
  local sb0 = emu.memory.wram:read32(toOff(SB1_LOC))
  local sb4 = emu.memory.wram:read32(toOff(SB1_LOC) + 4)

  console:log(string.format("[%s] cb1=0x%08X cb2=0x%08X +08=0x%08X +0C=0x%08X +10=0x%08X",
    label, cb1, cb2, f08, f0C, f10))
  console:log(string.format("  state: +34=%d +35=%d +36=%d +37=%d +38=%d +65=%d +66=%d",
    s34, s35, s36, s37, s38, s65, s66))
  console:log(string.format("  sWarp=0x%08X_%08X  SB1=0x%08X_%08X", sw0, sw4, sb0, sb4))
end

callbacks:add("frame", function()
  -- Read START button (bit 3 of key input register)
  local keys = emu:readKey("start")
  local startPressed = keys and not prevStart
  prevStart = keys

  if phase == "idle" then
    if startPressed then
      console:log("\n=== TRIGGERING FORCED WARP ===")
      dumpState("BEFORE")

      -- Step 1: Write sWarpDestination
      local swOff = toOff(SWARP)
      emu.memory.wram:write8(swOff, DEST_GROUP)
      emu.memory.wram:write8(swOff + 1, DEST_MAP)
      emu.memory.wram:write8(swOff + 2, 0xFF)  -- warpId = -1
      emu.memory.wram:write8(swOff + 3, 0)     -- pad
      emu.memory.wram:write16(swOff + 4, DEST_X)
      emu.memory.wram:write16(swOff + 6, DEST_Y)
      console:log("[WRITE] sWarpDestination = 28:24 (5,5)")

      -- Step 2: Write SaveBlock1->location + pos
      local sbOff = toOff(SB1_LOC)
      emu.memory.wram:write8(sbOff, DEST_GROUP)
      emu.memory.wram:write8(sbOff + 1, DEST_MAP)
      emu.memory.wram:write8(sbOff + 2, 0xFF)
      emu.memory.wram:write8(sbOff + 3, 0)
      emu.memory.wram:write16(sbOff + 4, DEST_X)
      emu.memory.wram:write16(sbOff + 6, DEST_Y)
      emu.memory.wram:write16(toOff(0x02024CBC), DEST_X)  -- playerX
      emu.memory.wram:write16(toOff(0x02024CBE), DEST_Y)  -- playerY
      console:log("[WRITE] SaveBlock1->location + pos")

      dumpState("AFTER_WRITE")

      -- Step 3: Trigger map load (MINIMAL: only cb1, state, cb2)
      local base = toOff(GMAIN_BASE)
      emu.memory.wram:write32(base + 0x00, 0)           -- NULL callback1
      emu.memory.wram:write8(base + 0x65, 0)            -- zero state
      emu.memory.wram:write32(base + 0x04, CB2_LOADMAP) -- set callback2

      console:log("[TRIGGER] cb1=NULL state=0 cb2=CB2_LoadMap")
      dumpState("AFTER_TRIGGER")

      phase = "loading"
      loadFrames = 0
    end

  elseif phase == "loading" then
    loadFrames = loadFrames + 1

    local base = toOff(GMAIN_BASE)
    local cb2 = emu.memory.wram:read32(base + 0x04)

    -- Log every frame for the first 20 frames, then every 10
    if loadFrames <= 20 or loadFrames % 10 == 0 then
      dumpState(string.format("F%d", loadFrames))
    end

    if cb2 == CB2_OVERWORLD then
      console:log(string.format("\n=== WARP COMPLETE after %d frames ===", loadFrames))
      dumpState("COMPLETE")
      phase = "done"
    elseif cb2 ~= CB2_LOADMAP then
      console:log(string.format("\n=== CALLBACK2 CHANGED to 0x%08X at frame %d ===", cb2, loadFrames))
      dumpState("CHANGED")
      -- Keep monitoring
    end

    if loadFrames >= 120 then
      console:log(string.format("\n=== TIMEOUT after %d frames ===", loadFrames))
      dumpState("TIMEOUT")
      -- Restore CB2_Overworld to unfreeze
      emu.memory.wram:write32(base + 0x04, CB2_OVERWORLD)
      console:log("[RESTORE] Forced callback2 = CB2_Overworld")
      phase = "done"
    end
  end
end)
