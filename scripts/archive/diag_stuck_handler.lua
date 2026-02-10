--[[
  Diagnostic Script: Stuck Player Controller Handler

  Purpose: Identify why battler 0's Player handler (0x08071B65) is stuck
  with gBattleControllerExecFlags = 0x01 (bit 0 set, battler 0 active).

  Reads and logs:
  - bufferA[0] command ID (what command the handler is processing)
  - gBattleSpritesDataPtr (animation/sprite state)
  - gBattleMainFunc and all 4 battler controller funcs
  - gBattleCommunication[0..7]
  - gBattleMons[0] and [1] species/HP
  - gBattleControllerExecFlags per-byte breakdown
  - gActiveBattler
  - gBattleTypeFlags
  - gBattleTurnCounter
  - gBattleOutcome
  - gBattlerPositions
  - Callback2 value

  Run from save state with battle already in progress.
  Usage: mGBA --script scripts/ToUse/diag_stuck_handler.lua "rom/Pokemon RunBun.gba"
         (load save state manually or it runs on current state)
]]

-- ============================================================
-- Memory addresses (from config/run_and_bun.lua)
-- ============================================================

local ADDR = {
  -- EWRAM battle variables
  gBattleTypeFlags          = 0x02023364,
  gActiveBattler            = 0x020233DC,
  gBattleControllerExecFlags = 0x020233E0,
  gBattlersCount            = 0x020233E4,
  gBattlerPositions         = 0x020233EE,
  gBattlerByTurnOrder       = 0x020233F6,
  gBattleMons               = 0x020233FC,  -- 0x5C per battler
  gBattleCommunication      = 0x0202370E,  -- 8 bytes
  gBattleTurnCounter        = 0x02023708,
  gBattleOutcome            = 0x02023716,
  gChosenActionByBattler    = 0x02023598,
  gChosenMoveByBattler      = 0x020235FA,
  gBattlescriptCurrInstr    = 0x02023594,
  gBattleResources          = 0x02023A18,  -- pointer to heap struct
  gBattleSpritesDataPtr     = 0x02023A0C,  -- pointer to sprite data
  gBattlerSpriteIds         = 0x0202356C,  -- u8[4]
  gPlayerParty              = 0x02023A98,
  gEnemyParty               = 0x02023CF0,

  -- IWRAM addresses
  gBattleMainFunc           = 0x03005D04,
  gBattlerControllerFuncs   = 0x03005D70,  -- u32[4]
  gBattlerControllerEndFuncs = 0x03005D80, -- u32[4]
  gPreBattleCallback1       = 0x03005D00,
  gRngValue                 = 0x03005D90,
  callback2Addr             = 0x030022C4,  -- gMain.callback2

  -- BattleResources struct offsets
  bufferA_offset            = 0x024,       -- bufferA at *gBattleResources + 0x024
  bufferB_offset            = 0x824,       -- bufferB at *gBattleResources + 0x824
  battlerBufferStride       = 0x200,       -- 512 bytes per battler slot
}

-- Known ROM function addresses for labeling
local KNOWN_FUNCS = {
  [0x0803ACB1] = "DoBattleIntro",
  [0x0803BE39] = "HandleTurnActionSelectionState",
  [0x0803E371] = "RunTurnActionsFunctions",
  [0x0803D8F1] = "SetActionsAndBattlersTurnOrder",
  [0x0803ECAD] = "??? (stuck bmf)",
  [0x0803816D] = "BattleMainCB2",
  [0x080363C1] = "CB2_InitBattle",
  [0x0803648D] = "CB2_InitBattleInternal",
  [0x08037B45] = "CB2_HandleStartBattle",
  [0x080A89A5] = "CB2_Overworld",
  [0x080A3FDD] = "CB2_LoadMap",
  [0x0806F151] = "PlayerBufferRunCommand",
  [0x0806F0A5] = "SetControllerToPlayer",
  [0x0806F0A1] = "BattleControllerDummy",
  [0x0806F0D5] = "PlayerBufferExecCompleted",
  [0x0807DC45] = "LinkOpponentRunCommand",
  [0x0807DC29] = "SetControllerToLinkOpponent",
  [0x081BAD85] = "OpponentBufferRunCommand",
  [0x081BB945] = "OpponentBufferExecCompleted",
  [0x08071B65] = "PlayerHandleCmd_??? (STUCK)",
  [0x08000544] = "SetMainCallback2",
}

-- Buffer command IDs (from pokeemerald-expansion: include/battle_controllers.h)
local BUFFER_CMDS = {
  [0x00] = "CONTROLLER_GETMONDATA",
  [0x01] = "CONTROLLER_GETRAWMONDATA",
  [0x02] = "CONTROLLER_SETMONDATA",
  [0x03] = "CONTROLLER_SETRAWMONDATA",
  [0x04] = "CONTROLLER_LOADMONSPRITE",
  [0x05] = "CONTROLLER_SWITCHINANIM",
  [0x06] = "CONTROLLER_RETURNMONTOBALL",
  [0x07] = "CONTROLLER_DRAWTRAINERPIC",
  [0x08] = "CONTROLLER_TRAINERSLIDE",
  [0x09] = "CONTROLLER_TRAINERSLIDEBACK",
  [0x0A] = "CONTROLLER_FAINTANIMATION",
  [0x0B] = "CONTROLLER_PALETTEFADE",         -- NOTE: might be unused
  [0x0C] = "CONTROLLER_SUCCESSBALLTHROWANIM",
  [0x0D] = "CONTROLLER_BALLTHROWANIM",
  [0x0E] = "CONTROLLER_PAUSE",
  [0x0F] = "CONTROLLER_MOVEANIMATION",
  [0x10] = "CONTROLLER_PRINTSTRING",
  [0x11] = "CONTROLLER_PRINTSTRINGPLAYERONLY",
  [0x12] = "CONTROLLER_CHOOSEACTION",
  [0x13] = "CONTROLLER_YESORNO",             -- CONTROLLER_UNKNOWNYESORNO in some
  [0x14] = "CONTROLLER_CHOOSEMOVE",
  [0x15] = "CONTROLLER_OPENBAG",
  [0x16] = "CONTROLLER_CHOOSEPOKEMON",
  [0x17] = "CONTROLLER_23",
  [0x18] = "CONTROLLER_HEALTHBARUPDATE",
  [0x19] = "CONTROLLER_EXPUPDATE",
  [0x1A] = "CONTROLLER_STATUSICONUPDATE",
  [0x1B] = "CONTROLLER_STATUSANIMATION",
  [0x1C] = "CONTROLLER_STATUSXOR",           -- CONTROLLER_DATAXTRANSFER in some
  [0x1D] = "CONTROLLER_DMA3TRANSFER",        -- or CONTROLLER_29
  [0x1E] = "CONTROLLER_PLAYBGM",
  [0x1F] = "CONTROLLER_32",
  [0x20] = "CONTROLLER_TWORETURNVALUES",
  [0x21] = "CONTROLLER_CHOSENMONRETURNVALUE",
  [0x22] = "CONTROLLER_ONERETURNVALUE",
  [0x23] = "CONTROLLER_ONERETURNVALUE_DUPLICATE",
  [0x24] = "CONTROLLER_CLEARUNKVAR",          -- CONTROLLER_36
  [0x25] = "CONTROLLER_SETUNKVAR",            -- CONTROLLER_37
  [0x26] = "CONTROLLER_CLEARUNKFLAG",         -- CONTROLLER_38
  [0x27] = "CONTROLLER_TOGGLEUNKFLAG",        -- CONTROLLER_39
  [0x28] = "CONTROLLER_HITANIMATION",
  [0x29] = "CONTROLLER_CANTSWITCH",           -- CONTROLLER_42
  [0x2A] = "CONTROLLER_PLAYSE",
  [0x2B] = "CONTROLLER_PLAYFANFAREORBGM",
  [0x2C] = "CONTROLLER_FAINTINGCRY",
  [0x2D] = "CONTROLLER_INTROSLIDE",
  [0x2E] = "CONTROLLER_INTROTRAINERBALLTHROW",
  [0x2F] = "CONTROLLER_DRAWPARTYSTATUSSUMMARY",
  [0x30] = "CONTROLLER_HIDEPARTYSTATUSSUMMARY",
  [0x31] = "CONTROLLER_ENDBOUNCE",
  [0x32] = "CONTROLLER_SPRITEINVISIBILITY",
  [0x33] = "CONTROLLER_BATTLEANIMATION",
  [0x34] = "CONTROLLER_LINKSTANDBYMSG",
  [0x35] = "CONTROLLER_RESETACTIONMOVESELECTION",
  [0x36] = "CONTROLLER_ENDLINKBATTLE",
  [0x37] = "CONTROLLER_DEBUGMENU",
  [0x38] = "CONTROLLER_TERMINATOR_NOP",
}

-- ============================================================
-- Memory helpers
-- ============================================================

local function r8(addr)
  if addr >= 0x03000000 and addr < 0x03008000 then
    return emu.memory.iwram:read8(addr - 0x03000000)
  elseif addr >= 0x02000000 and addr < 0x02040000 then
    return emu.memory.wram:read8(addr - 0x02000000)
  elseif addr >= 0x08000000 and addr < 0x0A000000 then
    return emu.memory.cart0:read8(addr - 0x08000000)
  end
  return nil
end

local function r16(addr)
  if addr >= 0x03000000 and addr < 0x03008000 then
    return emu.memory.iwram:read16(addr - 0x03000000)
  elseif addr >= 0x02000000 and addr < 0x02040000 then
    return emu.memory.wram:read16(addr - 0x02000000)
  elseif addr >= 0x08000000 and addr < 0x0A000000 then
    return emu.memory.cart0:read16(addr - 0x08000000)
  end
  return nil
end

local function r32(addr)
  if addr >= 0x03000000 and addr < 0x03008000 then
    return emu.memory.iwram:read32(addr - 0x03000000)
  elseif addr >= 0x02000000 and addr < 0x02040000 then
    return emu.memory.wram:read32(addr - 0x02000000)
  elseif addr >= 0x08000000 and addr < 0x0A000000 then
    return emu.memory.cart0:read32(addr - 0x08000000)
  end
  return nil
end

-- Safe wrappers
local function sr8(addr)  local ok, v = pcall(r8, addr);  return ok and v or nil end
local function sr16(addr) local ok, v = pcall(r16, addr); return ok and v or nil end
local function sr32(addr) local ok, v = pcall(r32, addr); return ok and v or nil end

local function hex8(v)  return v and string.format("0x%02X", v) or "nil" end
local function hex16(v) return v and string.format("0x%04X", v) or "nil" end
local function hex32(v) return v and string.format("0x%08X", v) or "nil" end

local function labelFunc(addr)
  if not addr then return "nil" end
  local name = KNOWN_FUNCS[addr]
  if name then
    return string.format("0x%08X (%s)", addr, name)
  else
    return string.format("0x%08X", addr)
  end
end

local function labelCmd(cmdId)
  if not cmdId then return "nil" end
  local name = BUFFER_CMDS[cmdId]
  if name then
    return string.format("0x%02X (%s)", cmdId, name)
  else
    return string.format("0x%02X (UNKNOWN)", cmdId)
  end
end

-- ============================================================
-- Diagnostic data collection
-- ============================================================

local results = {}
local frameCount = 0
local LOG_INTERVAL = 30
local MAX_FRAMES = 300

local function collectDiagnostics(frame)
  local diag = { frame = frame }

  -- 1. gBattleMainFunc
  diag.bmf = sr32(ADDR.gBattleMainFunc)

  -- 2. gBattleControllerExecFlags (full 32-bit + per-byte)
  diag.execFlags = sr32(ADDR.gBattleControllerExecFlags)
  diag.execByte = {}
  for i = 0, 3 do
    diag.execByte[i] = sr8(ADDR.gBattleControllerExecFlags + i)
  end

  -- 3. gActiveBattler
  diag.activeBattler = sr8(ADDR.gActiveBattler)

  -- 4. All 4 battler controller funcs
  diag.ctrlFuncs = {}
  for i = 0, 3 do
    diag.ctrlFuncs[i] = sr32(ADDR.gBattlerControllerFuncs + i * 4)
  end

  -- 5. All 4 battler controller end funcs
  diag.endFuncs = {}
  for i = 0, 3 do
    diag.endFuncs[i] = sr32(ADDR.gBattlerControllerEndFuncs + i * 4)
  end

  -- 6. gBattleCommunication[0..7]
  diag.comm = {}
  for i = 0, 7 do
    diag.comm[i] = sr8(ADDR.gBattleCommunication + i)
  end

  -- 7. gBattleTypeFlags
  diag.btf = sr32(ADDR.gBattleTypeFlags)

  -- 8. gBattleTurnCounter
  diag.turnCounter = sr16(ADDR.gBattleTurnCounter)

  -- 9. gBattleOutcome
  diag.outcome = sr8(ADDR.gBattleOutcome)

  -- 10. gBattlersCount
  diag.battlersCount = sr8(ADDR.gBattlersCount)

  -- 11. gBattlerPositions[0..3]
  diag.positions = {}
  for i = 0, 3 do
    diag.positions[i] = sr8(ADDR.gBattlerPositions + i)
  end

  -- 12. callback2
  diag.cb2 = sr32(ADDR.callback2Addr)

  -- 13. gRngValue
  diag.rng = sr32(ADDR.gRngValue)

  -- 14. gBattlescriptCurrInstr
  diag.bsInstr = sr32(ADDR.gBattlescriptCurrInstr)

  -- 15. gBattlerSpriteIds[0..3]
  diag.spriteIds = {}
  for i = 0, 3 do
    diag.spriteIds[i] = sr8(ADDR.gBattlerSpriteIds + i)
  end

  -- 16. gChosenActionByBattler[0..1]
  diag.chosenAction = {}
  for i = 0, 1 do
    diag.chosenAction[i] = sr8(ADDR.gChosenActionByBattler + i)
  end

  -- 17. gChosenMoveByBattler[0..1]
  diag.chosenMove = {}
  for i = 0, 1 do
    diag.chosenMove[i] = sr16(ADDR.gChosenMoveByBattler + i * 2)
  end

  -- 18. gBattleMons[0] and [1] - species, HP, maxHP, status, level
  diag.mons = {}
  for b = 0, 1 do
    local base = ADDR.gBattleMons + b * 0x5C
    local mon = {}
    mon.species = sr16(base + 0x00)  -- species at offset 0
    mon.attack  = sr16(base + 0x02)  -- attack at offset 2
    mon.defense = sr16(base + 0x04)  -- defense at offset 4
    mon.speed   = sr16(base + 0x06)  -- speed at offset 6
    mon.spAtk   = sr16(base + 0x08)  -- spAtk at offset 8
    mon.spDef   = sr16(base + 0x0A)  -- spDef at offset 10
    -- moves at 0x0C-0x13 (4 x u16)
    mon.moves = {}
    for m = 0, 3 do
      mon.moves[m] = sr16(base + 0x0C + m * 2)
    end
    mon.hp      = sr16(base + 0x28)  -- hp at offset 0x28
    mon.maxHP   = sr16(base + 0x2A)  -- maxHP at offset 0x2A
    mon.level   = sr8(base + 0x2C)   -- level at offset 0x2C
    mon.status1 = sr32(base + 0x50)  -- status1 at offset 0x50 (but this varies in expansion)
    mon.status2 = sr32(base + 0x54)  -- status2 at offset 0x54
    diag.mons[b] = mon
  end

  -- 19. bufferA[0] and bufferA[1] command IDs (via gBattleResources)
  diag.bufferA = {}
  diag.bufferB = {}
  diag.battleResourcesPtr = sr32(ADDR.gBattleResources)
  if diag.battleResourcesPtr and diag.battleResourcesPtr >= 0x02000000 and diag.battleResourcesPtr < 0x02040000 then
    local bufABase = diag.battleResourcesPtr + ADDR.bufferA_offset
    local bufBBase = diag.battleResourcesPtr + ADDR.bufferB_offset

    for b = 0, 1 do
      local aAddr = bufABase + b * ADDR.battlerBufferStride
      local bAddr = bufBBase + b * ADDR.battlerBufferStride

      -- Read first 16 bytes of bufferA for detailed command analysis
      diag.bufferA[b] = { cmdId = sr8(aAddr), bytes = {} }
      for i = 0, 15 do
        diag.bufferA[b].bytes[i] = sr8(aAddr + i)
      end

      -- Read first 8 bytes of bufferB
      diag.bufferB[b] = { cmdId = sr8(bAddr), bytes = {} }
      for i = 0, 7 do
        diag.bufferB[b].bytes[i] = sr8(bAddr + i)
      end
    end
  end

  -- 20. gBattleSpritesDataPtr contents
  diag.spritesDataPtr = sr32(ADDR.gBattleSpritesDataPtr)
  if diag.spritesDataPtr and diag.spritesDataPtr >= 0x02000000 and diag.spritesDataPtr < 0x02040000 then
    -- BattleSpriteInfo: first 4 sub-pointers in the struct
    diag.spriteSubPtrs = {}
    for i = 0, 3 do
      diag.spriteSubPtrs[i] = sr32(diag.spritesDataPtr + i * 4)
    end

    -- Read BattleSpriteData for battler 0 and 1 (via sub-pointer at offset 0)
    -- BattleSpriteData[battler]: struct with animation state
    local dataPtr = diag.spriteSubPtrs[0]
    if dataPtr and dataPtr >= 0x02000000 and dataPtr < 0x02040000 then
      diag.spriteData = {}
      for b = 0, 1 do
        -- BattleSpriteInfo (sizeof ~0x1C per battler in expansion, varies)
        local bBase = dataPtr + b * 0x1C
        diag.spriteData[b] = {}
        for i = 0, 0x1B do
          diag.spriteData[b][i] = sr8(bBase + i)
        end
      end
    end

    -- healthBoxesData sub-pointer (offset 4 in struct)
    local hbPtr = diag.spriteSubPtrs[1]
    if hbPtr and hbPtr >= 0x02000000 and hbPtr < 0x02040000 then
      diag.healthBoxData = {}
      for b = 0, 1 do
        local hBase = hbPtr + b * 0x0C  -- sizeof HealthboxSpriteData per battler
        diag.healthBoxData[b] = {}
        for i = 0, 0x0B do
          diag.healthBoxData[b][i] = sr8(hBase + i)
        end
      end
    end
  end

  -- 21. Check for gSprites / task state near the handler address
  -- Read 16 bytes of ROM around the stuck handler to identify the function
  diag.stuckHandlerROM = {}
  local stuckAddr = diag.ctrlFuncs[0]
  if stuckAddr and stuckAddr >= 0x08000000 and stuckAddr < 0x0A000000 then
    local romBase = (stuckAddr & 0xFFFFFFFE) - 0x08000000  -- Clear THUMB bit
    for i = 0, 31 do
      diag.stuckHandlerROM[i] = sr8(0x08000000 + romBase + i)
    end
  end

  return diag
end

-- ============================================================
-- Logging
-- ============================================================

local function formatDiag(d)
  local lines = {}

  table.insert(lines, string.format("========== FRAME %d ==========", d.frame))
  table.insert(lines, "")

  -- Main state
  table.insert(lines, "--- Battle Main State ---")
  table.insert(lines, string.format("  gBattleMainFunc         = %s", labelFunc(d.bmf)))
  table.insert(lines, string.format("  callback2               = %s", labelFunc(d.cb2)))
  table.insert(lines, string.format("  gBattleTypeFlags        = %s", hex32(d.btf)))
  if d.btf then
    local flagNames = {}
    if (d.btf & 0x01) ~= 0 then table.insert(flagNames, "DOUBLE") end
    if (d.btf & 0x02) ~= 0 then table.insert(flagNames, "LINK") end
    if (d.btf & 0x04) ~= 0 then table.insert(flagNames, "IS_MASTER") end
    if (d.btf & 0x08) ~= 0 then table.insert(flagNames, "TRAINER") end
    if (d.btf & 0x10) ~= 0 then table.insert(flagNames, "FIRST_BATTLE") end
    if (d.btf & 0x20) ~= 0 then table.insert(flagNames, "LINK_IN_BATTLE") end
    if (d.btf & 0x80) ~= 0 then table.insert(flagNames, "SAFARI") end
    if (d.btf & 0x100) ~= 0 then table.insert(flagNames, "BATTLE_TOWER") end
    if (d.btf & 0x01000000) ~= 0 then table.insert(flagNames, "RECORDED") end
    table.insert(lines, string.format("    flags: %s", table.concat(flagNames, " | ")))
  end
  table.insert(lines, string.format("  gBattleTurnCounter      = %s", d.turnCounter and tostring(d.turnCounter) or "nil"))
  table.insert(lines, string.format("  gBattleOutcome          = %s", hex8(d.outcome)))
  table.insert(lines, string.format("  gBattlersCount          = %s", d.battlersCount and tostring(d.battlersCount) or "nil"))
  table.insert(lines, string.format("  gActiveBattler          = %s", d.activeBattler and tostring(d.activeBattler) or "nil"))
  table.insert(lines, string.format("  gRngValue               = %s", hex32(d.rng)))
  table.insert(lines, string.format("  gBattlescriptCurrInstr  = %s", hex32(d.bsInstr)))
  table.insert(lines, "")

  -- Exec flags
  table.insert(lines, "--- Controller Exec Flags ---")
  table.insert(lines, string.format("  gBattleControllerExecFlags = %s", hex32(d.execFlags)))
  for i = 0, 3 do
    table.insert(lines, string.format("    byte[%d] = %s  (bits: %s%s%s%s%s%s%s%s)",
      i, hex8(d.execByte[i]),
      ((d.execByte[i] or 0) & 0x80) ~= 0 and "7" or ".",
      ((d.execByte[i] or 0) & 0x40) ~= 0 and "6" or ".",
      ((d.execByte[i] or 0) & 0x20) ~= 0 and "5" or ".",
      ((d.execByte[i] or 0) & 0x10) ~= 0 and "4" or ".",
      ((d.execByte[i] or 0) & 0x08) ~= 0 and "3" or ".",
      ((d.execByte[i] or 0) & 0x04) ~= 0 and "2" or ".",
      ((d.execByte[i] or 0) & 0x02) ~= 0 and "1" or ".",
      ((d.execByte[i] or 0) & 0x01) ~= 0 and "0" or "."))
  end
  table.insert(lines, "")

  -- Controller functions
  table.insert(lines, "--- Controller Functions ---")
  for i = 0, 3 do
    table.insert(lines, string.format("  ctrl[%d] = %s", i, labelFunc(d.ctrlFuncs[i])))
  end
  table.insert(lines, "  ---")
  for i = 0, 3 do
    table.insert(lines, string.format("  endFunc[%d] = %s", i, labelFunc(d.endFuncs[i])))
  end
  table.insert(lines, "")

  -- Battler positions
  table.insert(lines, "--- Battler Positions ---")
  for i = 0, 3 do
    table.insert(lines, string.format("  position[%d] = %s", i, hex8(d.positions[i])))
  end
  table.insert(lines, "")

  -- gBattleCommunication
  table.insert(lines, "--- gBattleCommunication[0..7] ---")
  local commStr = ""
  for i = 0, 7 do
    commStr = commStr .. string.format("[%d]=%s ", i, d.comm[i] and tostring(d.comm[i]) or "?")
  end
  table.insert(lines, "  " .. commStr)
  table.insert(lines, "")

  -- BufferA command IDs
  table.insert(lines, "--- Buffer A (commands being processed) ---")
  if d.battleResourcesPtr then
    table.insert(lines, string.format("  gBattleResources ptr = %s", hex32(d.battleResourcesPtr)))
  end
  for b = 0, 1 do
    if d.bufferA[b] then
      table.insert(lines, string.format("  bufferA[%d] cmd = %s", b, labelCmd(d.bufferA[b].cmdId)))
      local bytesStr = ""
      for i = 0, 15 do
        bytesStr = bytesStr .. string.format("%02X ", d.bufferA[b].bytes[i] or 0)
      end
      table.insert(lines, string.format("    first 16 bytes: %s", bytesStr))
    else
      table.insert(lines, string.format("  bufferA[%d] = NOT READABLE (gBattleResources invalid)", b))
    end
  end
  table.insert(lines, "")

  -- BufferB
  table.insert(lines, "--- Buffer B ---")
  for b = 0, 1 do
    if d.bufferB[b] then
      local bytesStr = ""
      for i = 0, 7 do
        bytesStr = bytesStr .. string.format("%02X ", d.bufferB[b].bytes[i] or 0)
      end
      table.insert(lines, string.format("  bufferB[%d] cmd=%s bytes: %s", b, hex8(d.bufferB[b].cmdId), bytesStr))
    end
  end
  table.insert(lines, "")

  -- BattleMons
  table.insert(lines, "--- gBattleMons[0..1] ---")
  for b = 0, 1 do
    if d.mons[b] then
      local m = d.mons[b]
      table.insert(lines, string.format("  battler[%d]: species=%s hp=%s/%s lv=%s status1=%s status2=%s",
        b, hex16(m.species), m.hp and tostring(m.hp) or "?", m.maxHP and tostring(m.maxHP) or "?",
        m.level and tostring(m.level) or "?", hex32(m.status1), hex32(m.status2)))
      table.insert(lines, string.format("    atk=%s def=%s spd=%s spa=%s spd=%s",
        m.attack and tostring(m.attack) or "?",
        m.defense and tostring(m.defense) or "?",
        m.speed and tostring(m.speed) or "?",
        m.spAtk and tostring(m.spAtk) or "?",
        m.spDef and tostring(m.spDef) or "?"))
      local moveStr = ""
      for mi = 0, 3 do
        moveStr = moveStr .. string.format("%s ", hex16(m.moves[mi]))
      end
      table.insert(lines, string.format("    moves: %s", moveStr))
    end
  end
  table.insert(lines, "")

  -- Sprite IDs
  table.insert(lines, "--- Battler Sprite IDs ---")
  local sidStr = ""
  for i = 0, 3 do
    sidStr = sidStr .. string.format("[%d]=%s ", i, d.spriteIds[i] and tostring(d.spriteIds[i]) or "?")
  end
  table.insert(lines, "  " .. sidStr)
  table.insert(lines, "")

  -- Chosen actions/moves
  table.insert(lines, "--- Chosen Actions & Moves ---")
  for i = 0, 1 do
    table.insert(lines, string.format("  battler[%d]: action=%s move=%s",
      i, hex8(d.chosenAction[i]), hex16(d.chosenMove[i])))
  end
  table.insert(lines, "")

  -- gBattleSpritesDataPtr
  table.insert(lines, "--- gBattleSpritesDataPtr ---")
  table.insert(lines, string.format("  ptr = %s", hex32(d.spritesDataPtr)))
  if d.spriteSubPtrs then
    for i = 0, 3 do
      table.insert(lines, string.format("    subPtr[%d] = %s", i, hex32(d.spriteSubPtrs[i])))
    end
  end
  if d.spriteData then
    for b = 0, 1 do
      if d.spriteData[b] then
        local sdStr = ""
        for i = 0, 0x1B do
          sdStr = sdStr .. string.format("%02X ", d.spriteData[b][i] or 0)
        end
        table.insert(lines, string.format("  spriteData[%d]: %s", b, sdStr))
      end
    end
  end
  if d.healthBoxData then
    for b = 0, 1 do
      if d.healthBoxData[b] then
        local hbStr = ""
        for i = 0, 0x0B do
          hbStr = hbStr .. string.format("%02X ", d.healthBoxData[b][i] or 0)
        end
        table.insert(lines, string.format("  healthBox[%d]: %s", b, hbStr))
      end
    end
  end
  table.insert(lines, "")

  -- Stuck handler ROM bytes
  if d.stuckHandlerROM and #d.stuckHandlerROM > 0 then
    table.insert(lines, "--- Stuck Handler ROM Bytes ---")
    table.insert(lines, string.format("  ctrl[0] = %s", hex32(d.ctrlFuncs[0])))
    local romStr = ""
    for i = 0, 31 do
      if d.stuckHandlerROM[i] then
        romStr = romStr .. string.format("%02X ", d.stuckHandlerROM[i])
      end
      if i == 15 then romStr = romStr .. " | " end
    end
    table.insert(lines, string.format("  first 32 bytes at handler: %s", romStr))
    -- Try to decode first few THUMB instructions
    if d.ctrlFuncs[0] and d.ctrlFuncs[0] >= 0x08000000 then
      local romBase = (d.ctrlFuncs[0] & 0xFFFFFFFE) - 0x08000000
      table.insert(lines, "  THUMB disasm (first 8 instructions):")
      for i = 0, 7 do
        local instr = sr16(0x08000000 + romBase + i * 2)
        if instr then
          local instrStr = string.format("    %s: %04X", hex32(0x08000000 + romBase + i * 2), instr)
          -- Basic THUMB decode for common patterns
          if (instr & 0xF800) == 0x4800 then
            -- LDR Rd, [PC, #imm]
            local rd = (instr >> 8) & 0x07
            local imm = (instr & 0xFF) * 4
            local pcAddr = (0x08000000 + romBase + i * 2 + 4) & ~2
            local litVal = sr32(pcAddr + imm)
            instrStr = instrStr .. string.format("  ; LDR R%d, [PC, #0x%X] = %s", rd, imm, hex32(litVal))
          elseif (instr & 0xF800) == 0x6800 then
            instrStr = instrStr .. string.format("  ; LDR Rd, [Rn, #imm]")
          elseif (instr & 0xFF00) == 0x2800 then
            instrStr = instrStr .. string.format("  ; CMP R0, #0x%02X", instr & 0xFF)
          elseif (instr & 0xFF00) == 0x2900 then
            instrStr = instrStr .. string.format("  ; CMP R1, #0x%02X", instr & 0xFF)
          elseif (instr & 0xF000) == 0xD000 then
            local cond = (instr >> 8) & 0x0F
            local condNames = {"BEQ","BNE","BCS","BCC","BMI","BPL","BVS","BVC",
                               "BHI","BLS","BGE","BLT","BGT","BLE","BAL","SWI"}
            instrStr = instrStr .. string.format("  ; %s", condNames[cond + 1] or "B??")
          elseif (instr & 0xFF00) == 0xB500 then
            instrStr = instrStr .. "  ; PUSH {LR, ...}"
          elseif (instr & 0xFF00) == 0xBD00 then
            instrStr = instrStr .. "  ; POP {PC, ...}"
          elseif (instr & 0xFF78) == 0x4770 then
            instrStr = instrStr .. "  ; BX LR (return)"
          elseif (instr & 0xF800) == 0xF000 then
            -- BL prefix
            local next_instr = sr16(0x08000000 + romBase + (i + 1) * 2)
            if next_instr and (next_instr & 0xF800) == 0xF800 then
              local offset_hi = (instr & 0x7FF) << 12
              local offset_lo = (next_instr & 0x7FF) << 1
              local target = 0x08000000 + romBase + i * 2 + 4 + offset_hi + offset_lo
              if (offset_hi & 0x400000) ~= 0 then target = target - 0x800000 end
              instrStr = instrStr .. string.format("  ; BL %s", labelFunc(target | 1))
            end
          end
          table.insert(lines, instrStr)
        end
      end
    end
  end
  table.insert(lines, "")

  -- Turn order
  table.insert(lines, "--- Turn Order ---")
  local toStr = ""
  for i = 0, 3 do
    local v = sr8(ADDR.gBattlerByTurnOrder + i)
    toStr = toStr .. string.format("[%d]=%s ", i, v and tostring(v) or "?")
  end
  table.insert(lines, "  gBattlerByTurnOrder: " .. toStr)
  table.insert(lines, "")

  return table.concat(lines, "\n")
end

-- ============================================================
-- Frame callback
-- ============================================================

local allOutput = {}

callbacks:add("frame", function()
  frameCount = frameCount + 1

  -- Take screenshot at frame 1
  if frameCount == 1 then
    pcall(function() emu:screenshot("diag_stuck_f0000.png") end)
    console:log("[DIAG_STUCK] Screenshot taken at frame 0")
    console:log("[DIAG_STUCK] Starting stuck handler diagnostic (300 frames, log every 30)")
    console:log("")
  end

  -- Log at frame 1 and every LOG_INTERVAL frames
  if frameCount == 1 or frameCount % LOG_INTERVAL == 0 then
    local diag = collectDiagnostics(frameCount)
    local formatted = formatDiag(diag)

    -- Print to console
    for line in formatted:gmatch("[^\n]+") do
      console:log(line)
    end

    table.insert(allOutput, formatted)
    table.insert(results, diag)

    -- Take screenshot every 60 frames
    if frameCount % 60 == 0 then
      local name = string.format("diag_stuck_f%04d.png", frameCount)
      pcall(function() emu:screenshot(name) end)
      console:log(string.format("[DIAG_STUCK] Screenshot: %s", name))
    end
  end

  -- Done
  if frameCount >= MAX_FRAMES then
    console:log("")
    console:log("========================================")
    console:log("[DIAG_STUCK] DIAGNOSTIC COMPLETE")
    console:log("========================================")

    -- Summary: check if values changed between first and last sample
    if #results >= 2 then
      local first = results[1]
      local last = results[#results]

      console:log("")
      console:log("--- CHANGE ANALYSIS (first vs last frame) ---")

      -- Did bmf change?
      if first.bmf ~= last.bmf then
        console:log(string.format("  gBattleMainFunc CHANGED: %s -> %s", labelFunc(first.bmf), labelFunc(last.bmf)))
      else
        console:log(string.format("  gBattleMainFunc STUCK at %s", labelFunc(first.bmf)))
      end

      -- Did exec flags change?
      if first.execFlags ~= last.execFlags then
        console:log(string.format("  execFlags CHANGED: %s -> %s", hex32(first.execFlags), hex32(last.execFlags)))
      else
        console:log(string.format("  execFlags STUCK at %s", hex32(first.execFlags)))
      end

      -- Did ctrl[0] change?
      if first.ctrlFuncs[0] ~= last.ctrlFuncs[0] then
        console:log(string.format("  ctrl[0] CHANGED: %s -> %s", labelFunc(first.ctrlFuncs[0]), labelFunc(last.ctrlFuncs[0])))
      else
        console:log(string.format("  ctrl[0] STUCK at %s", labelFunc(first.ctrlFuncs[0])))
      end

      -- Did activeBattler change?
      local abChanged = false
      for i = 1, #results - 1 do
        if results[i].activeBattler ~= results[i + 1].activeBattler then
          abChanged = true
          break
        end
      end
      console:log(string.format("  gActiveBattler: %s (first=%s, last=%s)",
        abChanged and "CHANGED" or "STUCK",
        first.activeBattler and tostring(first.activeBattler) or "?",
        last.activeBattler and tostring(last.activeBattler) or "?"))

      -- Did RNG change? (confirms emulation is running)
      if first.rng ~= last.rng then
        console:log("  RNG: ADVANCING (emulation running)")
      else
        console:log("  RNG: STUCK (emulation may be frozen!)")
      end

      -- Did comm change?
      local commChanged = false
      for i = 0, 7 do
        if first.comm[i] ~= last.comm[i] then
          commChanged = true
          break
        end
      end
      console:log(string.format("  gBattleCommunication: %s", commChanged and "CHANGED" or "STATIC"))

      -- Did bufferA[0] cmd change?
      if first.bufferA[0] and last.bufferA[0] then
        if first.bufferA[0].cmdId ~= last.bufferA[0].cmdId then
          console:log(string.format("  bufferA[0] cmd CHANGED: %s -> %s",
            labelCmd(first.bufferA[0].cmdId), labelCmd(last.bufferA[0].cmdId)))
        else
          console:log(string.format("  bufferA[0] cmd STUCK at %s", labelCmd(first.bufferA[0].cmdId)))
        end
      end

      -- HP changes
      if first.mons[0] and last.mons[0] then
        if first.mons[0].hp ~= last.mons[0].hp then
          console:log(string.format("  Mon[0] HP CHANGED: %d -> %d", first.mons[0].hp or 0, last.mons[0].hp or 0))
        end
      end
      if first.mons[1] and last.mons[1] then
        if first.mons[1].hp ~= last.mons[1].hp then
          console:log(string.format("  Mon[1] HP CHANGED: %d -> %d", first.mons[1].hp or 0, last.mons[1].hp or 0))
        end
      end
    end

    -- Write full output to file
    local outputFile = "diag_stuck_results.txt"
    local fullText = table.concat(allOutput, "\n\n")
    local f = io.open(outputFile, "w")
    if f then
      f:write(fullText)
      f:write("\n\n")
      f:write("=== DONE ===\n")
      f:close()
      console:log(string.format("[DIAG_STUCK] Results written to %s", outputFile))
    else
      console:log("[DIAG_STUCK] WARNING: Could not write results file")
    end

    -- Final screenshot
    pcall(function() emu:screenshot("diag_stuck_final.png") end)
    console:log("[DIAG_STUCK] Final screenshot taken")
    console:log("[DIAG_STUCK] Script complete. Review console output and diag_stuck_results.txt")
  end
end)

console:log("[DIAG_STUCK] Stuck handler diagnostic loaded")
console:log("[DIAG_STUCK] Will run for 300 frames, logging every 30 frames")
console:log("[DIAG_STUCK] Addresses configured for Pokemon Run & Bun")
console:log("")
