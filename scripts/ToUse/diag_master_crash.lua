-- Diagnostic script for master crash
-- Monitors gBattleStruct heap data, exec flags, and gBattleCommunication
-- Run with: mGBA.exe -t ss1 --script scripts/ToUse/diag_master_crash.lua "rom/Pokemon RunBun.gba"

-- Addresses from config
local gBattleStruct_ptr = 0x02023A0C    -- pointer to heap struct
local gBattleResources_ptr = 0x02023A18 -- pointer to heap resources
local gBattleControllerExecFlags = 0x020233E0
local gBattleTypeFlags = 0x02023364
local gBattleCommunication = 0x0202370E
local gBattleMainFunc = 0x03005D04      -- IWRAM
local gBattlerControllerFuncs = 0x03005D70 -- IWRAM
local callback2Addr = 0x030022C4        -- gMain.callback2 (IWRAM)
local CB2_BattleMain = 0x0803816D
local DoBattleIntro = 0x0803ACB1

-- Exec local patch addresses (ROM cart0)
local patches = {
  { name = "markExecLocal",    off = 0x040F50, expect = 0xD010, patched = 0xE010 },
  { name = "isExecLocal",      off = 0x040EFC, expect = 0xD00E, patched = 0xE00E },
  { name = "markAllExecLocal", off = 0x040E88, expect = 0xD018, patched = 0xE018 },
  { name = "playerBufSkip",    off = 0x06F0F0, expect = 0xD01C, patched = 0xE01C },
  { name = "linkOppBufSkip",   off = 0x07E92C, expect = 0xD01C, patched = 0xE01C },
  { name = "prepBufLocal",     off = 0x032FC0, expect = 0xD008, patched = 0xE008 },
}

local frame = 0
local logFile = io.open("diag_master.txt", "w")
local inBattle = false
local lastBsPtr = 0
local lastBsData = ""

local function toWRAM(addr) return addr - 0x02000000 end
local function toIWRAM(addr) return addr - 0x03000000 end

local function readW8(addr) return emu.memory.wram:read8(toWRAM(addr)) end
local function readW16(addr) return emu.memory.wram:read16(toWRAM(addr)) end
local function readW32(addr) return emu.memory.wram:read32(toWRAM(addr)) end
local function readI32(addr) return emu.memory.iwram:read32(toIWRAM(addr)) end

local startTime = os.clock()
local function log(msg)
  local elapsed = os.clock() - startTime
  local line = string.format("[%.3fs] f=%d %s", elapsed, frame, msg)
  console:log(line)
  if logFile then logFile:write(line .. "\n"); logFile:flush() end
end

local function hexdump(addr, size)
  local parts = {}
  for i = 0, size - 1, 4 do
    local ok, v = pcall(readW32, addr + i)
    if ok then
      table.insert(parts, string.format("%08X", v))
    else
      table.insert(parts, "????????")
    end
  end
  return table.concat(parts, " ")
end

callbacks:add("frame", function()
  frame = frame + 1

  -- Check if we're in battle
  local ok, cb2 = pcall(readI32, callback2Addr)
  if not ok then return end

  if cb2 == CB2_BattleMain and not inBattle then
    inBattle = true
    log("=== BATTLE MAIN REACHED ===")

    -- Check all ROM patches
    for _, p in ipairs(patches) do
      local okR, v = pcall(emu.memory.cart0.read16, emu.memory.cart0, p.off)
      local status = "???"
      if okR then
        if v == p.patched then status = "PATCHED"
        elseif v == p.expect then status = "NOT_PATCHED"
        else status = string.format("UNKNOWN(0x%04X)", v) end
      end
      log(string.format("  Patch %s: %s", p.name, status))
    end
  end

  if not inBattle then return end

  -- Read key values
  local bmf = readI32(gBattleMainFunc)
  local ef = readW32(gBattleControllerExecFlags)
  local btf = readW32(gBattleTypeFlags)
  local comm0 = readW8(gBattleCommunication)
  local bsPtr = readW32(gBattleStruct_ptr)
  local brPtr = readW32(gBattleResources_ptr)
  local ctrl0 = readI32(gBattlerControllerFuncs)
  local ctrl1 = readI32(gBattlerControllerFuncs + 4)

  -- Read first 32 bytes of *gBattleStruct (heap data)
  local bsData = ""
  local bsValid = (bsPtr >= 0x02000000 and bsPtr < 0x02040000)
  if bsValid then
    bsData = hexdump(bsPtr, 32)
  end

  -- Log every 30 frames during intro, every 60 after
  local isDBI = (bmf == DoBattleIntro)
  local logInterval = isDBI and 30 or 60

  if frame % logInterval == 0 or frame <= 5 or
     (ef ~= 0 and ef ~= 0x01 and ef ~= 0x02 and ef ~= 0x03) or
     bsPtr ~= lastBsPtr or
     (bsData ~= lastBsData and isDBI) then

    log(string.format("bmf=%08X ef=%08X btf=%08X comm0=%d bs=%08X br=%08X c0=%08X c1=%08X",
      bmf, ef, btf, comm0, bsPtr, brPtr, ctrl0, ctrl1))

    if bsValid then
      log(string.format("  *bs[0..31]: %s", bsData))

      -- eventState.battleIntro at offset 0x2F9
      local okI, introState = pcall(readW8, bsPtr + 0x2F9)
      if okI then
        log(string.format("  eventState.battleIntro = %d", introState))
      end
    end

    if bsPtr ~= lastBsPtr then
      log(string.format("  *** gBattleStruct POINTER CHANGED: 0x%08X -> 0x%08X ***", lastBsPtr, bsPtr))
    end

    lastBsPtr = bsPtr
    lastBsData = bsData
  end

  -- Screenshot every 300 frames
  if frame % 300 == 0 then
    pcall(function() emu:screenshot(string.format("diag_f%05d.png", frame)) end)
  end
end)

log("Diagnostic script loaded, waiting for battle...")
