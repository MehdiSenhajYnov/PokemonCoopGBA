--[[
  test_battle_init.lua — Comprehensive PvP Battle Init Chain Diagnostic

  Tests the full battle initialization chain step by step:
    CB2_InitBattle -> CB2_InitBattleInternal -> CB2_HandleStartBattle -> BattleMainCB2

  Steps:
    1. Read gPlayerParty and copy to gEnemyParty (self-battle)
    2. Set gBattleTypeFlags = LINK | TRAINER
    3. Apply all ROM patches (GetMultiplayerId, IsLinkTaskFinished, etc.)
    4. Set IWRAM vars (gWirelessCommType, gReceivedRemoteLinkPlayers, gBlockReceivedStatus)
    5. Set savedCallback, NULL callback1, reset gMain.state
    6. Set callback2 = CB2_InitBattle
    7. Monitor 600 frames (10 seconds) logging transitions
    8. Restore all patches

  Run in mGBA: Tools > Scripting > Load this script
  Requires: ROM loaded and in overworld (walking around)

  IMPORTANT: This will trigger a real battle! Save state first.
]]

-- ============================================================
-- Configuration (hardcoded from config/run_and_bun.lua)
-- ============================================================

local CFG = {
  -- Party addresses
  gPlayerParty      = 0x02023A98,
  gPlayerPartyCount = 0x02023A95,
  gEnemyParty       = 0x02023CF0,
  gEnemyPartyCount  = 0x02023CED,

  -- Battle state
  gBattleTypeFlags  = 0x02023364,
  gMainInBattle     = 0x020206AE,
  CB2_BattleMain    = 0x08094815,

  -- gMain addresses
  gMainBase         = 0x02020648,    -- gMain base (callback2Addr - 4)
  callback1Addr     = 0x02020648,    -- gMain + 0x00
  callback2Addr     = 0x0202064C,    -- gMain + 0x04
  savedCallbackAddr = 0x02020650,    -- gMain + 0x08
  gMainStateAddr    = 0x020206AD,    -- gMain + 0x65

  -- Warp system
  cb2Overworld      = 0x080A89A5,

  -- Link Battle addresses
  CB2_InitBattle    = 0x080363C1,
  CB2_HandleStartBattle = 0x08037B45,
  GetMultiplayerId  = 0x0800A4B1,    -- THUMB address (cart0 offset = 0x00A4B0)

  -- IWRAM vars
  gWirelessCommType          = 0x030030FC,
  gReceivedRemoteLinkPlayers = 0x03003124,
  gBlockReceivedStatus       = 0x0300307C,

  -- EWRAM vars
  gBattleCommunication = 0x0202370E,
  gBattleResources     = 0x02023A18,
  gActiveBattler       = 0x020233E0,
  gBattleControllerExecFlags = 0x020233DC,

  -- Battle type flags
  BATTLE_TYPE_LINK    = 0x00000002,
  BATTLE_TYPE_IS_MASTER = 0x00000004,
  BATTLE_TYPE_TRAINER = 0x00000008,

  -- Pokemon struct
  PARTY_SIZE      = 600,
  POKEMON_SIZE    = 100,
  HP_OFFSET       = 86,

  -- ROM patches (cart0 offsets)
  patches = {
    getMultiplayerId = {
      romOffset = 0x00A4B0,
      -- Master: MOV R0,#0 (0x2000) then BX LR (0x4770)
      value1 = 0x2000,  -- write16 at offset
      value2 = 0x4770,  -- write16 at offset+2
    },
    isLinkTaskFinished = {
      romOffset = 0x0A568,
      value = 0x47702001,  -- MOV R0,#1; BX LR
      size = 4,
    },
    getBlockReceivedStatus = {
      romOffset = 0x0A598,
      value = 0x4770200F,  -- MOV R0,#15; BX LR
      size = 4,
    },
    playerBufExecSkip = {
      romOffset = 0x06F0D4 + 0x1C,  -- 0x06F0F0
      value = 0xE01C,               -- BEQ -> B (unconditional)
      size = 2,
    },
    linkOpponentBufExecSkip = {
      romOffset = 0x078788 + 0x1C,  -- 0x0787A4
      value = 0xE01C,
      size = 2,
    },
    prepBufTransferSkip = {
      romOffset = 0x032FA8 + 0x18,  -- 0x032FC0
      value = 0xE008,
      size = 2,
    },
  },
}

-- ============================================================
-- Memory helpers
-- ============================================================

local function toWRAMOffset(addr)
  return addr - 0x02000000
end

local function toIWRAMOffset(addr)
  return addr - 0x03000000
end

local function isIWRAM(addr)
  return addr >= 0x03000000 and addr < 0x03008000
end

local function read8(addr)
  if isIWRAM(addr) then
    return emu.memory.iwram:read8(toIWRAMOffset(addr))
  else
    return emu.memory.wram:read8(toWRAMOffset(addr))
  end
end

local function read16(addr)
  if isIWRAM(addr) then
    return emu.memory.iwram:read16(toIWRAMOffset(addr))
  else
    return emu.memory.wram:read16(toWRAMOffset(addr))
  end
end

local function read32(addr)
  if isIWRAM(addr) then
    return emu.memory.iwram:read32(toIWRAMOffset(addr))
  else
    return emu.memory.wram:read32(toWRAMOffset(addr))
  end
end

local function write8(addr, val)
  if isIWRAM(addr) then
    emu.memory.iwram:write8(toIWRAMOffset(addr), val)
  else
    emu.memory.wram:write8(toWRAMOffset(addr), val)
  end
end

local function write16(addr, val)
  if isIWRAM(addr) then
    emu.memory.iwram:write16(toIWRAMOffset(addr), val)
  else
    emu.memory.wram:write16(toWRAMOffset(addr), val)
  end
end

local function write32(addr, val)
  if isIWRAM(addr) then
    emu.memory.iwram:write32(toIWRAMOffset(addr), val)
  else
    emu.memory.wram:write32(toWRAMOffset(addr), val)
  end
end

-- Safe pcall wrappers that return value or nil
local function safeRead8(addr)
  local ok, val = pcall(read8, addr)
  return ok and val or nil
end

local function safeRead16(addr)
  local ok, val = pcall(read16, addr)
  return ok and val or nil
end

local function safeRead32(addr)
  local ok, val = pcall(read32, addr)
  return ok and val or nil
end

local function safeWrite8(addr, val)
  local ok = pcall(write8, addr, val)
  return ok
end

local function safeWrite16(addr, val)
  local ok = pcall(write16, addr, val)
  return ok
end

local function safeWrite32(addr, val)
  local ok = pcall(write32, addr, val)
  return ok
end

-- ROM read/write helpers (cart0)
local function romRead16(offset)
  local ok, val = pcall(function() return emu.memory.cart0:read16(offset) end)
  return ok and val or nil
end

local function romRead32(offset)
  local ok, val = pcall(function() return emu.memory.cart0:read32(offset) end)
  return ok and val or nil
end

local function romWrite16(offset, val)
  local ok = pcall(function() emu.memory.cart0:write16(offset, val) end)
  return ok
end

local function romWrite32(offset, val)
  local ok = pcall(function() emu.memory.cart0:write32(offset, val) end)
  return ok
end

-- Verify ROM write: write then read back
local function romWriteVerify16(offset, val)
  if not romWrite16(offset, val) then return false end
  local rb = romRead16(offset)
  return rb == val
end

local function romWriteVerify32(offset, val)
  if not romWrite32(offset, val) then return false end
  local rb = romRead32(offset)
  return rb == val
end

-- ============================================================
-- Logging
-- ============================================================

local LOG = {}

local function log(msg)
  local line = string.format("[BattleInit] %s", msg)
  console:log(line)
  table.insert(LOG, line)
end

local function logf(fmt, ...)
  log(string.format(fmt, ...))
end

local function hex(val)
  if val == nil then return "nil" end
  return string.format("0x%08X", val)
end

local function hex16(val)
  if val == nil then return "nil" end
  return string.format("0x%04X", val)
end

-- ============================================================
-- Saved original values for restoration
-- ============================================================

local originals = {
  rom = {},          -- { {offset, value, size}, ... }
  callback1 = nil,
  callback2 = nil,
  savedCallback = nil,
  gMainState = nil,
  gBattleTypeFlags = nil,
  gWirelessCommType = nil,
  gReceivedRemoteLinkPlayers = nil,
  gBlockReceivedStatus = {},  -- [0..3]
  gBattleCommunication0 = nil,
}

-- ============================================================
-- Step 0: Pre-flight checks
-- ============================================================

local function step0_preflight()
  log("========================================")
  log("STEP 0: Pre-flight checks")
  log("========================================")

  -- Check that we can read memory
  local cb2 = safeRead32(CFG.callback2Addr)
  if not cb2 then
    log("FAIL: Cannot read callback2 - is ROM loaded?")
    return false
  end
  logf("callback2 = %s", hex(cb2))

  -- Check we are in overworld
  if cb2 == CFG.cb2Overworld then
    log("OK: In overworld (callback2 = CB2_Overworld)")
  else
    logf("WARNING: callback2 is NOT CB2_Overworld (%s). Expected %s", hex(cb2), hex(CFG.cb2Overworld))
    logf("Proceeding anyway, but results may be unexpected.")
  end

  -- Check inBattle
  local inBattle = safeRead8(CFG.gMainInBattle)
  logf("inBattle = %s", tostring(inBattle))
  if inBattle and inBattle ~= 0 then
    log("FAIL: Already in battle! Wait until overworld.")
    return false
  end

  -- Check player party
  local partyCount = safeRead8(CFG.gPlayerPartyCount)
  logf("gPlayerPartyCount = %s", tostring(partyCount))
  if not partyCount or partyCount == 0 or partyCount > 6 then
    logf("FAIL: Invalid party count (%s). Are you in-game?", tostring(partyCount))
    return false
  end

  -- Read first Pokemon personality to check validity
  local personality = safeRead32(CFG.gPlayerParty)
  logf("gPlayerParty[0].personality = %s", hex(personality))
  if not personality or personality == 0 then
    log("WARNING: First Pokemon personality is 0 - party may be empty")
  end

  -- Check first Pokemon HP
  local hp = safeRead16(CFG.gPlayerParty + CFG.HP_OFFSET)
  logf("gPlayerParty[0].hp = %s", tostring(hp))
  if not hp or hp == 0 then
    log("WARNING: First Pokemon HP is 0 - it may be fainted")
  end

  -- Check ROM write capability
  local testOff = 0x00A4B0
  local origVal = romRead16(testOff)
  logf("ROM test read at 0x%06X = %s", testOff, hex16(origVal))

  log("OK: Pre-flight checks passed")
  return true
end

-- ============================================================
-- Step 1: Copy player party to enemy party
-- ============================================================

local function step1_copyParty()
  log("========================================")
  log("STEP 1: Copy gPlayerParty -> gEnemyParty")
  log("========================================")

  local partyCount = safeRead8(CFG.gPlayerPartyCount)
  logf("Player party count: %d", partyCount or 0)

  -- Read entire player party (600 bytes)
  local partyData = {}
  local baseRead = toWRAMOffset(CFG.gPlayerParty)
  local okRead = pcall(function()
    for i = 0, CFG.PARTY_SIZE - 1 do
      partyData[i + 1] = emu.memory.wram:read8(baseRead + i)
    end
  end)

  if not okRead or #partyData ~= CFG.PARTY_SIZE then
    logf("FAIL: Could not read gPlayerParty (got %d bytes)", #partyData)
    return false, nil
  end
  logf("Read %d bytes from gPlayerParty (0x%08X)", #partyData, CFG.gPlayerParty)

  -- Log first 3 Pokemon summaries
  for i = 0, math.min(partyCount - 1, 2) do
    local off = i * CFG.POKEMON_SIZE
    local p = partyData[off + 1] + partyData[off + 2] * 256
              + partyData[off + 3] * 65536 + partyData[off + 4] * 16777216
    local hp = partyData[off + CFG.HP_OFFSET + 1] + partyData[off + CFG.HP_OFFSET + 2] * 256
    logf("  Party[%d]: personality=%s HP=%d", i, hex(p), hp)
  end

  -- Write to gEnemyParty
  local baseWrite = toWRAMOffset(CFG.gEnemyParty)
  local okWrite = pcall(function()
    for i = 1, CFG.PARTY_SIZE do
      emu.memory.wram:write8(baseWrite + i - 1, partyData[i])
    end
  end)

  if not okWrite then
    log("FAIL: Could not write to gEnemyParty")
    return false, nil
  end
  logf("Wrote %d bytes to gEnemyParty (0x%08X)", CFG.PARTY_SIZE, CFG.gEnemyParty)

  -- Set gEnemyPartyCount
  safeWrite8(CFG.gEnemyPartyCount, partyCount)
  local verify = safeRead8(CFG.gEnemyPartyCount)
  logf("gEnemyPartyCount: wrote %d, readback %s", partyCount, tostring(verify))

  -- Verify first enemy Pokemon personality matches
  local enemyP = safeRead32(CFG.gEnemyParty)
  local playerP = safeRead32(CFG.gPlayerParty)
  if enemyP == playerP then
    logf("OK: Enemy party personality matches player (%s)", hex(enemyP))
  else
    logf("WARNING: Mismatch! player=%s enemy=%s", hex(playerP), hex(enemyP))
  end

  log("OK: Party copied successfully")
  return true, partyData
end

-- ============================================================
-- Step 2: Set gBattleTypeFlags
-- ============================================================

local function step2_battleFlags()
  log("========================================")
  log("STEP 2: Set gBattleTypeFlags")
  log("========================================")

  -- Save original
  originals.gBattleTypeFlags = safeRead32(CFG.gBattleTypeFlags)
  logf("Original gBattleTypeFlags = %s", hex(originals.gBattleTypeFlags))

  -- Set LINK | TRAINER (master)
  local flags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER
  -- flags = 0x02 | 0x08 | 0x04 = 0x0E
  logf("Setting gBattleTypeFlags = %s (LINK|TRAINER|IS_MASTER)", hex(flags))

  safeWrite32(CFG.gBattleTypeFlags, flags)
  local verify = safeRead32(CFG.gBattleTypeFlags)
  if verify == flags then
    logf("OK: gBattleTypeFlags = %s (verified)", hex(verify))
  else
    logf("FAIL: Write verification failed (expected %s, got %s)", hex(flags), hex(verify))
    return false
  end

  return true
end

-- ============================================================
-- Step 3: Apply ROM patches
-- ============================================================

local function step3_romPatches()
  log("========================================")
  log("STEP 3: Apply ROM patches")
  log("========================================")

  originals.rom = {}
  local patchCount = 0
  local failCount = 0

  -- 3a. GetMultiplayerId: MOV R0,#0; BX LR (master mode)
  local gmid = CFG.patches.getMultiplayerId
  local orig1 = romRead16(gmid.romOffset)
  local orig2 = romRead16(gmid.romOffset + 2)
  logf("GetMultiplayerId at cart0 0x%06X: original = %s %s",
    gmid.romOffset, hex16(orig1), hex16(orig2))

  if romWriteVerify16(gmid.romOffset, gmid.value1) then
    table.insert(originals.rom, { offset = gmid.romOffset, value = orig1, size = 2 })
    patchCount = patchCount + 1
    logf("  Wrote MOV R0,#0 (0x2000) -> OK")
  else
    logf("  FAIL: Could not write MOV R0,#0")
    failCount = failCount + 1
  end

  if romWriteVerify16(gmid.romOffset + 2, gmid.value2) then
    table.insert(originals.rom, { offset = gmid.romOffset + 2, value = orig2, size = 2 })
    patchCount = patchCount + 1
    logf("  Wrote BX LR (0x4770) -> OK")
  else
    logf("  FAIL: Could not write BX LR")
    failCount = failCount + 1
  end

  -- 3b. IsLinkTaskFinished: MOV R0,#1; BX LR
  local iltf = CFG.patches.isLinkTaskFinished
  local origILTF = romRead32(iltf.romOffset)
  logf("IsLinkTaskFinished at cart0 0x%06X: original = %s", iltf.romOffset, hex(origILTF))

  if romWriteVerify32(iltf.romOffset, iltf.value) then
    table.insert(originals.rom, { offset = iltf.romOffset, value = origILTF, size = 4 })
    patchCount = patchCount + 1
    logf("  Wrote 0x47702001 (MOV R0,#1; BX LR) -> OK")
  else
    logf("  FAIL: Could not write IsLinkTaskFinished patch")
    failCount = failCount + 1
  end

  -- 3c. GetBlockReceivedStatus: MOV R0,#15; BX LR
  local gbrs = CFG.patches.getBlockReceivedStatus
  local origGBRS = romRead32(gbrs.romOffset)
  logf("GetBlockReceivedStatus at cart0 0x%06X: original = %s", gbrs.romOffset, hex(origGBRS))

  if romWriteVerify32(gbrs.romOffset, gbrs.value) then
    table.insert(originals.rom, { offset = gbrs.romOffset, value = origGBRS, size = 4 })
    patchCount = patchCount + 1
    logf("  Wrote 0x4770200F (MOV R0,#15; BX LR) -> OK")
  else
    logf("  FAIL: Could not write GetBlockReceivedStatus patch")
    failCount = failCount + 1
  end

  -- 3d. PlayerBufferExecCompleted +0x1C: BEQ -> B
  local pbec = CFG.patches.playerBufExecSkip
  local origPBEC = romRead16(pbec.romOffset)
  logf("PlayerBufExecSkip at cart0 0x%06X: original = %s", pbec.romOffset, hex16(origPBEC))

  if romWriteVerify16(pbec.romOffset, pbec.value) then
    table.insert(originals.rom, { offset = pbec.romOffset, value = origPBEC, size = 2 })
    patchCount = patchCount + 1
    logf("  Wrote 0xE01C (BEQ -> B) -> OK")
  else
    logf("  FAIL: Could not write PlayerBufExecSkip patch")
    failCount = failCount + 1
  end

  -- 3e. LinkOpponentBufferExecCompleted +0x1C: BEQ -> B
  local lobec = CFG.patches.linkOpponentBufExecSkip
  local origLOBEC = romRead16(lobec.romOffset)
  logf("LinkOpponentBufExecSkip at cart0 0x%06X: original = %s", lobec.romOffset, hex16(origLOBEC))

  if romWriteVerify16(lobec.romOffset, lobec.value) then
    table.insert(originals.rom, { offset = lobec.romOffset, value = origLOBEC, size = 2 })
    patchCount = patchCount + 1
    logf("  Wrote 0xE01C (BEQ -> B) -> OK")
  else
    logf("  FAIL: Could not write LinkOpponentBufExecSkip patch")
    failCount = failCount + 1
  end

  -- 3f. PrepareBufferDataTransferLink +0x18: BEQ -> B
  local pbtl = CFG.patches.prepBufTransferSkip
  local origPBTL = romRead16(pbtl.romOffset)
  logf("PrepBufTransferSkip at cart0 0x%06X: original = %s", pbtl.romOffset, hex16(origPBTL))

  if romWriteVerify16(pbtl.romOffset, pbtl.value) then
    table.insert(originals.rom, { offset = pbtl.romOffset, value = origPBTL, size = 2 })
    patchCount = patchCount + 1
    logf("  Wrote 0xE008 (BEQ -> B) -> OK")
  else
    logf("  FAIL: Could not write PrepBufTransferSkip patch")
    failCount = failCount + 1
  end

  logf("ROM patches: %d applied, %d failed, %d saved for restore", patchCount, failCount, #originals.rom)

  if failCount > 0 then
    log("WARNING: Some ROM patches failed. Battle may not work correctly.")
  end

  return failCount == 0
end

-- ============================================================
-- Step 4: Set IWRAM variables
-- ============================================================

local function step4_iwramVars()
  log("========================================")
  log("STEP 4: Set IWRAM variables")
  log("========================================")

  -- Save originals
  originals.gWirelessCommType = safeRead8(CFG.gWirelessCommType)
  originals.gReceivedRemoteLinkPlayers = safeRead8(CFG.gReceivedRemoteLinkPlayers)
  for i = 0, 3 do
    originals.gBlockReceivedStatus[i] = safeRead8(CFG.gBlockReceivedStatus + i)
  end

  logf("Original gWirelessCommType = %s", tostring(originals.gWirelessCommType))
  logf("Original gReceivedRemoteLinkPlayers = %s", tostring(originals.gReceivedRemoteLinkPlayers))
  logf("Original gBlockReceivedStatus = [%s, %s, %s, %s]",
    tostring(originals.gBlockReceivedStatus[0]),
    tostring(originals.gBlockReceivedStatus[1]),
    tostring(originals.gBlockReceivedStatus[2]),
    tostring(originals.gBlockReceivedStatus[3]))

  -- gWirelessCommType = 0 (wired mode)
  safeWrite8(CFG.gWirelessCommType, 0)
  local v1 = safeRead8(CFG.gWirelessCommType)
  logf("gWirelessCommType = %d (wrote 0, readback %s)", 0, tostring(v1))

  -- gReceivedRemoteLinkPlayers = 1 (skip link handshake)
  safeWrite8(CFG.gReceivedRemoteLinkPlayers, 1)
  local v2 = safeRead8(CFG.gReceivedRemoteLinkPlayers)
  logf("gReceivedRemoteLinkPlayers = %d (wrote 1, readback %s)", 1, tostring(v2))

  -- gBlockReceivedStatus[0..3] = 0x0F (all blocks received)
  for i = 0, 3 do
    safeWrite8(CFG.gBlockReceivedStatus + i, 0x0F)
  end
  local v3 = {}
  for i = 0, 3 do
    v3[i] = safeRead8(CFG.gBlockReceivedStatus + i)
  end
  logf("gBlockReceivedStatus = [0x%02X, 0x%02X, 0x%02X, 0x%02X]",
    v3[0] or 0, v3[1] or 0, v3[2] or 0, v3[3] or 0)

  log("OK: IWRAM variables set")
  return true
end

-- ============================================================
-- Step 5: Set gMain fields (savedCallback, callback1, state)
-- ============================================================

local function step5_gMainSetup()
  log("========================================")
  log("STEP 5: Set gMain fields")
  log("========================================")

  -- 5a. Set savedCallback = CB2_Overworld (so battle returns to overworld)
  originals.savedCallback = safeRead32(CFG.savedCallbackAddr)
  logf("Original savedCallback (gMain+0x08) = %s", hex(originals.savedCallback))

  safeWrite32(CFG.savedCallbackAddr, CFG.cb2Overworld)
  local vsc = safeRead32(CFG.savedCallbackAddr)
  logf("savedCallback = %s (wrote CB2_Overworld, readback %s)", hex(CFG.cb2Overworld), hex(vsc))

  -- 5b. Save callback1 then set to NULL
  originals.callback1 = safeRead32(CFG.callback1Addr)
  logf("Original callback1 (gMain+0x00) = %s", hex(originals.callback1))

  safeWrite32(CFG.callback1Addr, 0)
  local vcb1 = safeRead32(CFG.callback1Addr)
  logf("callback1 = 0x00000000 (NULL, readback %s)", hex(vcb1))

  -- 5c. Set gMain.state = 0
  originals.gMainState = safeRead8(CFG.gMainStateAddr)
  logf("Original gMain.state (gMain+0x65) = %d", originals.gMainState or 0)

  safeWrite8(CFG.gMainStateAddr, 0)
  local vst = safeRead8(CFG.gMainStateAddr)
  logf("gMain.state = 0 (readback %s)", tostring(vst))

  -- 5d. Clear gBattleCommunication[0]
  originals.gBattleCommunication0 = safeRead8(CFG.gBattleCommunication)
  safeWrite8(CFG.gBattleCommunication, 0)
  logf("gBattleCommunication[0] = 0 (readback %s)", tostring(safeRead8(CFG.gBattleCommunication)))

  log("OK: gMain fields configured")
  return true
end

-- ============================================================
-- Step 6: Trigger battle (set callback2 = CB2_InitBattle)
-- ============================================================

local function step6_trigger()
  log("========================================")
  log("STEP 6: Set callback2 = CB2_InitBattle")
  log("========================================")

  originals.callback2 = safeRead32(CFG.callback2Addr)
  logf("Original callback2 = %s", hex(originals.callback2))

  -- Blank screen first (fill palette with black)
  logf("Blanking screen (filling palette RAM with 0)...")
  pcall(function()
    -- Palette RAM: 0x05000000 mapped as emu.memory.palette
    -- BG palette: 512 bytes, OBJ palette: 512 bytes
    for i = 0, 511, 2 do
      emu.memory.palette:write16(i, 0x0000)
    end
  end)

  -- Set callback2 = CB2_InitBattle
  safeWrite32(CFG.callback2Addr, CFG.CB2_InitBattle)
  local vcb2 = safeRead32(CFG.callback2Addr)

  if vcb2 == CFG.CB2_InitBattle then
    logf("OK: callback2 = %s (CB2_InitBattle, verified)", hex(vcb2))
  else
    logf("FAIL: callback2 write failed (expected %s, got %s)", hex(CFG.CB2_InitBattle), hex(vcb2))
    return false
  end

  logf(">>> BATTLE TRIGGERED! Monitoring for 600 frames (10 seconds)...")
  return true
end

-- ============================================================
-- Monitoring state
-- ============================================================

local monitor = {
  active = false,
  frameCount = 0,
  maxFrames = 600,
  partyData = nil,      -- saved party data for re-injection
  prevCb2 = nil,
  prevInBattle = nil,
  prevComm0 = nil,
  transitions = {},     -- log of transitions
  success = false,
  battleMainReached = false,
  inBattleTriggered = false,
  firstBattleCb2Frame = nil,
  cb2History = {},      -- track unique cb2 values and when they first appeared
  frameCallbackId = nil,
}

-- Known callback2 addresses for labeling
local CB2_LABELS = {
  [CFG.CB2_InitBattle]         = "CB2_InitBattle",
  [CFG.CB2_HandleStartBattle]  = "CB2_HandleStartBattle",
  [CFG.CB2_BattleMain]         = "BattleMainCB2",
  [CFG.cb2Overworld]           = "CB2_Overworld",
  [0x0803648D]                 = "CB2_InitBattleInternal",
}

local function labelCb2(val)
  if not val then return "nil" end
  local label = CB2_LABELS[val]
  if label then
    return string.format("%s (%s)", hex(val), label)
  end
  return hex(val)
end

-- ============================================================
-- Frame callback (monitoring loop)
-- ============================================================

local function onFrame()
  if not monitor.active then return end

  monitor.frameCount = monitor.frameCount + 1
  local f = monitor.frameCount

  -- Read current state
  local cb2 = safeRead32(CFG.callback2Addr)
  local inBattle = safeRead8(CFG.gMainInBattle)
  local comm0 = safeRead8(CFG.gBattleCommunication)
  local gMainState = safeRead8(CFG.gMainStateAddr)

  -- Track callback2 transitions
  if cb2 ~= monitor.prevCb2 then
    local msg = string.format("frame %d: callback2 CHANGED %s -> %s",
      f, labelCb2(monitor.prevCb2), labelCb2(cb2))
    logf(">>> %s", msg)
    table.insert(monitor.transitions, msg)

    -- Track unique cb2 values
    if cb2 and not monitor.cb2History[cb2] then
      monitor.cb2History[cb2] = f
    end

    monitor.prevCb2 = cb2
  end

  -- Track inBattle transitions
  if inBattle ~= monitor.prevInBattle then
    local msg = string.format("frame %d: inBattle CHANGED %s -> %s",
      f, tostring(monitor.prevInBattle), tostring(inBattle))
    logf(">>> %s", msg)
    table.insert(monitor.transitions, msg)

    if inBattle == 1 and (monitor.prevInBattle == 0 or monitor.prevInBattle == nil) then
      monitor.inBattleTriggered = true
    end

    monitor.prevInBattle = inBattle
  end

  -- Track gBattleCommunication[0] changes
  if comm0 ~= monitor.prevComm0 then
    local msg = string.format("frame %d: gBattleCommunication[0] CHANGED %s -> %s",
      f, tostring(monitor.prevComm0), tostring(comm0))
    logf(">>> %s", msg)
    table.insert(monitor.transitions, msg)
    monitor.prevComm0 = comm0
  end

  -- Check for BattleMainCB2
  if cb2 == CFG.CB2_BattleMain and not monitor.battleMainReached then
    monitor.battleMainReached = true
    monitor.firstBattleCb2Frame = f
    logf("***** SUCCESS: BattleMainCB2 reached at frame %d! *****", f)
    -- Take screenshot at this critical moment
    pcall(function()
      local src = debug.getinfo(1, "S").source:sub(2)
      local dir = src:match("(.*/)")
      if not dir then dir = src:match("(.*\\)") end
      local ssPath = (dir or "") .. "../../battle_main_reached.png"
      emu:screenshot(ssPath)
    end)
  end

  -- Re-inject enemy party every 10 frames (counter Case 7 overwrite)
  if f % 10 == 0 and monitor.partyData then
    local baseWrite = toWRAMOffset(CFG.gEnemyParty)
    pcall(function()
      for i = 1, CFG.PARTY_SIZE do
        emu.memory.wram:write8(baseWrite + i - 1, monitor.partyData[i])
      end
    end)
    -- Also re-inject party count
    pcall(function()
      local playerCount = read8(CFG.gPlayerPartyCount)
      write8(CFG.gEnemyPartyCount, playerCount)
    end)
  end

  -- Maintain IWRAM vars every 10 frames
  if f % 10 == 0 then
    safeWrite8(CFG.gWirelessCommType, 0)
    safeWrite8(CFG.gReceivedRemoteLinkPlayers, 1)
    for i = 0, 3 do
      safeWrite8(CFG.gBlockReceivedStatus + i, 0x0F)
    end
  end

  -- Maintain gBattleTypeFlags during first 60 frames
  if f <= 60 then
    local flags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER
    safeWrite32(CFG.gBattleTypeFlags, flags)
  end

  -- Periodic logging every 10 frames
  if f % 10 == 0 then
    -- Read extra diagnostic values
    local btf = safeRead32(CFG.gBattleTypeFlags)
    local gBattleRes = safeRead32(CFG.gBattleResources)
    local activeBattler = safeRead8(CFG.gActiveBattler)
    local execFlags = safeRead32(CFG.gBattleControllerExecFlags)

    logf("  [f=%3d] cb2=%s inBattle=%s st=%s comm0=%s btf=%s res=%s aB=%s exF=%s",
      f,
      labelCb2(cb2),
      tostring(inBattle),
      tostring(gMainState),
      tostring(comm0),
      hex(btf),
      hex(gBattleRes),
      tostring(activeBattler),
      hex(execFlags))
  end

  -- End monitoring
  if f >= monitor.maxFrames then
    monitor.active = false
    logf("Monitoring complete after %d frames", f)
    finishMonitoring()
  end
end

-- ============================================================
-- Finish monitoring and restore
-- ============================================================

function finishMonitoring()
  log("========================================")
  log("STEP 7: Results and Restore")
  log("========================================")

  -- Summary
  logf("Total frames monitored: %d", monitor.frameCount)
  logf("Transitions recorded: %d", #monitor.transitions)

  log("")
  log("--- Callback2 History ---")
  for val, frame in pairs(monitor.cb2History) do
    logf("  %s first seen at frame %d", labelCb2(val), frame)
  end

  log("")
  log("--- All Transitions ---")
  for _, t in ipairs(monitor.transitions) do
    logf("  %s", t)
  end

  log("")
  if monitor.battleMainReached then
    logf("RESULT: **SUCCESS** - BattleMainCB2 reached at frame %d", monitor.firstBattleCb2Frame or -1)
    logf("  The battle engine is running! All patches working correctly.")
    log("  The battle should be playable (self-battle: your party vs clone).")
  elseif monitor.inBattleTriggered then
    log("RESULT: **PARTIAL** - inBattle=1 detected but BattleMainCB2 never reached")
    log("  Battle init started but may be stuck in CB2_HandleStartBattle cases.")
    log("  Check gBattleCommunication[0] transitions to see which case is blocking.")
  else
    log("RESULT: **FAILED** - Battle did not start")
    log("  callback2 may not have progressed from CB2_InitBattle.")
    log("  Check the transitions log for clues.")
  end

  -- Read final state
  log("")
  log("--- Final State ---")
  local finalCb2 = safeRead32(CFG.callback2Addr)
  local finalInBattle = safeRead8(CFG.gMainInBattle)
  local finalComm0 = safeRead8(CFG.gBattleCommunication)
  local finalBTF = safeRead32(CFG.gBattleTypeFlags)
  logf("  callback2 = %s", labelCb2(finalCb2))
  logf("  inBattle = %s", tostring(finalInBattle))
  logf("  gBattleCommunication[0] = %s", tostring(finalComm0))
  logf("  gBattleTypeFlags = %s", hex(finalBTF))

  -- Check gBattleResources pointer
  local gBR = safeRead32(CFG.gBattleResources)
  logf("  gBattleResources = %s", hex(gBR))
  if gBR and gBR >= 0x02000000 and gBR < 0x02040000 then
    -- Read buffer pointers
    local bufA = safeRead32(gBR + CFG.battle_link_bufferA_offset)
    local bufB = safeRead32(gBR + CFG.battle_link_bufferB_offset)
    logf("  bufferA base = %s (from gBattleResources+0x024)", hex(bufA))
    logf("  bufferB base = %s (from gBattleResources+0x824)", hex(bufB))
  end

  -- Restore ROM patches
  log("")
  log("--- Restoring ROM patches ---")
  local restored = 0
  for _, patch in ipairs(originals.rom) do
    local ok
    if patch.size == 2 then
      ok = romWrite16(patch.offset, patch.value)
    elseif patch.size == 4 then
      ok = romWrite32(patch.offset, patch.value)
    end
    if ok then
      restored = restored + 1
      logf("  Restored cart0 0x%06X = %s (%d bytes)", patch.offset,
        patch.size == 2 and hex16(patch.value) or hex(patch.value), patch.size)
    else
      logf("  FAIL: Could not restore cart0 0x%06X", patch.offset)
    end
  end
  logf("Restored %d/%d ROM patches", restored, #originals.rom)

  -- Note: NOT restoring EWRAM/IWRAM or callback2 because the battle is running
  -- If you need to abort the battle, reload a save state
  if monitor.battleMainReached then
    log("")
    log("NOTE: Battle is running. ROM patches restored but EWRAM/callback state left as-is.")
    log("The battle should play out normally. Use save state to return to overworld if needed.")
  else
    -- Battle didn't start properly - try to restore overworld
    log("")
    log("NOTE: Battle did not fully start. Attempting to restore overworld state...")

    if originals.callback2 then
      safeWrite32(CFG.callback2Addr, originals.callback2)
      logf("  Restored callback2 = %s", hex(originals.callback2))
    end
    if originals.callback1 then
      safeWrite32(CFG.callback1Addr, originals.callback1)
      logf("  Restored callback1 = %s", hex(originals.callback1))
    end
    if originals.savedCallback then
      safeWrite32(CFG.savedCallbackAddr, originals.savedCallback)
      logf("  Restored savedCallback = %s", hex(originals.savedCallback))
    end
    if originals.gMainState then
      safeWrite8(CFG.gMainStateAddr, originals.gMainState)
      logf("  Restored gMain.state = %d", originals.gMainState)
    end
    if originals.gBattleTypeFlags then
      safeWrite32(CFG.gBattleTypeFlags, originals.gBattleTypeFlags)
      logf("  Restored gBattleTypeFlags = %s", hex(originals.gBattleTypeFlags))
    end
    -- Restore IWRAM
    if originals.gWirelessCommType ~= nil then
      safeWrite8(CFG.gWirelessCommType, originals.gWirelessCommType)
    end
    if originals.gReceivedRemoteLinkPlayers ~= nil then
      safeWrite8(CFG.gReceivedRemoteLinkPlayers, originals.gReceivedRemoteLinkPlayers)
    end
    for i = 0, 3 do
      if originals.gBlockReceivedStatus[i] ~= nil then
        safeWrite8(CFG.gBlockReceivedStatus + i, originals.gBlockReceivedStatus[i])
      end
    end
    log("  IWRAM variables restored")
    log("  If the game is stuck, load a save state to recover.")
  end

  log("")
  log("========================================")
  log("  DIAGNOSTIC COMPLETE")
  log("========================================")
  logf("Total log lines: %d", #LOG)

  -- Write results to file for automated reading
  writeLogFile()

  -- Take screenshot of final state
  pcall(function()
    local scriptSrc = debug.getinfo(1, "S").source:sub(2)
    local scriptDir2 = scriptSrc:match("(.*/)")
    if not scriptDir2 then scriptDir2 = scriptSrc:match("(.*\\)") end
    local ssPath = (scriptDir2 or "") .. "../../battle_init_screenshot.png"
    emu:screenshot(ssPath)
  end)
end

-- Extra config values used in finishMonitoring
CFG.battle_link_bufferA_offset = 0x024
CFG.battle_link_bufferB_offset = 0x824

-- Write log to file (works even if mGBA console is not visible)
local function writeLogFile()
  -- Get script directory for output path
  local scriptSrc = debug.getinfo(1, "S").source:sub(2)
  local scriptDir = scriptSrc:match("(.*/)")
  if not scriptDir then scriptDir = scriptSrc:match("(.*\\)") end
  local outPath = (scriptDir or "") .. "../../battle_init_results.txt"

  local f = io.open(outPath, "w")
  if f then
    for _, line in ipairs(LOG) do
      f:write(line .. "\n")
    end
    f:write("\n--- RESULT ---\n")
    if monitor.battleMainReached then
      f:write("SUCCESS: BattleMainCB2 reached at frame " .. tostring(monitor.firstBattleCb2Frame) .. "\n")
    elseif monitor.inBattleTriggered then
      f:write("PARTIAL: inBattle=1 but BattleMainCB2 never reached\n")
    else
      f:write("FAILED: Battle did not start\n")
    end
    f:close()
    console:log("[BattleInit] Results written to: " .. outPath)
  else
    console:log("[BattleInit] WARNING: Could not write results file to: " .. outPath)
  end
end

-- ============================================================
-- Main execution
-- ============================================================

local function main()
  log("========================================")
  log("PvP Battle Init Chain Diagnostic")
  log("========================================")
  log("This script tests the FULL battle init chain:")
  log("  CB2_InitBattle -> CB2_InitBattleInternal -> CB2_HandleStartBattle -> BattleMainCB2")
  log("")
  log("WARNING: This WILL trigger a battle! Save state first!")
  log("")

  -- Step 0: Pre-flight checks
  if not step0_preflight() then
    log("ABORTED: Pre-flight checks failed")
    return
  end

  -- Step 1: Copy party
  local ok1, partyData = step1_copyParty()
  if not ok1 then
    log("ABORTED: Party copy failed")
    return
  end

  -- Step 2: Set battle type flags
  if not step2_battleFlags() then
    log("ABORTED: Could not set battle flags")
    return
  end

  -- Step 3: Apply ROM patches
  step3_romPatches()  -- continue even if some patches fail

  -- Step 4: Set IWRAM variables
  step4_iwramVars()

  -- Step 5: Set gMain fields
  step5_gMainSetup()

  -- Step 6: Trigger battle
  if not step6_trigger() then
    log("ABORTED: Could not set callback2")
    -- Restore ROM patches
    for _, patch in ipairs(originals.rom) do
      if patch.size == 2 then romWrite16(patch.offset, patch.value)
      elseif patch.size == 4 then romWrite32(patch.offset, patch.value) end
    end
    log("ROM patches restored after abort")
    return
  end

  -- Initialize monitoring state
  monitor.active = true
  monitor.frameCount = 0
  monitor.partyData = partyData
  monitor.prevCb2 = CFG.CB2_InitBattle
  monitor.prevInBattle = 0
  monitor.prevComm0 = 0
  monitor.transitions = {}
  monitor.success = false
  monitor.battleMainReached = false
  monitor.inBattleTriggered = false
  monitor.firstBattleCb2Frame = nil
  monitor.cb2History = { [CFG.CB2_InitBattle] = 0 }

  -- Register frame callback
  log("Registering frame callback for monitoring...")
  callbacks:add("frame", onFrame)
  log("Frame callback registered. Monitoring started.")
  log("Watch the console for live updates every 10 frames.")
end

-- Run immediately
main()
