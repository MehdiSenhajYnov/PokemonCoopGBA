--[[
  run_battle_test_slave.lua — Same as run_battle_test.lua but as SLAVE (isMaster=false)

  Key differences from master test:
  - GetMultiplayerId returns 1 (not 0)
  - gBattleTypeFlags does NOT include IS_MASTER
  - InitLinkBattleStructs case 1: pos[0]=OPPONENT, pos[1]=PLAYER
  - After BattleMainCB2: swap ctrl[0] to OpponentBufferRunCommand (not ctrl[1])
  - Player controls battler 1 (not 0)

  Usage: mGBA.exe --script scripts/ToUse/run_battle_test_slave.lua "rom/Pokemon RunBun.gba"
]]

-- Get script directory
local scriptSrc = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptSrc:match("(.*/)")
if not scriptDir then scriptDir = scriptSrc:match("(.*\\)") end
local projectRoot = scriptDir and (scriptDir .. "../../") or ""

console:log("[SlaveTest] Starting battle test as SLAVE (isMaster=false)...")

-- ============================================================
-- Configuration (same addresses as master test)
-- ============================================================

local CFG = {
  gPlayerParty      = 0x02023A98,
  gPlayerPartyCount = 0x02023A95,
  gEnemyParty       = 0x02023CF0,
  gEnemyPartyCount  = 0x02023A96,
  gBattleTypeFlags  = 0x02023364,
  gMainInBattle     = 0x03002AF9,
  CB2_BattleMain    = 0x0803816D,
  gMainBase         = 0x030022C0,
  callback1Addr     = 0x030022C0,
  callback2Addr     = 0x030022C4,
  savedCallbackAddr = 0x030022C8,
  gMainStateAddr    = 0x03002AF8,
  cb2Overworld      = 0x080A89A5,
  CB2_InitBattle    = 0x080363C1,
  CB2_HandleStartBattle = 0x08037B45,
  CB2_InitBattleInternal = 0x0803648D,
  GetMultiplayerId  = 0x0800A4B1,
  gWirelessCommType          = 0x030030FC,
  gReceivedRemoteLinkPlayers = 0x03003124,
  gBlockReceivedStatus       = 0x0300307C,
  gBattleCommunication = 0x0202370E,
  gBattleResources     = 0x02023A18,
  gActiveBattler       = 0x020233DC,
  gBattleControllerExecFlags = 0x020233E0,
  gBlockRecvBuffer     = 0x020226C4,
  gBlockRecvBufferStride = 0x100,
  gLinkPlayers         = 0x020229E8,
  BATTLE_TYPE_LINK    = 0x00000002,
  BATTLE_TYPE_LINK_IN_BATTLE = 0x00000020,
  BATTLE_TYPE_IS_MASTER = 0x00000004,
  BATTLE_TYPE_TRAINER = 0x00000008,
  BATTLE_TYPE_RECORDED_LINK = 0x01000000,
  linkStatusByte = 0x0203C300,
  gBattleMainFunc  = 0x03005D04,
  gBattlerControllerFuncs = 0x03005D70,
  gBattlerControllerEndFuncs = 0x03005D80,
  BattleControllerDummy = 0x0806F0A1,
  PlayerBufferRunCommand = 0x0806F151,
  LinkOpponentRunCommand = 0x0807DC45,
  OpponentBufferRunCommand = 0x081BAD85,
  SetControllerToOpponent = 0x081BAD69,
  DoBattleIntro    = 0x0803ACB1,
  TryDoEventsBeforeFirstTurn = 0x0803B4B9,
  HandleTurnActionSelectionState = 0x0803BE39,
  gBattlerByTurnOrder      = 0x020233F6,
  gChosenActionByBattler   = 0x02023598,
  gChosenMoveByBattler     = 0x020235FA,
  gBattleTurnCounter       = 0x02023708,
  gBattleOutcome           = 0x02023716,
  gPlttBufferUnfaded = 0x02036CD4,
  gPlttBufferFaded   = 0x020370D4,
  gPaletteFade       = 0x02037594,
  gPaletteFadeActive = 0x0203759B,
  PARTY_SIZE      = 600,
  POKEMON_SIZE    = 100,
  HP_OFFSET       = 86,
  patches = {
    -- GetMultiplayerId patched separately below (returns 1 for slave!)
    getMultiplayerId = { romOffset = 0x00A4B0, value1 = 0x2001, value2 = 0x4770 },  -- MOV R0,#1 (SLAVE!)
    isLinkTaskFinished = { romOffset = 0x0A568, value = 0x47702001, size = 4 },
    getBlockReceivedStatus = { romOffset = 0x0A598, value = 0x4770200F, size = 4 },
    playerBufExecSkip = { romOffset = 0x06F0D4 + 0x1C, value = 0xE01C, size = 2 },
    linkOpponentBufExecSkip = { romOffset = 0x078788 + 0x1C, value = 0xE01C, size = 2 },
    prepBufTransferSkip = { romOffset = 0x032FA8 + 0x18, value = 0xE008, size = 2 },
    markBattlerExecLocal = { romOffset = 0x040F40 + 0x10, value = 0xE010, size = 2 },
    isBattlerExecLocal = { romOffset = 0x040EFC, value = 0xE00E, size = 2 },
    markAllBattlersExecLocal = { romOffset = 0x040E88, value = 0xE018, size = 2 },
  },
  gBattleSpritesDataPtr_candidates = { 0x02023A0C, 0x02023A40, 0x02023A10, 0x02023A14 },
  HEALTHBOX_SIZE = 0x0C,
  gActionsByTurnOrder = 0x020233F2,
}

-- ============================================================
-- Memory helpers (same as master)
-- ============================================================
local function toWRAM(addr) return addr - 0x02000000 end
local function toIWRAM(addr) return addr - 0x03000000 end
local function isIW(addr) return addr >= 0x03000000 and addr < 0x03008000 end

local function r8(a) if isIW(a) then return emu.memory.iwram:read8(toIWRAM(a)) else return emu.memory.wram:read8(toWRAM(a)) end end
local function r16(a) if isIW(a) then return emu.memory.iwram:read16(toIWRAM(a)) else return emu.memory.wram:read16(toWRAM(a)) end end
local function r32(a) if isIW(a) then return emu.memory.iwram:read32(toIWRAM(a)) else return emu.memory.wram:read32(toWRAM(a)) end end
local function w8(a,v) if isIW(a) then emu.memory.iwram:write8(toIWRAM(a),v) else emu.memory.wram:write8(toWRAM(a),v) end end
local function w16(a,v) if isIW(a) then emu.memory.iwram:write16(toIWRAM(a),v) else emu.memory.wram:write16(toWRAM(a),v) end end
local function w32(a,v) if isIW(a) then emu.memory.iwram:write32(toIWRAM(a),v) else emu.memory.wram:write32(toWRAM(a),v) end end

local function sr8(a) local ok,v = pcall(r8,a) return ok and v or nil end
local function sr16(a) local ok,v = pcall(r16,a) return ok and v or nil end
local function sr32(a) local ok,v = pcall(r32,a) return ok and v or nil end
local function sw8(a,v) return pcall(w8,a,v) end
local function sw16(a,v) return pcall(w16,a,v) end
local function sw32(a,v) return pcall(w32,a,v) end

local function rr16(off) local ok,v = pcall(function() return emu.memory.cart0:read16(off) end) return ok and v or nil end
local function rr32(off) local ok,v = pcall(function() return emu.memory.cart0:read32(off) end) return ok and v or nil end
local function wr16(off,v) return pcall(function() emu.memory.cart0:write16(off,v) end) end
local function wr32(off,v) return pcall(function() emu.memory.cart0:write32(off,v) end) end
local function wrv16(off,v) if not wr16(off,v) then return false end return rr16(off) == v end
local function wrv32(off,v) if not wr32(off,v) then return false end return rr32(off) == v end

-- ============================================================
-- Logging
-- ============================================================
local LOG = {}
local function log(msg)
  local line = "[SlaveTest] " .. msg
  console:log(line)
  table.insert(LOG, line)
  if socketConnected and resultSocket then
    pcall(function() resultSocket:send(line .. "\n") end)
  end
end
local function logf(fmt, ...) log(string.format(fmt, ...)) end
local function hex(v) return v and string.format("0x%08X",v) or "nil" end
local function hex16(v) return v and string.format("0x%04X",v) or "nil" end

-- Known CB2 labels
local CB2_LABELS = {
  [CFG.CB2_InitBattle] = "CB2_InitBattle",
  [CFG.CB2_HandleStartBattle] = "CB2_HandleStartBattle",
  [CFG.CB2_BattleMain] = "BattleMainCB2",
  [CFG.cb2Overworld] = "CB2_Overworld",
  [CFG.CB2_InitBattleInternal] = "CB2_InitBattleInternal",
  [CFG.DoBattleIntro] = "DoBattleIntro",
  [CFG.TryDoEventsBeforeFirstTurn] = "TryDoEventsBeforeFirstTurn",
  [CFG.HandleTurnActionSelectionState] = "HandleTurnActionSelectionState",
}
local function labelCb2(v)
  if not v then return "nil" end
  local l = CB2_LABELS[v]
  return l and string.format("%s (%s)", hex(v), l) or hex(v)
end

-- ============================================================
-- State machine
-- ============================================================
local phase = "init"
local frameCount = 0
local phaseFrame = 0
local stateLoaded = false

-- Battle monitoring
local mon = {
  partyData = nil,
  prevCb2 = nil,
  prevInBattle = nil,
  prevComm0 = nil,
  transitions = {},
  battleMainReached = false,
  inBattleTriggered = false,
  firstBattleCb2Frame = nil,
  cb2History = {},
  maxFrames = 10800,
  prevBmf = nil,
  execStuckFrame = nil,
  execStuckValue = nil,
  bmfForceAdvanced = false,
  bmfAdvanceFrame = nil,
  battleResPtr = nil,
  turnsInjected = 0,
  outcomeFrame = nil,
  introComplete = false,
  introStuckFrame = nil,
  keyPhase = nil,
  keyHoldTimer = 0,
  keyTarget = nil,
  prevCommForKey = nil,
  turnInputAttempts = 0,
  idleTimer = 0,
  turnStartFrame = nil,
  prevPlayerHP = nil,
  prevEnemyHP = nil,
}

-- Saved originals for restore
local originals = { rom = {} }

-- TCP socket
local resultSocket = nil
local socketConnected = false

local function connectResultSocket()
  pcall(function()
    resultSocket = socket.connect("127.0.0.1", 9999)
    if resultSocket then socketConnected = true end
  end)
end

local function sendResult(text)
  if socketConnected and resultSocket then
    pcall(function() resultSocket:send(text .. "\n") end)
  end
end

local function closeResultSocket()
  if resultSocket then pcall(function() resultSocket:close() end) end
  resultSocket = nil
  socketConnected = false
end

local function writeResults()
  local lines = {}
  for _, line in ipairs(LOG) do table.insert(lines, line) end
  table.insert(lines, "")
  table.insert(lines, "--- RESULT (SLAVE MODE) ---")
  if mon.battleMainReached then
    table.insert(lines, "SUCCESS: BattleMainCB2 reached at frame " .. tostring(mon.firstBattleCb2Frame))
    table.insert(lines, "Turns: " .. tostring(mon.turnsInjected))
    local outcome = sr8(CFG.gBattleOutcome) or 0
    table.insert(lines, "Outcome: " .. tostring(outcome))
  elseif mon.inBattleTriggered then
    table.insert(lines, "PARTIAL: inBattle=1 but BattleMainCB2 never reached")
  else
    table.insert(lines, "FAILED: Battle did not start")
  end
  if socketConnected then
    for _, line in ipairs(lines) do sendResult(line) end
    closeResultSocket()
  end
  pcall(function()
    local f = io.open(projectRoot .. "battle_init_results_slave.txt", "w")
    if f then
      for _, line in ipairs(lines) do f:write(line .. "\n") end
      f:close()
    end
  end)
end

local function takeScreenshot(name)
  pcall(function()
    emu:screenshot(projectRoot .. "slave_" .. name .. ".png")
  end)
end

-- ============================================================
-- SLAVE-SPECIFIC: Battle setup
-- Key difference: GetMultiplayerId returns 1, no IS_MASTER flag
-- ============================================================
local function doBattleSetup()
  log("=== SLAVE MODE BATTLE SETUP ===")

  log("=== Step 1: Copy party (same as master) ===")
  local partyCount = sr8(CFG.gPlayerPartyCount) or 0
  logf("Player party count: %d", partyCount)
  if partyCount == 0 or partyCount > 6 then log("FAIL: Invalid party count") return false end

  local partyData = {}
  local baseR = toWRAM(CFG.gPlayerParty)
  local okR = pcall(function()
    for i = 0, CFG.PARTY_SIZE-1 do partyData[i+1] = emu.memory.wram:read8(baseR+i) end
  end)
  if not okR or #partyData ~= CFG.PARTY_SIZE then log("FAIL: Could not read gPlayerParty") return false end

  local baseW = toWRAM(CFG.gEnemyParty)
  local okW = pcall(function()
    for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(baseW+i-1, partyData[i]) end
  end)
  if not okW then log("FAIL: Could not write gEnemyParty") return false end
  sw8(CFG.gEnemyPartyCount, partyCount)

  -- SLAVE: enemy slot is 0 (GetMultiplayerId=1, enemy = slot 1^1 = 0)
  local enemySlot = 0  -- DIFFERENT FROM MASTER (which uses slot 1)
  local bufBase = toWRAM(CFG.gBlockRecvBuffer + enemySlot * CFG.gBlockRecvBufferStride)
  pcall(function()
    local healthFlags = 0
    for i = 0, 5 do
      local off = i * CFG.POKEMON_SIZE
      local personality = partyData[off+1] + partyData[off+2]*256 + partyData[off+3]*65536 + partyData[off+4]*16777216
      if personality ~= 0 then
        local hp = partyData[off + CFG.HP_OFFSET + 1] + partyData[off + CFG.HP_OFFSET + 2] * 256
        if hp > 0 then healthFlags = healthFlags | (1 << (i * 2))
        else healthFlags = healthFlags | (3 << (i * 2)) end
      end
    end
    logf("vsScreenHealthFlags for enemy (slot %d) = 0x%04X", enemySlot, healthFlags)
    emu.memory.wram:write8(bufBase + 0, 0)
    emu.memory.wram:write8(bufBase + 1, 0)
    emu.memory.wram:write8(bufBase + 2, healthFlags & 0xFF)
    emu.memory.wram:write8(bufBase + 3, (healthFlags >> 8) & 0xFF)
  end)

  -- Also write LOCAL player's health flags to slot 1 (slave's local slot)
  local localSlot = 1
  local localBufBase = toWRAM(CFG.gBlockRecvBuffer + localSlot * CFG.gBlockRecvBufferStride)
  pcall(function()
    local localHealth = 0
    for i = 0, 5 do
      local pOff = toWRAM(CFG.gPlayerParty) + i * CFG.POKEMON_SIZE
      local p = emu.memory.wram:read32(pOff)
      if p ~= 0 then
        local hp = emu.memory.wram:read16(pOff + CFG.HP_OFFSET)
        if hp > 0 then localHealth = localHealth | (1 << (i * 2))
        else localHealth = localHealth | (3 << (i * 2)) end
      end
    end
    emu.memory.wram:write8(localBufBase + 0, 0)
    emu.memory.wram:write8(localBufBase + 1, 0)
    emu.memory.wram:write8(localBufBase + 2, localHealth & 0xFF)
    emu.memory.wram:write8(localBufBase + 3, (localHealth >> 8) & 0xFF)
    logf("Local health flags (slot %d) = 0x%04X", localSlot, localHealth)
  end)

  -- gLinkPlayers (same as master)
  local lpBase = toWRAM(CFG.gLinkPlayers)
  pcall(function()
    emu.memory.wram:write16(lpBase + 0x00, 3)
    emu.memory.wram:write8(lpBase + 0x13, 0)
    emu.memory.wram:write32(lpBase + 0x14, 0x2233)
    emu.memory.wram:write16(lpBase + 0x18, 0)
    emu.memory.wram:write16(lpBase + 0x1A, 2)
    local p1 = lpBase + 0x1C
    emu.memory.wram:write16(p1 + 0x00, 3)
    emu.memory.wram:write8(p1 + 0x13, 0)
    emu.memory.wram:write32(p1 + 0x14, 0x2233)
    emu.memory.wram:write16(p1 + 0x18, 1)
    emu.memory.wram:write16(p1 + 0x1A, 2)
  end)

  mon.partyData = partyData

  log("=== Step 2: Set gBattleTypeFlags (WITH IS_MASTER — required for BeginBattleIntro!) ===")
  -- FIX: BOTH players need IS_MASTER so InitBtlControllersInternal sets gBattleMainFunc = BeginBattleIntro
  -- Without it, slave gets gBattleMainFunc = BeginBattleIntroDummy (empty) → stuck on VS screen
  local flags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_RECORDED_LINK | CFG.BATTLE_TYPE_IS_MASTER
  sw32(CFG.gBattleTypeFlags, flags)
  logf("gBattleTypeFlags = %s (WITH IS_MASTER for intro)", hex(sr32(CFG.gBattleTypeFlags)))

  sw8(CFG.linkStatusByte, 0)

  log("=== Step 3: ROM patches (GetMultiplayerId returns 1 for SLAVE!) ===")
  originals.rom = {}
  local patchCount = 0

  -- GetMultiplayerId → MOV R0,#1 (SLAVE returns 1!)
  local g = CFG.patches.getMultiplayerId
  local o1, o2 = rr16(g.romOffset), rr16(g.romOffset+2)
  if wrv16(g.romOffset, g.value1) then
    table.insert(originals.rom, {off=g.romOffset, val=o1, sz=2})
    patchCount = patchCount + 1
    logf("  GetMultiplayerId: MOV R0,#1 (SLAVE)")
  end
  if wrv16(g.romOffset+2, g.value2) then
    table.insert(originals.rom, {off=g.romOffset+2, val=o2, sz=2})
    patchCount = patchCount + 1
  end

  for name, p in pairs(CFG.patches) do
    if name ~= "getMultiplayerId" and p.romOffset and p.value then
      local orig
      if p.size == 4 then orig = rr32(p.romOffset) else orig = rr16(p.romOffset) end
      local ok
      if p.size == 4 then ok = wrv32(p.romOffset, p.value) else ok = wrv16(p.romOffset, p.value) end
      if ok then
        table.insert(originals.rom, {off=p.romOffset, val=orig, sz=p.size})
        patchCount = patchCount + 1
        logf("  Patch %s: OK", name)
      else
        logf("  Patch %s: FAIL", name)
      end
    end
  end
  logf("Applied %d ROM patches", patchCount)

  log("=== Step 4: IWRAM vars ===")
  sw8(CFG.gWirelessCommType, 0)
  sw8(CFG.gReceivedRemoteLinkPlayers, 1)
  for i = 0,3 do sw8(CFG.gBlockReceivedStatus+i, 0x0F) end

  log("=== Step 5: gMain setup ===")
  local cb1 = sr32(CFG.callback1Addr)
  logf("Original callback1 = %s", hex(cb1))
  sw32(CFG.savedCallbackAddr, CFG.cb2Overworld)
  sw32(CFG.callback1Addr, 0)
  sw8(CFG.gMainStateAddr, 0)
  sw8(CFG.gBattleCommunication, 0)

  log("=== Step 6: Trigger battle (SLAVE) ===")
  pcall(function() emu:clearKey(0) end)
  pcall(function() emu:clearKey(1) end)
  for k = 2, 7 do pcall(function() emu:clearKey(k) end) end

  sw32(CFG.callback2Addr, CFG.CB2_InitBattle)
  local vcb2 = sr32(CFG.callback2Addr)
  if vcb2 == CFG.CB2_InitBattle then
    logf("callback2 = %s (CB2_InitBattle) VERIFIED", hex(vcb2))
  else
    logf("FAIL: callback2 = %s (expected %s)", hex(vcb2), hex(CFG.CB2_InitBattle))
    return false
  end

  log(">>> SLAVE BATTLE TRIGGERED <<<")
  return true
end

-- ============================================================
-- Monitoring (mostly same as master, but controller swap is REVERSED)
-- ============================================================
local BMON_SIZE = 0x5C
local BMON_BASE = 0x020233FC

local function monitorFrame()
  local f = frameCount - phaseFrame
  local cb2 = sr32(CFG.callback2Addr)
  local rawIB = sr8(CFG.gMainInBattle)
  local inBattle = rawIB and (((rawIB & 0x02) ~= 0) and 1 or 0) or nil
  local comm0 = sr8(CFG.gBattleCommunication)
  local bmf = sr32(0x03005D04)

  -- Transitions
  if cb2 ~= mon.prevCb2 then
    logf(">>> f%d: cb2 %s -> %s", f, labelCb2(mon.prevCb2), labelCb2(cb2))
    table.insert(mon.transitions, string.format("f%d: cb2 change", f))
    mon.prevCb2 = cb2
  end
  if inBattle ~= mon.prevInBattle then
    logf(">>> f%d: inBattle %s -> %s", f, tostring(mon.prevInBattle), tostring(inBattle))
    if inBattle == 1 then mon.inBattleTriggered = true end
    mon.prevInBattle = inBattle
  end
  if comm0 ~= mon.prevComm0 then
    logf(">>> f%d: comm[0] %s -> %s", f, tostring(mon.prevComm0), tostring(comm0))
    mon.prevComm0 = comm0
  end
  if bmf ~= mon.prevBmf then
    logf(">>> f%d: bmf %s -> %s", f, hex(mon.prevBmf), hex(bmf))
    mon.prevBmf = bmf
  end

  -- BattleMainCB2 reached?
  if cb2 == CFG.CB2_BattleMain and not mon.battleMainReached then
    mon.battleMainReached = true
    mon.firstBattleCb2Frame = f
    logf("***** SUCCESS: BattleMainCB2 at frame %d (SLAVE) *****", f)
    takeScreenshot("battle_main_reached")

    -- CRITICAL FIX (SLAVE VERSION):
    -- Part 1: Clear LINK flags
    local btf = sr32(CFG.gBattleTypeFlags)
    local newBtf = btf & ~CFG.BATTLE_TYPE_LINK
    newBtf = newBtf & ~CFG.BATTLE_TYPE_LINK_IN_BATTLE
    newBtf = newBtf & ~CFG.BATTLE_TYPE_RECORDED_LINK
    sw32(CFG.gBattleTypeFlags, newBtf)
    logf("  [FIX] Cleared LINK flags: %s -> %s", hex(btf), hex(newBtf))

    -- Part 2: SLAVE controller swap — REVERSE of master!
    -- Slave (GetMultiplayerId=1): InitLinkBattleStructs case 1:
    --   pos[0] = OPPONENT_LEFT (front sprite)
    --   pos[1] = PLAYER_LEFT (back sprite)
    --   ctrl[0] = LinkOpponentBufferRunCommand (STUCK — needs replacement)
    --   ctrl[1] = PlayerBufferRunCommand (correct)
    local cf0 = sr32(CFG.gBattlerControllerFuncs)
    local cf1 = sr32(CFG.gBattlerControllerFuncs + 4)
    logf("  [FIX] Pre-swap: ctrl[0]=%s ctrl[1]=%s", hex(cf0), hex(cf1))

    -- Swap ctrl[0] (opponent) to OpponentBufferRunCommand
    sw32(CFG.gBattlerControllerFuncs, CFG.OpponentBufferRunCommand)
    -- Ensure ctrl[1] (player) stays as PlayerBufferRunCommand
    sw32(CFG.gBattlerControllerFuncs + 4, CFG.PlayerBufferRunCommand)

    local cf0_new = sr32(CFG.gBattlerControllerFuncs)
    local cf1_new = sr32(CFG.gBattlerControllerFuncs + 4)
    logf("  [FIX] Post-swap: ctrl[0]=%s (OpponentAI) ctrl[1]=%s (Player)", hex(cf0_new), hex(cf1_new))

    -- Part 3: Clear gReceivedRemoteLinkPlayers
    sw8(CFG.gReceivedRemoteLinkPlayers, 0)

    -- Re-inject enemy party
    if mon.partyData then
      local bw = toWRAM(CFG.gEnemyParty)
      pcall(function()
        for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(bw+i-1, mon.partyData[i]) end
      end)
    end
  end

  -- Post-BattleMainCB2 logic
  if mon.battleMainReached then
    local framesSinceBMC = f - mon.firstBattleCb2Frame

    -- Re-inject enemy party every 10 frames
    if f % 10 == 0 and mon.partyData then
      local bw = toWRAM(CFG.gEnemyParty)
      pcall(function()
        for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(bw+i-1, mon.partyData[i]) end
      end)
      -- Re-write health flags for enemy (slot 0 for slave)
      local bufBase = toWRAM(CFG.gBlockRecvBuffer + 0 * CFG.gBlockRecvBufferStride)
      pcall(function()
        emu.memory.wram:write8(bufBase + 2, 0x01)
        emu.memory.wram:write8(bufBase + 3, 0x00)
      end)
    end

    -- Enforce gBattlersCount=2
    sw8(0x020233E4, 2)

    -- Maintain IWRAM
    if f % 10 == 0 then
      sw8(CFG.gWirelessCommType, 0)
      if mon.battleMainReached then
        sw8(CFG.gReceivedRemoteLinkPlayers, 0)
      else
        sw8(CFG.gReceivedRemoteLinkPlayers, 1)
        for i = 0,3 do sw8(CFG.gBlockReceivedStatus+i, 0x0F) end
      end
      sw8(CFG.linkStatusByte, 0)
    end

    -- Maintain gBattleTypeFlags (BOTH players need IS_MASTER for BeginBattleIntro)
    if f % 4 == 0 then
      local currentFlags = sr32(CFG.gBattleTypeFlags)
      if currentFlags then
        local requiredFlags = CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER
        local unwantedFlags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_LINK_IN_BATTLE | CFG.BATTLE_TYPE_RECORDED_LINK
        local merged = (currentFlags | requiredFlags) & ~unwantedFlags
        if merged ~= currentFlags then sw32(CFG.gBattleTypeFlags, merged) end
      end
    end

    -- Force actions (SLAVE: player is battler 1, opponent is battler 0)
    -- Note: gChosenActionByBattler[0] = opponent, gChosenActionByBattler[1] = player
    sw8(CFG.gChosenActionByBattler, 0)
    sw8(CFG.gChosenActionByBattler + 1, 0)
    sw16(CFG.gChosenMoveByBattler, 0)
    sw16(CFG.gChosenMoveByBattler + 2, 0)
    sw8(CFG.gActionsByTurnOrder, 0)
    sw8(CFG.gActionsByTurnOrder + 1, 0)
    sw8(CFG.gActionsByTurnOrder + 2, 0)
    sw8(CFG.gActionsByTurnOrder + 3, 0)

    -- Exec flags management (same as master)
    local execFlags = sr32(CFG.gBattleControllerExecFlags)
    if execFlags and execFlags ~= 0 then
      local localBits = execFlags & 0x0000000F
      local strayBits = execFlags & 0xFFFFFFF0
      if strayBits ~= 0 then sw32(CFG.gBattleControllerExecFlags, localBits) end
      if localBits ~= 0 then
        local isActionSelection = bmf == CFG.HandleTurnActionSelectionState
        local isDoBattleIntro = bmf == CFG.DoBattleIntro
        if not isActionSelection then
          if not mon.execStuckFrame then
            mon.execStuckFrame = f
            mon.execStuckValue = localBits
          end
          if localBits ~= mon.execStuckValue then
            mon.execStuckFrame = f
            mon.execStuckValue = localBits
          end
          local safetyTimeout = isDoBattleIntro and 200 or 180
          if f - mon.execStuckFrame >= safetyTimeout then
            logf("  [EXEC] SAFETY clear 0x%X after %d frames", localBits, safetyTimeout)
            sw32(CFG.gBattleControllerExecFlags, 0)
            mon.execStuckFrame = nil
          end
        end
      else
        mon.execStuckFrame = nil
      end
    else
      mon.execStuckFrame = nil
    end

    -- Healthbox unblock
    if not mon.gBattleSpritesDataPtr and f % 5 == 0 then
      for _, candidate in ipairs(CFG.gBattleSpritesDataPtr_candidates) do
        local ptr = sr32(candidate)
        if ptr and ptr >= 0x02000000 and ptr < 0x02040000 then
          local validSubs = 0
          for off = 0, 12, 4 do
            local s = sr32(ptr + off)
            if s and s >= 0x02000000 and s < 0x02040000 then validSubs = validSubs + 1 end
          end
          if validSubs >= 3 then
            mon.gBattleSpritesDataPtr = candidate
            mon.healthBoxesData = sr32(ptr + 4)
            break
          end
        end
      end
    end
    if mon.healthBoxesData and f % 5 == 0 then
      for battler = 0, 1 do
        local base = mon.healthBoxesData + battler * CFG.HEALTHBOX_SIZE
        local byte1 = sr8(base + 1) or 0
        if (byte1 & 0x40) ~= 0 then sw8(base + 1, byte1 & ~0x40) end
        if framesSinceBMC > 120 then
          byte1 = sr8(base + 1) or 0
          sw8(base + 1, byte1 | 0x01 | 0x20)
        end
      end
    end

    -- Palette force
    if mon.introComplete or mon.bmfForceAdvanced then
      local introEndFrame = mon.bmfAdvanceFrame or mon.introCompleteFrame or 0
      local sinceIntroEnd = framesSinceBMC - introEndFrame
      if sinceIntroEnd >= 30 and not mon.paletteForcedFrame then
        local pal0 = nil
        pcall(function() pal0 = emu.memory.palette:read16(0) end)
        if pal0 and pal0 == 0 then
          local ufOff = toWRAM(CFG.gPlttBufferUnfaded)
          local fdOff = toWRAM(CFG.gPlttBufferFaded)
          pcall(function()
            for i = 0, 1023 do
              emu.memory.wram:write8(fdOff + i, emu.memory.wram:read8(ufOff + i))
            end
            for i = 0, 511 do
              emu.memory.palette:write16(i * 2, emu.memory.wram:read16(fdOff + i * 2))
            end
          end)
          local w1 = sr32(CFG.gPaletteFade + 0x0C) or 0
          sw32(CFG.gPaletteFade + 0x0C, w1 & 0x7E007FFF)
          mon.paletteForcedFrame = framesSinceBMC
          logf("  [PAL] Forced palette restore at f+%d", framesSinceBMC)
        end
      end
      if mon.paletteForcedFrame and (framesSinceBMC - mon.paletteForcedFrame) % 30 == 0 then
        local pal0 = nil
        pcall(function() pal0 = emu.memory.palette:read16(0) end)
        if pal0 and pal0 == 0 then
          local ufOff = toWRAM(CFG.gPlttBufferUnfaded)
          local fdOff = toWRAM(CFG.gPlttBufferFaded)
          pcall(function()
            for i = 0, 1023 do emu.memory.wram:write8(fdOff + i, emu.memory.wram:read8(ufOff + i)) end
            for i = 0, 511 do emu.memory.palette:write16(i * 2, emu.memory.wram:read16(fdOff + i * 2)) end
          end)
        end
      end
    end

    -- Track intro progress
    local currentBmf = sr32(CFG.gBattleMainFunc)
    if currentBmf == CFG.DoBattleIntro then
      if not mon.introStuckFrame then mon.introStuckFrame = framesSinceBMC end
      if framesSinceBMC - mon.introStuckFrame >= 5400 and not mon.bmfForceAdvanced then
        logf("  [BMF] DoBattleIntro stuck %d frames, FORCE-ADVANCING", framesSinceBMC - mon.introStuckFrame)
        sw32(CFG.gBattleControllerExecFlags, 0)
        sw32(CFG.gBattleMainFunc, CFG.TryDoEventsBeforeFirstTurn)
        mon.bmfForceAdvanced = true
        mon.bmfAdvanceFrame = framesSinceBMC
      end
    else
      mon.introStuckFrame = nil
      if currentBmf == CFG.HandleTurnActionSelectionState and not mon.actionMenuReached then
        logf("  [INTRO] SLAVE reached HandleTurnActionSelectionState at f+%d!", framesSinceBMC)
        mon.introComplete = true
        mon.actionMenuReached = true
        mon.bmfForceAdvanced = true
        mon.bmfAdvanceFrame = framesSinceBMC
        takeScreenshot("slave_action_menu")
      end
    end

    -- KEY SIMULATION (SLAVE: player is battler 1, but key input still goes to same menus)
    -- The key simulation logic is the same — A presses for Fight and Move selection
    local KEY_A = 0
    if currentBmf == CFG.HandleTurnActionSelectionState then
      local ef = sr32(CFG.gBattleControllerExecFlags) or 0
      -- SLAVE: player is battler 1, so comm[1] tracks our state
      -- But the key simulation still works the same way — the game reads KEYINPUT for player battler
      local playerComm = sr8(CFG.gBattleCommunication + 1) or 0  -- Player is battler 1 for slave!
      local opponentComm = sr8(CFG.gBattleCommunication) or 0

      if not mon.turnStartFrame then
        mon.turnStartFrame = framesSinceBMC
        mon.keyPhase = "idle"
        mon.keyHoldTimer = 0
        mon.idleTimer = 0
        local hp0 = sr16(BMON_BASE + 0x2A) or 0
        local hp1 = sr16(BMON_BASE + BMON_SIZE + 0x2A) or 0
        logf("  [TURN] SLAVE action selection at f+%d HP: b0=%d b1=%d (player=b1)", framesSinceBMC, hp0, hp1)
        takeScreenshot(string.format("slave_turn%d_f%04d", (mon.turnsInjected or 0) + 1, framesSinceBMC))
      end

      mon.keyHoldTimer = mon.keyHoldTimer + 1

      -- Opponent force-advance: if opponent (battler 0) stuck at comm=3
      if opponentComm == 3 and ef == 0 then
        if not mon.comm0StuckFrame then
          mon.comm0StuckFrame = framesSinceBMC
        elseif framesSinceBMC - mon.comm0StuckFrame >= 60 then
          sw8(CFG.gChosenActionByBattler, 0)
          sw16(CFG.gChosenMoveByBattler, 0)
          sw8(CFG.gBattleCommunication, 5)
          logf("  [FIX] Force-advanced opponent comm[0]: 3 -> 5")
          mon.comm0StuckFrame = nil
        end
      else
        mon.comm0StuckFrame = nil
      end

      -- SLAVE key sim: watch playerComm (comm[1]) for input prompts
      if mon.keyPhase == "idle" then
        mon.idleTimer = (mon.idleTimer or 0) + 1
        if playerComm == 1 and (ef & 0x02) ~= 0 then  -- Player is battler 1, exec bit is 0x02
          mon.keyPhase = "wait_render"
          mon.keyHoldTimer = 0
          mon.keyTarget = "fight"
          mon.idleTimer = 0
          logf("  [INPUT] SLAVE: Fight menu (comm[1]=%d, ef=0x%02X)", playerComm, ef)
        elseif playerComm == 3 and (ef & 0x02) ~= 0 then
          mon.keyPhase = "wait_render"
          mon.keyHoldTimer = 0
          mon.keyTarget = "move"
          mon.idleTimer = 0
          logf("  [INPUT] SLAVE: Move menu (comm[1]=%d, ef=0x%02X)", playerComm, ef)
        elseif playerComm >= 4 then
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
          mon.idleTimer = 0
        elseif mon.idleTimer > 120 then
          mon.keyPhase = "force_press"
          mon.keyHoldTimer = 0
          mon.idleTimer = 0
        end
      elseif mon.keyPhase == "wait_render" then
        if mon.keyHoldTimer >= 10 then
          mon.keyPhase = "pressing"
          mon.keyHoldTimer = 0
          emu:addKey(KEY_A)
          mon.turnInputAttempts = (mon.turnInputAttempts or 0) + 1
        end
      elseif mon.keyPhase == "pressing" then
        if mon.keyHoldTimer >= 4 then
          emu:clearKey(KEY_A)
          mon.keyPhase = "wait_response"
          mon.keyHoldTimer = 0
        end
      elseif mon.keyPhase == "wait_response" then
        if playerComm >= 4 then
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
        elseif mon.keyHoldTimer > 90 then
          mon.keyPhase = "idle"
          mon.idleTimer = 0
          mon.keyHoldTimer = 0
        end
      elseif mon.keyPhase == "wait_turn" then
        if mon.keyHoldTimer > 300 then
          mon.keyPhase = "force_press"
          mon.keyHoldTimer = 0
        end
      elseif mon.keyPhase == "force_press" then
        local cycle = mon.keyHoldTimer % 20
        if cycle <= 3 then emu:addKey(KEY_A) elseif cycle == 4 then emu:clearKey(KEY_A) end
        if playerComm >= 4 and ef == 0 then
          emu:clearKey(KEY_A)
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
        end
        if mon.keyHoldTimer > 600 then
          emu:clearKey(KEY_A)
          mon.keyPhase = "idle"
          mon.idleTimer = 0
          mon.keyHoldTimer = 0
        end
      end

      -- Periodic log
      if (framesSinceBMC - (mon.turnStartFrame or 0)) % 30 == 0 then
        logf("  [HTASS] SLAVE f+%d phase=%s comm=%d/%d ef=%s",
          framesSinceBMC, mon.keyPhase or "nil", opponentComm, playerComm, hex(ef))
      end
    else
      if mon.turnStartFrame then
        if mon.keyPhase ~= "idle" then
          mon.turnsInjected = (mon.turnsInjected or 0) + 1
          logf("  [TURN] SLAVE turn %d executing (bmf=%s)", mon.turnsInjected, hex(currentBmf))
        end
        emu:clearKey(KEY_A)
        mon.turnStartFrame = nil
        mon.keyPhase = nil
        mon.keyHoldTimer = 0
        mon.idleTimer = 0
      end
    end

    -- Turn execution maintenance
    if mon.bmfForceAdvanced then
      local RunTurnActionsFunctions = 0x0803E371
      local SetActionsAndBattlersTurnOrder = 0x0803D8F1
      local HandleEndTurn = 0x0803B96D
      local BattleTurnPassed = 0x0803BA25
      if currentBmf == RunTurnActionsFunctions or currentBmf == SetActionsAndBattlersTurnOrder
         or currentBmf == HandleEndTurn or currentBmf == BattleTurnPassed then
        sw8(CFG.gChosenActionByBattler, 0)
        sw8(CFG.gChosenActionByBattler + 1, 0)
        sw16(CFG.gChosenMoveByBattler, 0)
        sw16(CFG.gChosenMoveByBattler + 2, 0)
        sw8(CFG.gActionsByTurnOrder, 0)
        sw8(CFG.gActionsByTurnOrder + 1, 0)
        sw8(CFG.gActionsByTurnOrder + 2, 0)
        sw8(CFG.gActionsByTurnOrder + 3, 0)
        local cafid = sr8(0x020233FB) or 0
        if cafid > 12 then sw8(0x020233FB, 0) end
      end
    end

    -- gBattleResources cache
    if not mon.battleResPtr then
      local resPtr = sr32(CFG.gBattleResources)
      if resPtr and resPtr >= 0x02000000 and resPtr < 0x02040000 then
        mon.battleResPtr = resPtr
      end
    end
    if mon.battleResPtr and sr32(CFG.gBattleResources) == 0 then
      sw32(CFG.gBattleResources, mon.battleResPtr)
    end
  end

  -- Periodic log
  if f % 60 == 0 then
    local btf = sr32(CFG.gBattleTypeFlags)
    local ef = sr32(CFG.gBattleControllerExecFlags)
    logf("  [SLAVE f=%d] cb2=%s bmf=%s btf=%s ef=%s", f, labelCb2(cb2), hex(bmf), hex(btf), hex(ef))
  end

  -- During STARTING: maintain and re-inject
  if not mon.battleMainReached then
    if f % 10 == 0 then
      sw8(CFG.gWirelessCommType, 0)
      sw8(CFG.gReceivedRemoteLinkPlayers, 1)
      for i = 0,3 do sw8(CFG.gBlockReceivedStatus+i, 0x0F) end
      sw8(CFG.linkStatusByte, 0)
      sw8(0x020233E4, 2) -- gBattlersCount
    end
    if f % 4 == 0 then
      local cur = sr32(CFG.gBattleTypeFlags)
      if cur then
        local required = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_RECORDED_LINK | CFG.BATTLE_TYPE_IS_MASTER
        local merged = cur | required
        if merged ~= cur then sw32(CFG.gBattleTypeFlags, merged) end
      end
    end
    if f % 10 == 0 and mon.partyData then
      local bw = toWRAM(CFG.gEnemyParty)
      pcall(function()
        for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(bw+i-1, mon.partyData[i]) end
      end)
    end
  end

  -- Screenshots
  if f <= 400 and f % 50 == 0 then takeScreenshot(string.format("slave_f%04d", f)) end
  if f > 400 and f % 200 == 0 then takeScreenshot(string.format("slave_f%04d", f)) end

  -- Check battle outcome
  if mon.bmfForceAdvanced then
    local outcome = sr8(CFG.gBattleOutcome)
    if outcome and outcome ~= 0 then
      if not mon.outcomeFrame then
        mon.outcomeFrame = f
        logf("  [END] SLAVE battle outcome %d at f=%d, turns=%d", outcome, f, mon.turnsInjected or 0)
        takeScreenshot("slave_outcome")
      elseif f - mon.outcomeFrame >= 300 then
        return true
      end
    end
  end

  if f >= mon.maxFrames then return true end
  if mon.battleMainReached and f >= mon.firstBattleCb2Frame + 6000 then return true end
  return false
end

-- ============================================================
-- Finish
-- ============================================================
local function finish()
  pcall(function() emu:clearKey(0) end)
  pcall(function() emu:clearKey(1) end)

  log("=== SLAVE TEST RESULTS ===")
  if mon.battleMainReached then
    logf("RESULT: SUCCESS — BattleMainCB2 at frame %d (SLAVE)", mon.firstBattleCb2Frame or -1)
    logf("  Turns: %d", mon.turnsInjected or 0)
    local outcome = sr8(CFG.gBattleOutcome) or 0
    logf("  Outcome: %d", outcome)
    local hp0 = sr16(BMON_BASE + 0x2A) or 0
    local hp1 = sr16(BMON_BASE + BMON_SIZE + 0x2A) or 0
    logf("  HP: battler0=%d battler1=%d (slave player=battler1)", hp0, hp1)
  elseif mon.inBattleTriggered then
    log("RESULT: PARTIAL — inBattle=1 but no BattleMainCB2 (SLAVE)")
  else
    log("RESULT: FAILED — Battle did not start (SLAVE)")
  end

  -- Verify controller state was correct
  local cf0 = sr32(CFG.gBattlerControllerFuncs) or 0
  local cf1 = sr32(CFG.gBattlerControllerFuncs + 4) or 0
  logf("Final controllers: ctrl[0]=%s ctrl[1]=%s", hex(cf0), hex(cf1))

  -- Restore ROM
  for _, p in ipairs(originals.rom) do
    if p.sz == 2 then wr16(p.off, p.val) else wr32(p.off, p.val) end
  end
  logf("Restored %d ROM patches", #originals.rom)

  takeScreenshot("slave_final")
  writeResults()
end

-- ============================================================
-- Main frame handler
-- ============================================================
local function onFrame()
  frameCount = frameCount + 1

  if phase == "init" then
    if frameCount == 1 then connectResultSocket() end
    if frameCount >= 60 then
      log("Loading save state slot 1...")
      pcall(function() emu:loadStateSlot(1) end)
      phase = "waitload"
      phaseFrame = frameCount
    end
  elseif phase == "waitload" then
    if frameCount - phaseFrame >= 120 then
      log("Save state loaded.")
      local pc = sr8(CFG.gPlayerPartyCount)
      if not pc or pc == 0 or pc > 6 then
        log("FAIL: No valid party")
        phase = "done"
        writeResults()
        return
      end
      phase = "battle"
      phaseFrame = frameCount
    end
  elseif phase == "battle" then
    local ok = doBattleSetup()
    if ok then
      mon.prevCb2 = CFG.CB2_InitBattle
      mon.prevInBattle = 0
      mon.prevComm0 = 0
      phase = "monitoring"
      phaseFrame = frameCount
    else
      phase = "done"
      writeResults()
    end
  elseif phase == "monitoring" then
    if monitorFrame() then
      phase = "done"
      finish()
    end
  end
end

callbacks:add("frame", onFrame)
console:log("[SlaveTest] Frame callback registered. SLAVE mode active.")
