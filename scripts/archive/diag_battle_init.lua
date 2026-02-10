-- Diagnostic script: reads battle-related memory addresses every frame
-- Run with: mGBA.exe -t "rom/Pokemon RunBun.ss1" --script "scripts/ToUse/diag_battle_init.lua" "rom/Pokemon RunBun.gba"
-- Then manually trigger a battle to see the init chain

local frameCount = 0
local logFile = io.open("battle_init_diag.txt", "w")

local function log(msg)
  console:log(msg)
  if logFile then
    logFile:write(msg .. "\n")
    logFile:flush()
  end
end

-- Key addresses
local CB2_ADDR = 0x030022C4         -- gMain.callback2 (IWRAM)
local IWRAM_BASE = 0x03000000
local EWRAM_BASE = 0x02000000

local gBattleMainFunc     = 0x03005D04
local gBattlerCtrlFuncs   = 0x03005D70
local gBattleCtrlExecFlags = 0x020233E0
local gBattleCommunication = 0x0202370E
local gBattleTypeFlags    = 0x02023364
local gMainInBattle       = 0x03002AF9

local CB2_InitBattle          = 0x080363C1
local CB2_InitBattleInternal  = 0x0803648D
local CB2_HandleStartBattle   = 0x08037B45
local CB2_BattleMain          = 0x0803816D

local function readIWRAM32(addr) return emu.memory.iwram:read32(addr - IWRAM_BASE) end
local function readIWRAM8(addr) return emu.memory.iwram:read8(addr - IWRAM_BASE) end
local function readEWRAM32(addr) return emu.memory.wram:read32(addr - EWRAM_BASE) end
local function readEWRAM8(addr) return emu.memory.wram:read8(addr - EWRAM_BASE) end

local function getPhase(cb2)
  if cb2 == CB2_InitBattle then return "InitBattle"
  elseif cb2 == CB2_InitBattleInternal then return "InitBattleInternal"
  elseif cb2 == CB2_HandleStartBattle then return "HandleStartBattle"
  elseif cb2 == CB2_BattleMain then return "BattleMainCB2"
  else return string.format("0x%08X", cb2) end
end

log("=== BATTLE INIT DIAGNOSTIC ===")
log("Watching callback2 at IWRAM 0x030022C4")

callbacks:add("frame", function()
  frameCount = frameCount + 1

  -- Read callback2
  local ok, cb2 = pcall(readIWRAM32, CB2_ADDR)
  if not ok then return end

  -- Read battle state
  local ok2, btf = pcall(readEWRAM32, gBattleTypeFlags)
  local ok3, bmf = pcall(readIWRAM32, gBattleMainFunc)
  local ok4, ib = pcall(readIWRAM8, gMainInBattle)
  local ok5, ef = pcall(readEWRAM32, gBattleCtrlExecFlags)
  local ok6, comm0 = pcall(readEWRAM8, gBattleCommunication)
  local ok7, ctrl0 = pcall(readIWRAM32, gBattlerCtrlFuncs)
  local ok8, ctrl1 = pcall(readIWRAM32, gBattlerCtrlFuncs + 4)

  -- Log every 30 frames or on phase change
  if frameCount % 30 == 0 or frameCount <= 5 then
    log(string.format("f=%d cb2=%s btf=0x%08X bmf=0x%08X ib=%d ef=0x%08X comm0=%d ctrl0=0x%08X ctrl1=0x%08X",
      frameCount,
      getPhase(cb2),
      ok2 and btf or 0, ok3 and bmf or 0, ok4 and (ib & 0x02) or 0,
      ok5 and ef or 0, ok6 and comm0 or 0, ok7 and ctrl0 or 0, ok8 and ctrl1 or 0))
  end

  -- Stop after 300 frames
  if frameCount >= 300 then
    log("=== DIAGNOSTIC COMPLETE (300 frames) ===")
    if logFile then logFile:close() end
  end
end)
