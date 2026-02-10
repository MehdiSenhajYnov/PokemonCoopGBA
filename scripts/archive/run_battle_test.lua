--[[
  run_battle_test.lua — Wrapper that loads save state then runs battle init diagnostic

  Usage: mGBA.exe --script scripts/ToUse/run_battle_test.lua "rom/Pokemon RunBun.gba"

  Steps:
  1. Wait 30 frames for mGBA to stabilize
  2. Load save state slot 1 (must exist: overworld, with party)
  3. Wait 60 frames for save state to fully load
  4. Run the battle init diagnostic inline
  5. Write results to battle_init_results.txt
]]

-- Get script directory
local scriptSrc = debug.getinfo(1, "S").source:sub(2)
local scriptDir = scriptSrc:match("(.*/)")
if not scriptDir then scriptDir = scriptSrc:match("(.*\\)") end
local projectRoot = scriptDir and (scriptDir .. "../../") or ""

console:log("[RunTest] Starting battle init test wrapper...")
console:log("[RunTest] Project root: " .. projectRoot)

-- ============================================================
-- Configuration (hardcoded from config/run_and_bun.lua)
-- ============================================================

local CFG = {
  gPlayerParty      = 0x02023A98,
  gPlayerPartyCount = 0x02023A95,
  gEnemyParty       = 0x02023CF0,
  gEnemyPartyCount  = 0x02023A96,  -- CORRECTED: contiguous with gPlayerPartyCount in pokemon.c
  gBattleTypeFlags  = 0x02023364,
  -- CORRECTED: gMain is in IWRAM at 0x030022C0, vanilla expansion layout
  gMainInBattle     = 0x03002AF9,    -- gMain+0x439 (IWRAM), bitfield bit 1
  CB2_BattleMain    = 0x0803816D,  -- CORRECTED: was 0x08094815 (sprite anim callback, NOT BattleMainCB2)
  gMainBase         = 0x030022C0,    -- IWRAM (was 0x02020648 EWRAM — WRONG)
  callback1Addr     = 0x030022C0,    -- gMain+0x00 (IWRAM)
  callback2Addr     = 0x030022C4,    -- gMain+0x04 (IWRAM)
  savedCallbackAddr = 0x030022C8,    -- gMain+0x08 (IWRAM)
  gMainStateAddr    = 0x03002AF8,    -- gMain+0x438 (IWRAM, vanilla layout)
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
  gActiveBattler       = 0x020233DC,  -- CORRECTED: u8 (byte access), was swapped with ExecFlags
  gBattleControllerExecFlags = 0x020233E0,  -- CORRECTED: u32 (32-bit polling), was swapped with ActiveBattler
  gBlockRecvBuffer     = 0x020226C4,  -- 4 slots × 0x100 bytes — link party exchange source
  gBlockRecvBufferStride = 0x100,
  gLinkPlayers         = 0x020229E8,  -- 4 entries × 0x1C bytes — link player identification
  BATTLE_TYPE_LINK    = 0x00000002,
  BATTLE_TYPE_LINK_IN_BATTLE = 0x00000020,  -- Bit 5: auto-set by engine when LINK starts. IsLinkBattle() checks THIS, not bit 1!
  BATTLE_TYPE_IS_MASTER = 0x00000004,
  BATTLE_TYPE_TRAINER = 0x00000008,
  BATTLE_TYPE_RECORDED_LINK = 0x01000000,  -- Bit 24: needed for BattleMainCB2 transition gate
  linkStatusByte = 0x0203C300,  -- Must be 0 for link readiness check in BattleMainCB2
  gBattleMainFunc  = 0x03005D04,   -- IWRAM: function pointer called each frame by BattleMainCB2
  gBattlerControllerFuncs = 0x03005D70,  -- IWRAM: u32[4] function pointers per battler
  gBattlerControllerEndFuncs = 0x03005D80,  -- IWRAM: u32[4] end callback per battler
  -- Known controller functions for link battle (IS_MASTER, non-multi):
  --   slot[0] = PlayerBufferRunCommand = 0x0806F151 (set by SetControllerToPlayer at 0x0806F0A5)
  --   slot[1] = 0x0807DC45 (link opponent variant, set by 0x0807DC29)
  BattleControllerDummy = 0x0806F0A1,
  PlayerBufferRunCommand = 0x0806F151,
  LinkOpponentRunCommand = 0x0807DC45,
  OpponentBufferRunCommand = 0x081BAD85,  -- Regular AI opponent controller (handles all anims locally)
  SetControllerToOpponent = 0x081BAD69,   -- Function that sets up opponent controller
  DoBattleIntro    = 0x0803ACB1,   -- Current stuck function
  TryDoEventsBeforeFirstTurn = 0x0803B4B9,  -- Next in chain after DoBattleIntro
  HandleTurnActionSelectionState = 0x0803BE39, -- Action selection menu (Fight/Bag/Pokemon/Run)
  -- Turn management variables (found by find_turn_vars.py / find_turn_counter_v12.py)
  gBattlerByTurnOrder      = 0x020233F6,   -- u8[4]: speed-sorted battler order
  gChosenActionByBattler   = 0x02023598,   -- u8[MAX_BATTLERS_COUNT]: action per battler (0xFF = none)
  gChosenMoveByBattler     = 0x020235FA,   -- u16[MAX_BATTLERS_COUNT]: move per battler (0 = none)
  gBattleTurnCounter       = 0x02023708,   -- u16: incremented each turn, 0 at start
  gBattleOutcome           = 0x02023716,   -- u8: 0=ongoing, 1=won, 2=lost (immediately after gBattleCommunication[8])
  -- Palette system (found via ROM scanner)
  gPlttBufferUnfaded = 0x02036CD4,  -- 1024 bytes (512 u16) — original loaded palette
  gPlttBufferFaded   = 0x020370D4,  -- 1024 bytes (512 u16) — working copy DMA'd to palette RAM
  gPaletteFade       = 0x02037594,  -- struct (8+ bytes), active flag = bit 7 at +0x07
  gPaletteFadeActive = 0x0203759B,  -- byte containing active flag (bit 7)
  PARTY_SIZE      = 600,
  POKEMON_SIZE    = 100,
  HP_OFFSET       = 86,
  patches = {
    getMultiplayerId = { romOffset = 0x00A4B0, value1 = 0x2000, value2 = 0x4770 },
    isLinkTaskFinished = { romOffset = 0x0A568, value = 0x47702001, size = 4 },
    getBlockReceivedStatus = { romOffset = 0x0A598, value = 0x4770200F, size = 4 },
    playerBufExecSkip = { romOffset = 0x06F0D4 + 0x1C, value = 0xE01C, size = 2 },
    linkOpponentBufExecSkip = { romOffset = 0x078788 + 0x1C, value = 0xE01C, size = 2 },
    prepBufTransferSkip = { romOffset = 0x032FA8 + 0x18, value = 0xE008, size = 2 },
    -- MarkBattlerForControllerExec: BEQ→B to ALWAYS use local exec path (set bits 0-3)
    -- Without this, link mode only sets bits 28-31 and controllers never execute commands
    markBattlerExecLocal = { romOffset = 0x040F40 + 0x10, value = 0xE010, size = 2 },
    -- IsBattlerMarkedForControllerExec: BEQ→B to ALWAYS check local bits 0-3
    -- CRITICAL: Without this, engine checks bits 28-31 (always 0) and thinks controllers
    -- are done immediately, racing through DoBattleIntro without waiting for animations
    isBattlerExecLocal = { romOffset = 0x040EFC, value = 0xE00E, size = 2 },
    -- MarkAllBattlersForControllerExec: BEQ→B to ALWAYS use local path
    markAllBattlersExecLocal = { romOffset = 0x040E88, value = 0xE018, size = 2 },
  },
  -- gBattleSpritesDataPtr candidates (runtime-probed, ~579 ROM refs)
  gBattleSpritesDataPtr_candidates = { 0x02023A0C, 0x02023A40, 0x02023A10, 0x02023A14 },
  -- BattleHealthboxInfo struct: 0x0C bytes per battler
  -- byte 0: bit3=ballAnimActive
  -- byte 1: bit0=finishedShinyMonAnim, bit5=bgmRestored, bit6=waitForCry, bit7=healthboxSlideInStarted
  -- byte 0x0A: introEndDelay
  HEALTHBOX_SIZE = 0x0C,
}

-- ============================================================
-- Memory helpers
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

local function wrv16(off,v)
  if not wr16(off,v) then return false end
  return rr16(off) == v
end
local function wrv32(off,v)
  if not wr32(off,v) then return false end
  return rr32(off) == v
end

-- ============================================================
-- Logging
-- ============================================================
local LOG = {}
local function log(msg)
  local line = "[BattleTest] " .. msg
  console:log(line)
  table.insert(LOG, line)
  -- Stream log via TCP if connected
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

local phase = "init"  -- init -> waitload -> stabilize -> preflight -> battle -> monitoring -> done
local frameCount = 0
local phaseFrame = 0

-- Save state loaded flag
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
  maxFrames = 10800,  -- ~180 seconds (intro animations need time + key simulation per turn)
  prevBmf = nil,
  execStuckFrame = nil,    -- Tracks when exec flags got stuck (safety timeout)
  execStuckValue = nil,    -- Which bits were stuck
  bmfForceAdvanced = false,  -- Whether we force-advanced gBattleMainFunc past DoBattleIntro
  bmfAdvanceFrame = nil,     -- Frame when BMF was force-advanced
  battleResPtr = nil,        -- Cached gBattleResources pointer
  turnsInjected = 0,         -- Count of turns auto-injected
  outcomeFrame = nil,        -- Frame when battle outcome was first detected
  introComplete = false,     -- Whether DoBattleIntro completed naturally
  introStuckFrame = nil,     -- Frame when intro got stuck (for 1200-frame timeout)
  -- Key simulation state v2 (state-driven based on gBattleCommunication)
  keyPhase = nil,            -- nil/"idle"/"wait_render"/"pressing"/"wait_response"/"wait_turn"/"force_press"
  keyHoldTimer = 0,          -- Frames in current key phase
  keyTarget = nil,           -- "fight" or "move" — what we're trying to select
  prevCommForKey = nil,      -- Previous comm[0] for change detection
  turnInputAttempts = 0,     -- Number of A press attempts this turn
  idleTimer = 0,             -- Frames spent idle (for stuck detection)
  turnStartFrame = nil,      -- Frame when current turn's action selection started
  prevPlayerHP = nil,        -- Track HP changes between turns
  prevEnemyHP = nil,
}

-- Saved originals for restore
local originals = { rom = {} }

-- ============================================================
-- TCP socket for sending results (mGBA sandboxes io.open)
-- ============================================================
local resultSocket = nil
local socketConnected = false

local function connectResultSocket()
  pcall(function()
    resultSocket = socket.connect("127.0.0.1", 9999)
    if resultSocket then
      socketConnected = true
      console:log("[RunTest] Connected to result listener on port 9999")
    end
  end)
end

local function sendResult(text)
  if socketConnected and resultSocket then
    pcall(function() resultSocket:send(text .. "\n") end)
  end
end

local function closeResultSocket()
  if resultSocket then
    pcall(function() resultSocket:close() end)
    resultSocket = nil
    socketConnected = false
  end
end

-- Write results via TCP socket and also try io.open as fallback
local function writeResults()
  -- Build result text
  local lines = {}
  for _, line in ipairs(LOG) do
    table.insert(lines, line)
  end
  table.insert(lines, "")
  table.insert(lines, "--- RESULT ---")
  if mon.battleMainReached then
    table.insert(lines, "SUCCESS: BattleMainCB2 reached at frame " .. tostring(mon.firstBattleCb2Frame))
  elseif mon.inBattleTriggered then
    table.insert(lines, "PARTIAL: inBattle=1 but BattleMainCB2 never reached")
  else
    table.insert(lines, "FAILED: Battle did not start")
  end

  -- Send via TCP
  if socketConnected then
    for _, line in ipairs(lines) do
      sendResult(line)
    end
    closeResultSocket()
    log("Results sent via TCP socket")
  end

  -- Also try io.open as fallback (may work if loaded manually)
  pcall(function()
    local f = io.open(projectRoot .. "battle_init_results.txt", "w")
    if f then
      for _, line in ipairs(lines) do f:write(line .. "\n") end
      f:close()
    end
  end)
end

-- Take screenshot
local function takeScreenshot(name)
  pcall(function()
    local ssPath = projectRoot .. name .. ".png"
    emu:screenshot(ssPath)
    log("Screenshot saved: " .. ssPath)
  end)
end

-- ============================================================
-- Phase: battle setup
-- ============================================================
local function doBattleSetup()
  log("=== Step 1: Copy party ===")
  local partyCount = sr8(CFG.gPlayerPartyCount) or 0
  logf("Player party count: %d", partyCount)
  if partyCount == 0 or partyCount > 6 then
    log("FAIL: Invalid party count")
    return false
  end

  -- Read player party
  local partyData = {}
  local baseR = toWRAM(CFG.gPlayerParty)
  local okR = pcall(function()
    for i = 0, CFG.PARTY_SIZE-1 do partyData[i+1] = emu.memory.wram:read8(baseR+i) end
  end)
  if not okR or #partyData ~= CFG.PARTY_SIZE then
    log("FAIL: Could not read gPlayerParty")
    return false
  end
  logf("Read %d bytes from gPlayerParty", #partyData)

  -- Write to enemy party (direct injection — will be overwritten by CB2_HandleStartBattle cases)
  local baseW = toWRAM(CFG.gEnemyParty)
  local okW = pcall(function()
    for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(baseW+i-1, partyData[i]) end
  end)
  if not okW then log("FAIL: Could not write gEnemyParty") return false end
  sw8(CFG.gEnemyPartyCount, partyCount)
  logf("Wrote %d bytes to gEnemyParty, count=%d", CFG.PARTY_SIZE, partyCount)

  -- CRITICAL: Write party data to gBlockRecvBuffer[1] (enemy slot for master)
  -- CB2_HandleStartBattle Cases 4/8/12 copy FROM gBlockRecvBuffer TO gEnemyParty
  -- Without this, they overwrite our injection with zeros
  -- Each case copies 200 bytes (2 Pokemon × 100 bytes) from sequential offsets
  local enemySlot = 1  -- For master (GetMultiplayerId=0), enemy is slot 1
  local bufBase = toWRAM(CFG.gBlockRecvBuffer + enemySlot * CFG.gBlockRecvBufferStride)
  pcall(function()
    -- Case 2 reads vsScreenHealthFlags from gBlockRecvBuffer[enemy][1] (byte index 1)
    -- Build health flags: 2 bits per slot (0=empty, 1=healthy, 2=statused/egg, 3=fainted)
    local healthFlags = 0
    for i = 0, 5 do
      local off = i * CFG.POKEMON_SIZE
      -- Read species (first 2 bytes of encrypted data would need decryption,
      -- but we can check if personality (bytes 0-3) is nonzero = valid pokemon)
      local personality = partyData[off+1] + partyData[off+2]*256 + partyData[off+3]*65536 + partyData[off+4]*16777216
      if personality ~= 0 then
        -- Read HP (at HP_OFFSET from mon base)
        local hp = partyData[off + CFG.HP_OFFSET + 1] + partyData[off + CFG.HP_OFFSET + 2] * 256
        if hp > 0 then
          healthFlags = healthFlags | (1 << (i * 2))  -- 1 = healthy
        else
          healthFlags = healthFlags | (3 << (i * 2))  -- 3 = fainted
        end
      end
      -- 0 = empty slot (no bits set)
    end
    logf("vsScreenHealthFlags for enemy = 0x%04X", healthFlags)

    -- Write LinkBattlerHeader to gBlockRecvBuffer[enemy]
    -- Struct: {u8 versionSigLo, u8 versionSigHi, u8 healthFlagsLo, u8 healthFlagsHi, ...}
    -- gBlockRecvBuffer is u16[] — VS screen reads [enemy][1] = bytes 2-3 = health flags
    emu.memory.wram:write8(bufBase + 0, 0)  -- versionSignatureLo
    emu.memory.wram:write8(bufBase + 1, 0)  -- versionSignatureHi
    emu.memory.wram:write8(bufBase + 2, healthFlags & 0xFF)  -- vsScreenHealthFlagsLo
    emu.memory.wram:write8(bufBase + 3, (healthFlags >> 8) & 0xFF)  -- vsScreenHealthFlagsHi

    -- NOTE: We do NOT write party data to gBlockRecvBuffer because Cases 4/8/12
    -- each read from the same buffer at offset 0, overwriting the header.
    -- Instead, party data is injected directly into gEnemyParty and re-injected
    -- every 10 frames during monitoring. The gBlockRecvBuffer only needs the
    -- health flags (bytes 2-3) for the VS screen in Case 2.
  end)
  log("Wrote party data + healthFlags to gBlockRecvBuffer[1]")

  -- Set up gLinkPlayers struct entries (28 bytes each)
  -- Struct layout: version(+0x00,u16), lp_field_2(+0x02), trainerId(+0x04,u32),
  --   name(+0x08,8bytes), progressFlags(+0x10), neverRead(+0x11),
  --   progressFlagsCopy(+0x12), gender(+0x13,u8), linkType(+0x14,u32),
  --   id(+0x18,u16), language(+0x1A,u16)
  local lpBase = toWRAM(CFG.gLinkPlayers)
  local VERSION_EMERALD = 3
  local LINKTYPE_SINGLE_BATTLE = 0x2233
  local LANGUAGE_ENGLISH = 2
  pcall(function()
    -- Player 0 (master/local)
    emu.memory.wram:write16(lpBase + 0x00, VERSION_EMERALD)  -- version
    emu.memory.wram:write8(lpBase + 0x13, 0)  -- gender = male
    emu.memory.wram:write32(lpBase + 0x14, LINKTYPE_SINGLE_BATTLE)  -- linkType
    emu.memory.wram:write16(lpBase + 0x18, 0)  -- id = 0
    emu.memory.wram:write16(lpBase + 0x1A, LANGUAGE_ENGLISH)  -- language
    -- Player 1 (client/remote = opponent)
    local p1 = lpBase + 0x1C
    emu.memory.wram:write16(p1 + 0x00, VERSION_EMERALD)  -- version
    emu.memory.wram:write8(p1 + 0x13, 0)  -- gender = male
    emu.memory.wram:write32(p1 + 0x14, LINKTYPE_SINGLE_BATTLE)  -- linkType
    emu.memory.wram:write16(p1 + 0x18, 1)  -- id = 1
    emu.memory.wram:write16(p1 + 0x1A, LANGUAGE_ENGLISH)  -- language
  end)
  log("Set up gLinkPlayers entries (version, gender, linkType, id, language)")

  -- Verify
  local ep = sr32(CFG.gEnemyParty)
  local pp = sr32(CFG.gPlayerParty)
  logf("Player personality=%s Enemy personality=%s match=%s", hex(pp), hex(ep), tostring(ep==pp))
  mon.partyData = partyData

  log("=== Step 2: Set gBattleTypeFlags ===")
  local flags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER | CFG.BATTLE_TYPE_RECORDED_LINK
  sw32(CFG.gBattleTypeFlags, flags)
  logf("gBattleTypeFlags = %s", hex(sr32(CFG.gBattleTypeFlags)))

  -- Clear link status byte (must be 0 for BattleMainCB2 to proceed)
  sw8(CFG.linkStatusByte, 0)

  log("=== Step 3: ROM patches ===")
  originals.rom = {}
  local patchCount = 0

  -- GetMultiplayerId
  local g = CFG.patches.getMultiplayerId
  local o1, o2 = rr16(g.romOffset), rr16(g.romOffset+2)
  if wrv16(g.romOffset, g.value1) then
    table.insert(originals.rom, {off=g.romOffset, val=o1, sz=2})
    patchCount = patchCount + 1
  end
  if wrv16(g.romOffset+2, g.value2) then
    table.insert(originals.rom, {off=g.romOffset+2, val=o2, sz=2})
    patchCount = patchCount + 1
  end

  -- Other patches
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
  logf("IWRAM: wireless=0, remotePlayers=1, blockStatus=0x0F")

  log("=== Step 5: gMain setup ===")
  -- Save callback1
  local cb1 = sr32(CFG.callback1Addr)
  logf("Original callback1 = %s", hex(cb1))

  -- Set savedCallback = CB2_Overworld
  sw32(CFG.savedCallbackAddr, CFG.cb2Overworld)
  logf("savedCallback = %s (CB2_Overworld)", hex(CFG.cb2Overworld))

  -- NULL callback1
  sw32(CFG.callback1Addr, 0)
  logf("callback1 = 0x00000000 (NULL)")

  -- Reset state
  sw8(CFG.gMainStateAddr, 0)

  -- Clear gBattleCommunication[0]
  sw8(CFG.gBattleCommunication, 0)

  log("=== Step 6: Trigger battle ===")
  -- NOTE: Do NOT blank palette — the battle engine handles its own palette fade-in
  -- Blanking prevented the battle from showing anything on screen

  -- CRITICAL: Clear ALL simulated keys to prevent stale A button
  -- If A button was pressed during save state, it persists and causes
  -- HandleInputChooseAction to auto-select immediately
  pcall(function() emu:clearKey(0) end)  -- A
  pcall(function() emu:clearKey(1) end)  -- B
  pcall(function() emu:clearKey(2) end)  -- Select
  pcall(function() emu:clearKey(3) end)  -- Start
  pcall(function() emu:clearKey(4) end)  -- Right
  pcall(function() emu:clearKey(5) end)  -- Left
  pcall(function() emu:clearKey(6) end)  -- Up
  pcall(function() emu:clearKey(7) end)  -- Down
  log("Cleared all simulated keys")

  -- Set callback2 = CB2_InitBattle
  sw32(CFG.callback2Addr, CFG.CB2_InitBattle)
  local vcb2 = sr32(CFG.callback2Addr)
  if vcb2 == CFG.CB2_InitBattle then
    logf("callback2 = %s (CB2_InitBattle) VERIFIED", hex(vcb2))
  else
    logf("FAIL: callback2 = %s (expected %s)", hex(vcb2), hex(CFG.CB2_InitBattle))
    return false
  end

  log(">>> BATTLE TRIGGERED <<<")
  return true
end

-- (Window reveal helpers removed — let engine manage windows naturally)

-- ============================================================
-- Phase: monitoring frame handler
-- ============================================================
local function monitorFrame()
  local f = frameCount - phaseFrame

  local cb2 = sr32(CFG.callback2Addr)
  local rawIB = sr8(CFG.gMainInBattle)
  local inBattle = rawIB and (((rawIB & 0x02) ~= 0) and 1 or 0) or nil
  local comm0 = sr8(CFG.gBattleCommunication)
  local bmf = sr32(0x03005D04) -- gBattleMainFunc (IWRAM)

  -- Transitions
  if cb2 ~= mon.prevCb2 then
    local msg = string.format("f%d: cb2 %s -> %s", f, labelCb2(mon.prevCb2), labelCb2(cb2))
    logf(">>> %s", msg)
    table.insert(mon.transitions, msg)
    if cb2 and not mon.cb2History[cb2] then mon.cb2History[cb2] = f end
    mon.prevCb2 = cb2
  end

  if inBattle ~= mon.prevInBattle then
    local msg = string.format("f%d: inBattle %s -> %s", f, tostring(mon.prevInBattle), tostring(inBattle))
    logf(">>> %s", msg)
    table.insert(mon.transitions, msg)
    if inBattle == 1 then mon.inBattleTriggered = true end
    mon.prevInBattle = inBattle
  end

  if comm0 ~= mon.prevComm0 then
    local msg = string.format("f%d: comm[0] %s -> %s", f, tostring(mon.prevComm0), tostring(comm0))
    logf(">>> %s", msg)
    table.insert(mon.transitions, msg)
    mon.prevComm0 = comm0
  end

  -- Track gBattleMainFunc transitions
  if bmf ~= mon.prevBmf then
    local msg = string.format("f%d: bmf %s -> %s", f, hex(mon.prevBmf), hex(bmf))
    logf(">>> %s", msg)
    table.insert(mon.transitions, msg)

    -- CRASH DIAGNOSTIC: If bmf goes to 0 or an unexpected address, dump full state
    if (bmf == nil or bmf == 0) and mon.prevBmf and mon.prevBmf ~= 0 then
      logf("  *** CRASH DETECTED *** bmf went to 0 from %s!", hex(mon.prevBmf))
      local outcome = sr8(CFG.gBattleOutcome)
      local turnCnt = sr16(CFG.gBattleTurnCounter)
      local ef = sr32(CFG.gBattleControllerExecFlags)
      local ab = sr8(CFG.gActiveBattler)
      local btf = sr32(CFG.gBattleTypeFlags)
      logf("  [CRASH] outcome=%d turnCnt=%d ef=%s ab=%d btf=%s",
        outcome or -1, turnCnt or -1, hex(ef), ab or -1, hex(btf))
      local sp0 = sr16(0x020233FC)
      local sp1 = sr16(0x020233FC + 0x5C)
      local hp0 = sr16(0x020233FC + 0x2A)
      local hp1 = sr16(0x020233FC + 0x5C + 0x2A)
      logf("  [CRASH] species=%d/%d hp=%d/%d", sp0 or -1, sp1 or -1, hp0 or -1, hp1 or -1)
      takeScreenshot(string.format("crash_f%04d", f))
    end

    mon.prevBmf = bmf

    -- Track DoBattleIntro completion
    if mon.prevBmf == CFG.DoBattleIntro and bmf ~= CFG.DoBattleIntro and bmf ~= 0 then
      logf("  [INTRO] DoBattleIntro completed naturally -> %s", hex(bmf))
      mon.introComplete = true
    end
  end

  -- BattleMainCB2 reached?
  if cb2 == CFG.CB2_BattleMain and not mon.battleMainReached then
    mon.battleMainReached = true
    mon.firstBattleCb2Frame = f
    logf("***** SUCCESS: BattleMainCB2 at frame %d *****", f)
    takeScreenshot("battle_main_reached")

    -- CRITICAL FIX (2-part):
    -- Part 1: Clear BATTLE_TYPE_LINK from gBattleTypeFlags
    -- During init (CB2_InitBattle → CB2_HandleStartBattle), LINK flag is needed for VS screen,
    -- link player data exchange, etc. But once BattleMainCB2 starts, LINK causes:
    --   - ExecCompleted functions to use PrepareBufferDataTransferLink (never completes)
    --   - BattleMain_HandleControllerState to use link exec path (bits 28-31)
    --   - HandleTurnActionSelectionState to use link state machine (not local menu)
    -- By clearing LINK here, the battle runs as a normal local trainer battle:
    --   - All animations work (opponent controller handles them locally)
    --   - Fight/Bag/Pokemon/Run menu appears normally
    --   - Exec flags clear via MarkBattleControllerIdleOnLocal (bits 0-3)
    local btf = sr32(CFG.gBattleTypeFlags)
    local newBtf = btf & ~CFG.BATTLE_TYPE_LINK  -- Clear bit 1 (LINK)
    newBtf = newBtf & ~CFG.BATTLE_TYPE_LINK_IN_BATTLE  -- Clear bit 5 (LINK_IN_BATTLE — IsLinkBattle() checks THIS!)
    newBtf = newBtf & ~CFG.BATTLE_TYPE_RECORDED_LINK  -- Clear bit 24 (RECORDED)
    sw32(CFG.gBattleTypeFlags, newBtf)
    logf("  [FIX] Cleared LINK+LINK_IN_BATTLE+RECORDED: %s -> %s", hex(btf), hex(newBtf))

    -- Part 2: Replace link opponent controller with regular opponent controller
    -- NOTE: This test always uses isMaster=true, so opponent=battler 1, player=battler 0
    -- For slave (isMaster=false), opponent=battler 0, player=battler 1 (see battle.lua)
    local cf1 = sr32(CFG.gBattlerControllerFuncs + 4)
    logf("  [FIX] Replacing ctrl[1] from %s with OpponentBufferRunCommand %s",
      hex(cf1), hex(CFG.OpponentBufferRunCommand))
    sw32(CFG.gBattlerControllerFuncs + 4, CFG.OpponentBufferRunCommand)

    -- Part 3: Clear gReceivedRemoteLinkPlayers so HandleLinkConnection doesn't block callbacks
    sw8(CFG.gReceivedRemoteLinkPlayers, 0)
    logf("  [FIX] Cleared gReceivedRemoteLinkPlayers")
  end

  -- CONTROLLER MONITORING + DIAGNOSTIC SCREENSHOTS
  -- Encode key state in screenshot filenames since io.open and TCP are sandboxed
  if mon.battleMainReached then
    local framesSinceBMC = f - (mon.firstBattleCb2Frame or 0)

    -- Read controller funcs from IWRAM every frame for change tracking
    local cf0 = sr32(CFG.gBattlerControllerFuncs) or 0
    local cf1 = sr32(CFG.gBattlerControllerFuncs + 4) or 0

    if cf0 ~= mon.prevCf0 or cf1 ~= mon.prevCf1 then
      logf("  [CTRL] f+%d: [0]=%s [1]=%s", framesSinceBMC, hex(cf0), hex(cf1))
      mon.prevCf0 = cf0
      mon.prevCf1 = cf1
    end
  end

  -- Take periodic screenshots with diagnostic data encoded in filename
  local shouldScreenshot = false
  if f <= 10 then
    shouldScreenshot = (f == 1 or f == 5 or f == 10)
  elseif f <= 800 then
    shouldScreenshot = (f % 50 == 0)
  elseif f <= 2000 then
    shouldScreenshot = (f % 100 == 0)
  else
    shouldScreenshot = (f % 300 == 0)
  end
  if shouldScreenshot then
    -- Build diagnostic filename
    local ef = sr32(CFG.gBattleControllerExecFlags) or 0
    local cf0 = sr32(CFG.gBattlerControllerFuncs) or 0
    local cf1 = sr32(CFG.gBattlerControllerFuncs + 4) or 0
    local bmfV = sr32(CFG.gBattleMainFunc) or 0
    local pal0 = 0
    pcall(function() pal0 = emu.memory.palette:read16(0) end)

    -- Also read gBattleCommunication[0] and [1] for battler state tracking
    local comm0v = sr8(CFG.gBattleCommunication) or 9
    local comm1v = sr8(CFG.gBattleCommunication + 1) or 9

    -- Also read gBattleTypeFlags and gChosenActionByBattler for diagnostics
    local btfV = sr32(CFG.gBattleTypeFlags) or 0
    local act0v = sr8(CFG.gChosenActionByBattler) or 9
    local act1v = sr8(CFG.gChosenActionByBattler + 1) or 9

    -- Encode in filename: frame, bmf, ef, comm, btf(low byte), act, ctrl, pal
    local name = string.format("B_f%04d_bmf%04X_ef%02X_co%d%d_btf%02X_a%d%d_c0_%04X_c1_%04X",
      f, bmfV & 0xFFFF, ef & 0xFF, comm0v, comm1v, btfV & 0xFF, act0v, act1v, cf0 & 0xFFFF, cf1 & 0xFFFF)
    takeScreenshot(name)
  end

  -- Re-inject enemy party every 10 frames (prevents CB2_HandleStartBattle cases from zeroing it)
  if f % 10 == 0 and mon.partyData then
    local bw = toWRAM(CFG.gEnemyParty)
    pcall(function()
      for i = 1, CFG.PARTY_SIZE do emu.memory.wram:write8(bw+i-1, mon.partyData[i]) end
    end)
    pcall(function()
      local pc = r8(CFG.gPlayerPartyCount)
      w8(CFG.gEnemyPartyCount, pc)
    end)
    -- Re-write VS screen health flags in gBlockRecvBuffer[enemy] at bytes 2-3
    -- This persists through CB2_HandleStartBattle Case 2 which reads [enemy][1] (u16 at bytes 2-3)
    local bufBase = toWRAM(CFG.gBlockRecvBuffer + 1 * CFG.gBlockRecvBufferStride)
    pcall(function()
      emu.memory.wram:write8(bufBase + 2, 0x01)  -- healthFlagsLo: 1 healthy Pokemon
      emu.memory.wram:write8(bufBase + 3, 0x00)  -- healthFlagsHi: empty
    end)
  end

  -- Enforce gBattlersCount=2 EVERY FRAME
  sw8(0x020233E4, 2)
  -- Clamp gActiveBattler to 0 or 1
  local ab = sr8(CFG.gActiveBattler)
  if ab and ab >= 2 then
    sw8(CFG.gActiveBattler, ab & 1)
  end

  -- Maintain IWRAM every 10 frames
  if f % 10 == 0 then
    sw8(CFG.gWirelessCommType, 0)
    -- AFTER BattleMainCB2: keep gReceivedRemoteLinkPlayers=0 (not 1!)
    -- During init: keep it at 1 so link exchange completes
    if mon.battleMainReached then
      sw8(CFG.gReceivedRemoteLinkPlayers, 0)
    else
      sw8(CFG.gReceivedRemoteLinkPlayers, 1)
      for i = 0,3 do sw8(CFG.gBlockReceivedStatus+i, 0x0F) end
    end
  end

  -- Maintain gBattleTypeFlags
  if f % 4 == 0 then
    local currentFlags = sr32(CFG.gBattleTypeFlags)
    if currentFlags ~= nil then
      if mon.battleMainReached then
        -- AFTER BattleMainCB2: keep TRAINER + IS_MASTER, but NOT LINK or RECORDED_LINK
        local requiredFlags = CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER
        local unwantedFlags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_LINK_IN_BATTLE | CFG.BATTLE_TYPE_RECORDED_LINK
        local merged = (currentFlags | requiredFlags) & ~unwantedFlags
        if merged ~= currentFlags then
          sw32(CFG.gBattleTypeFlags, merged)
        end
      else
        -- DURING INIT: keep all flags including LINK
        local requiredFlags = CFG.BATTLE_TYPE_LINK | CFG.BATTLE_TYPE_TRAINER | CFG.BATTLE_TYPE_IS_MASTER | CFG.BATTLE_TYPE_RECORDED_LINK
        local merged = currentFlags | requiredFlags
        if merged ~= currentFlags then
          sw32(CFG.gBattleTypeFlags, merged)
        end
      end
    end
  end

  -- Keep link status byte clear
  if f % 10 == 0 then
    sw8(CFG.linkStatusByte, 0)
  end

  -- CONTROLLER UNBLOCK: Find gBattleSpritesDataPtr and force healthbox flags
  -- This unblocks Intro_TryShinyAnimShowHealthbox which waits for:
  --   waitForCry==FALSE, finishedShinyMonAnim==TRUE, ballAnimActive==FALSE
  -- These can get stuck because our emulated link battle doesn't have proper audio/animation context
  if mon.battleMainReached and f % 5 == 0 then
    -- Find gBattleSpritesDataPtr (runtime probe)
    if not mon.gBattleSpritesDataPtr then
      for _, candidate in ipairs(CFG.gBattleSpritesDataPtr_candidates) do
        local ptr = sr32(candidate)
        if ptr and ptr >= 0x02000000 and ptr < 0x02040000 then
          -- Validate: should have 4 sub-pointers (battlerData, healthBoxesData, animationData, battleBars)
          local sub0 = sr32(ptr)
          local sub1 = sr32(ptr + 4)
          local sub2 = sr32(ptr + 8)
          local sub3 = sr32(ptr + 12)
          local validSubs = 0
          for _, s in ipairs({sub0, sub1, sub2, sub3}) do
            if s and s >= 0x02000000 and s < 0x02040000 then validSubs = validSubs + 1 end
          end
          if validSubs >= 3 then  -- At least 3 valid heap pointers
            mon.gBattleSpritesDataPtr = candidate
            mon.spritesDataHeap = ptr
            logf("  [CTRL] Found gBattleSpritesDataPtr at %s -> heap %s (subs: %s %s %s %s)",
              hex(candidate), hex(ptr), hex(sub0), hex(sub1), hex(sub2), hex(sub3))
            -- healthBoxesData is at offset +0x04
            mon.healthBoxesData = sub1
            -- animationData is at offset +0x08
            mon.animationData = sub2
            break
          end
        end
      end
    end

    -- Force healthbox flags to unblock controller callback chain
    if mon.healthBoxesData then
      local hbd = mon.healthBoxesData
      for battler = 0, 1 do
        local base = hbd + battler * CFG.HEALTHBOX_SIZE
        local byte0 = sr8(base + 0) or 0
        local byte1 = sr8(base + 1) or 0

        local waitForCry = (byte1 & 0x40) ~= 0
        local finishedShiny = (byte1 & 0x01) ~= 0
        local ballActive = (byte0 & 0x08) ~= 0
        local healthboxStarted = (byte1 & 0x80) ~= 0

        -- Force waitForCry = FALSE (clear bit 6 of byte 1)
        if waitForCry then
          sw8(base + 1, byte1 & ~0x40)
          if not mon.cryClearLogged then
            logf("  [CTRL] Cleared waitForCry for battler %d at f=%d", battler, f)
          end
        end

        -- Force finishedShinyMonAnim = TRUE (set bit 0 of byte 1) after 120 frames of battle
        -- Force bgmRestored = TRUE (set bit 5 of byte 1) — another gate in Intro_TryShinyAnimShowHealthbox
        local framesSinceBMC = f - (mon.firstBattleCb2Frame or 0)
        if framesSinceBMC > 120 then
          byte1 = sr8(base + 1) or 0
          local newByte1 = byte1 | 0x01 | 0x20  -- finishedShinyMonAnim + bgmRestored
          if newByte1 ~= byte1 then
            sw8(base + 1, newByte1)
            if not mon.shinyClearLogged then
              logf("  [CTRL] Set finishedShinyMonAnim+bgmRestored for battler %d at f=%d", battler, f)
            end
          end
        end

        -- Log detailed state periodically
        if f % 60 == 0 and battler == 0 then
          local bgmRestored = (byte1 & 0x20) ~= 0
          logf("  [CTRL] b%d: ball=%s cry=%s shiny=%s hbox=%s bgm=%s",
            battler, tostring(ballActive), tostring(waitForCry),
            tostring(finishedShiny), tostring(healthboxStarted), tostring(bgmRestored))
        end
      end
      mon.cryClearLogged = true
      mon.shinyClearLogged = true
    end

    -- Dump gBattleSpritesDataPtr discovery results via screenshot filename
    if not mon.ctrlDiagDone and f % 60 == 0 then
      local diagParts = {}
      -- Check all candidates
      for i, candidate in ipairs(CFG.gBattleSpritesDataPtr_candidates) do
        local ptr = sr32(candidate) or 0
        table.insert(diagParts, string.format("c%d_%X_%X", i, candidate & 0xFFFF, ptr & 0xFFFF))
      end
      -- Also show found state
      if mon.gBattleSpritesDataPtr then
        local hbd = mon.healthBoxesData or 0
        local b0_0 = sr8(hbd) or 0xFF
        local b0_1 = sr8(hbd + 1) or 0xFF
        local b1_0 = sr8(hbd + CFG.HEALTHBOX_SIZE) or 0xFF
        local b1_1 = sr8(hbd + CFG.HEALTHBOX_SIZE + 1) or 0xFF
        table.insert(diagParts, string.format("hbd_%X_b0_%02X%02X_b1_%02X%02X",
          hbd & 0xFFFF, b0_0, b0_1, b1_0, b1_1))
      else
        table.insert(diagParts, "NOT_FOUND")
      end
      local diagName = "diag_f" .. f .. "_" .. table.concat(diagParts, "_")
      takeScreenshot(diagName)
      if f > 300 then mon.ctrlDiagDone = true end  -- Only dump a few times
    end
  end

  -- EXEC FLAGS STRATEGY (v4 — proper patches, natural completion):
  --
  -- With isBattlerExecLocal + markBattlerExecLocal + markAllBattlersExecLocal patches,
  -- all exec flag operations use bits 0-3 (local path). The patched BufferExecCompleted
  -- functions (playerBufExecSkip, linkOpponentBufExecSkip) call MarkBattleControllerIdleOnLocal
  -- which properly clears bits 0-3 when controllers finish.
  --
  -- We only need to:
  -- 1. Strip stray bits 28-31 (shouldn't appear now, but safety)
  -- 2. Strip bits 4-27 (per-player link bits, not used)
  -- 3. Safety clear if bits 0-3 stuck for 180+ frames (something went very wrong)
  local execFlags = sr32(CFG.gBattleControllerExecFlags)

  if execFlags and execFlags ~= 0 then
    -- Strip everything except bits 0-3 (local controller active flags)
    local localBits = execFlags & 0x0000000F
    local strayBits = execFlags & 0xFFFFFFF0

    -- Always clear stray bits immediately
    if strayBits ~= 0 then
      sw32(CFG.gBattleControllerExecFlags, localBits)
    end

    -- Track stuck local bits with CONTEXT-AWARE timeout
    -- CRITICAL: During HandleTurnActionSelectionState, exec flags are INTENTIONALLY set
    -- while the player controller waits for input. Clearing them prematurely breaks the menu.
    if localBits ~= 0 then
      if not mon.execStuckFrame then
        mon.execStuckFrame = f
        mon.execStuckValue = localBits
      end
      -- Reset counter when exec value changes (different operation in progress)
      if localBits ~= mon.execStuckValue then
        mon.execStuckFrame = f
        mon.execStuckValue = localBits
      end
      local stuckDuration = f - mon.execStuckFrame

      -- Context-aware timeout:
      -- During HandleTurnActionSelectionState: NEVER clear (player input expected, unlimited time)
      -- During DoBattleIntro: 200 frames — balanced timeout:
      --   - GetMonData completes naturally in ~160 frames ✓
      --   - Pokeball throw animation is ~130 frames ✓
      --   - Genuinely stuck handlers (e.g., 0x08071B65) cleared after 200 frames
      --   - 30 frames was too aggressive (killed animations before completing)
      --   - 999999 was too passive (stuck handlers blocked intro forever at state 2)
      -- Default: 180 frames
      local safetyTimeout = 180
      if bmf == CFG.HandleTurnActionSelectionState then
        safetyTimeout = 999999  -- Effectively disabled
      elseif bmf == CFG.DoBattleIntro then
        safetyTimeout = 200  -- Balanced: lets animations complete, clears stuck handlers
      end

      if stuckDuration >= safetyTimeout then
        logf("  [EXEC] SAFETY: Force-cleared bits 0x%X after %d frames (bmf=%s)", localBits, stuckDuration, hex(bmf))
        sw32(CFG.gBattleControllerExecFlags, 0)
        mon.execStuckFrame = nil
        mon.execStuckValue = nil
      end
    else
      mon.execStuckFrame = nil
      mon.execStuckValue = nil
    end
  else
    mon.execStuckFrame = nil
    mon.execStuckValue = nil
  end
  -- ============================================================
  -- POST-BattleMainCB2 LOGIC
  -- ============================================================
  if mon.battleMainReached then
    local framesSinceBMC = f - mon.firstBattleCb2Frame

    -- Cache gBattleResources pointer early
    if not mon.battleResPtr then
      local resPtr = sr32(CFG.gBattleResources)
      if resPtr and resPtr >= 0x02000000 and resPtr < 0x02040000 then
        mon.battleResPtr = resPtr
        logf("  [RES] Cached gBattleResources=%s at f+%d", hex(resPtr), framesSinceBMC)
      end
    end

    -- STRATEGY (v3): Aggressive 3-frame exec clearing lets DoBattleIntro race
    -- through all 20 states in ~60 frames. Force-advance after 300 frames if still stuck.
    -- After intro completes, wait 200 frames for sprite animations before turns.

    local currentBmf = sr32(CFG.gBattleMainFunc)

    -- Track DoBattleIntro progress
    if currentBmf == CFG.DoBattleIntro then
      if not mon.introStuckFrame then
        mon.introStuckFrame = framesSinceBMC
      end
      local introStuckDuration = framesSinceBMC - mon.introStuckFrame
      if introStuckDuration >= 5400 and not mon.bmfForceAdvanced then
        -- DoBattleIntro stuck for 5400 frames (~90 sec) — force-advance as last resort
        -- With 200-frame exec clearing per state and ~20 states, intro should complete
        -- in ~4000 frames. If it hasn't by 5400, something is very wrong.
        logf("  [BMF] DoBattleIntro stuck for %d frames, FORCE-ADVANCING", introStuckDuration)
        sw32(CFG.gBattleControllerExecFlags, 0)
        sw32(CFG.gBattleMainFunc, CFG.TryDoEventsBeforeFirstTurn)
        mon.bmfForceAdvanced = true
        mon.bmfAdvanceFrame = framesSinceBMC
        takeScreenshot("forced_intro_skip")
      end
    else
      mon.introStuckFrame = nil  -- Reset if not stuck
      -- DoBattleIntro has advanced to another function — track it
      if currentBmf == CFG.TryDoEventsBeforeFirstTurn and not mon.introComplete then
        logf("  [INTRO] Reached TryDoEventsBeforeFirstTurn at f+%d", framesSinceBMC)
        mon.introComplete = true
        mon.introCompleteFrame = framesSinceBMC
        takeScreenshot("intro_complete")
      end
      if currentBmf == CFG.HandleTurnActionSelectionState and not mon.actionMenuReached then
        logf("  [INTRO] Reached HandleTurnActionSelectionState NATURALLY at f+%d!", framesSinceBMC)
        mon.introComplete = true
        mon.introCompleteFrame = framesSinceBMC
        mon.actionMenuReached = true
        mon.bmfForceAdvanced = true
        mon.bmfAdvanceFrame = framesSinceBMC
        takeScreenshot("action_menu_natural")
      end
    end

    -- PALETTE FADE FORCE-COMPLETE: After intro is done or force-skipped,
    -- force the screen back to normal colors.
    --
    -- gPaletteFade struct layout (at 0x02037594):
    --   +0x00: multipurpose1 (selectedPalettes)
    --   +0x04: bld0 pointer
    --   +0x08: bld1 pointer
    --   +0x0C: BITFIELD WORD 1 — weight(9), delayCounter(6), y(5), targetY(5), multipurpose2(6), active(1)
    --   +0x10: BITFIELD WORD 2 — blendColor(15), yDec(1), bufferTransferDisabled(1), mode(2), ...deltaY(4)
    --
    -- active = bit 31 of word at +0x0C
    -- y = bits 15-19 of word at +0x0C (current blend: 0=normal, 16=full black)
    -- targetY = bits 20-24 of word at +0x0C
    -- bufferTransferDisabled = bit 16 of word at +0x10
    --
    -- Strategy: We try THREE approaches in order:
    -- 1. If fade is active with y > 0, set y=0 + targetY=0 to make it complete
    -- 2. If fade is NOT active but screen is dark, start a new fade-back
    -- 3. Direct buffer copy as last resort
    if mon.introComplete or mon.bmfForceAdvanced then
      -- Wait 30 frames after intro complete before forcing (give engine a chance)
      local introEndFrame = mon.bmfAdvanceFrame or mon.introCompleteFrame or 0
      local sinceIntroEnd = framesSinceBMC - introEndFrame

      if sinceIntroEnd >= 30 and not mon.paletteForcedFrame then
        local gPF = CFG.gPaletteFade  -- 0x02037594
        local word1 = sr32(gPF + 0x0C) or 0
        local word2 = sr32(gPF + 0x10) or 0

        local y = (word1 >> 15) & 0x1F
        local targetY = (word1 >> 20) & 0x1F
        local active = (word1 >> 31) & 0x01
        local bufDisabled = (word2 >> 16) & 0x01

        logf("  [PAL] f+%d: word1=%s word2=%s y=%d targetY=%d active=%d bufDisabled=%d",
          framesSinceBMC, hex(word1), hex(word2), y, targetY, active, bufDisabled)

        -- Check if screen is still dark (read a few palette entries)
        local pal0 = nil
        local palDark = false
        pcall(function() pal0 = emu.memory.palette:read16(0) end)
        if pal0 and pal0 == 0 then palDark = true end

        if y > 0 or palDark then
          logf("  [PAL] Force-restoring palette (y=%d, dark=%s) at f+%d", y, tostring(palDark), framesSinceBMC)

          -- Approach 1: Set gPaletteFade to complete state
          -- Clear active bit, set y=0, targetY=0
          local newWord1 = word1 & 0x7E007FFF  -- Clear active(31), y(15-19), targetY(20-24)
          sw32(gPF + 0x0C, newWord1)

          -- Clear bufferTransferDisabled bit and ensure mode=NORMAL
          local newWord2 = word2 & 0xFFF8FFFF  -- Clear bufferTransferDisabled(16), mode(17-18)
          sw32(gPF + 0x10, newWord2)

          -- Approach 2: Copy gPlttBufferUnfaded → gPlttBufferFaded
          local ufOff = toWRAM(CFG.gPlttBufferUnfaded)
          local fdOff = toWRAM(CFG.gPlttBufferFaded)
          pcall(function()
            for i = 0, 1023 do
              local b = emu.memory.wram:read8(ufOff + i)
              emu.memory.wram:write8(fdOff + i, b)
            end
          end)
          logf("  [PAL] Copied gPlttBufferUnfaded -> gPlttBufferFaded (1024 bytes)")

          -- Approach 3: Also DMA the faded buffer to hardware palette directly
          -- GBA palette RAM is at 0x05000000, 1024 bytes
          -- mGBA exposes this as emu.memory.palette
          pcall(function()
            for i = 0, 511 do
              local c = emu.memory.wram:read16(fdOff + i * 2)
              emu.memory.palette:write16(i * 2, c)
            end
          end)
          logf("  [PAL] Wrote gPlttBufferFaded -> hardware palette (512 entries)")

          mon.paletteForcedFrame = framesSinceBMC
          takeScreenshot("palette_forced")
        elseif not mon.paletteOkLogged then
          logf("  [PAL] Palette looks OK at f+%d (y=%d, pal0=%s)", framesSinceBMC, y, hex16(pal0))
          mon.paletteOkLogged = true
        end
      end

      -- CONTINUOUS palette maintenance: Keep forcing normal palette every 30 frames
      -- if initial force was done but screen went dark again
      if mon.paletteForcedFrame and (framesSinceBMC - mon.paletteForcedFrame) >= 30 then
        if (framesSinceBMC - mon.paletteForcedFrame) % 30 == 0 then
          local pal0 = nil
          pcall(function() pal0 = emu.memory.palette:read16(0) end)
          if pal0 and pal0 == 0 then
            -- Screen went dark again — re-force
            local ufOff = toWRAM(CFG.gPlttBufferUnfaded)
            local fdOff = toWRAM(CFG.gPlttBufferFaded)
            pcall(function()
              for i = 0, 1023 do
                local b = emu.memory.wram:read8(ufOff + i)
                emu.memory.wram:write8(fdOff + i, b)
              end
              for i = 0, 511 do
                local c = emu.memory.wram:read16(fdOff + i * 2)
                emu.memory.palette:write16(i * 2, c)
              end
            end)
            -- Also make sure gPaletteFade is inactive
            local w1 = sr32(CFG.gPaletteFade + 0x0C) or 0
            sw32(CFG.gPaletteFade + 0x0C, w1 & 0x7E007FFF)
            logf("  [PAL] Re-forced palette at f+%d (screen went dark again)", framesSinceBMC)
          end
        end
      end
    end

    -- Detect gBattleMons init
    local BMON_SIZE = 0x5C
    local BMON_BASE = 0x020233FC
    if not mon.gBattleMonsAddr and framesSinceBMC >= 80 then
      local sp = sr16(BMON_BASE)
      if sp and sp >= 1 and sp <= 1300 then
        mon.gBattleMonsAddr = BMON_BASE
        local m0 = sr16(BMON_BASE + 0x0C)
        local hp0 = sr16(BMON_BASE + 0x2A)
        local lv0 = sr8(BMON_BASE + 0x2C)
        local mhp0 = sr16(BMON_BASE + 0x2E)
        logf("  [BMONS] Accepted gBattleMons: species=%d moves=%d hp=%d/%d lv=%d", sp, m0 or 0, hp0 or -1, mhp0 or -1, lv0 or -1)
        local sp2 = sr16(BMON_BASE + BMON_SIZE)
        local hp1 = sr16(BMON_BASE + BMON_SIZE + 0x2A)
        local lv1 = sr8(BMON_BASE + BMON_SIZE + 0x2C)
        logf("  [BMONS] Battler 1: species=%d hp=%d lv=%d", sp2 or -1, hp1 or -1, lv1 or -1)
      end
    end

    -- SPRITE DIAGNOSTICS: Check gBattlerSpriteIds and gSprites state
    -- gBattlerSpriteIds is near other battle vars in EWRAM
    -- gSprites is at a fixed EWRAM address (declared in sprite.c)
    -- Each Sprite struct is 0x44 bytes, invisible bit at +0x3E bit 2
    -- Sprite diagnostics: run every 15 frames during intro, every 60 after
    local spriteDiagInterval = mon.introComplete and 60 or 15
    if mon.battleMainReached and framesSinceBMC % spriteDiagInterval == 0 then
      -- Try to read gBattlerSpriteIds (scan near known battle vars)
      -- In pokeemerald-expansion, it's declared near gBattlersCount, gActiveBattler etc.
      -- gActiveBattler = 0x020233DC, gBattleControllerExecFlags = 0x020233E0
      -- gBattlersCount = 0x020233E4, gBattlerSpriteIds is nearby
      -- Let's scan a range for valid sprite IDs (0-63)
      if not mon.spriteIdAddr then
        -- gBattlerSpriteIds is typically between gBattlersCount and gBattleMons
        -- Try common offsets from the battle variable cluster
        local candidates = {
          0x020233E5, -- right after gBattlersCount (u8)
          0x020233E6, 0x020233E8, 0x020233EA, 0x020233EC,
          0x020233EE, 0x020233F0, 0x020233F2,
          -- Also check in the battle_main.c variable cluster
          0x02023398, 0x0202339C, 0x020233A0, 0x020233A4,
        }
        for _, addr in ipairs(candidates) do
          local v0 = sr8(addr)
          local v1 = sr8(addr + 1)
          -- Valid sprite IDs are 0-63 (MAX_SPRITES=64)
          if v0 and v0 < 64 and v1 and v1 < 64 and v0 ~= v1 then
            logf("  [SPRITEID] Candidate gBattlerSpriteIds at %s: [%d, %d]", hex(addr), v0, v1)
          end
        end
        mon.spriteIdAddr = true  -- Only scan once
      end

      -- gSprites confirmed at 0x02020630 (1655 ROM refs, stride 0x44, MAX_SPRITES=64)
      -- Vanilla was 0x020200B0, R&B shifted by +0x580
      if not mon.gSpritesBase then
        mon.gSpritesBase = 0x02020630
        logf("  [SPRITE] Using gSprites = 0x02020630 (confirmed via ROM scan)")
      end

      -- Read gBattleSpritesDataPtr to check ballAnimActive
      local bsdPtr = sr32(0x02023A10)  -- Try near gBattleResources
      if not bsdPtr or bsdPtr < 0x02000000 or bsdPtr > 0x0203FFFF then
        bsdPtr = sr32(0x02023A14)
      end
      if not bsdPtr or bsdPtr < 0x02000000 or bsdPtr > 0x0203FFFF then
        bsdPtr = sr32(0x02023A1C)
      end
      -- Log whatever we find
      if framesSinceBMC % 60 == 0 then
        local res = sr32(CFG.gBattleResources)
        logf("  [DIAG] f+%d: gBattleResources=%s", framesSinceBMC, hex(res))
        -- Read the gBattleResources struct to find buffer pointers
        if res and res >= 0x02000000 and res < 0x02040000 then
          local bResOff = res - 0x02000000
          local field0 = sr32(res)
          local field1 = sr32(res + 4)
          local field2 = sr32(res + 8)
          logf("  [DIAG] BattleResources: [0]=%s [1]=%s [2]=%s", hex(field0), hex(field1), hex(field2))
        end
        -- Read gBattlerSpriteIds and check sprite state
        local spriteIdBase = 0x020233EE  -- Found by scan
        local sid0 = sr8(spriteIdBase) or 255
        local sid1 = sr8(spriteIdBase + 1) or 255

        local gSpritesAddr = 0x02020630  -- Confirmed via ROM literal pool scan (1655 refs)
        local function readSpriteInfo(spriteId)
          local base = gSpritesAddr + spriteId * 0x44
          local flags = sr16(base + 0x3E) or 0
          local inUse = (flags & 1) ~= 0
          local invisible = (flags & 4) ~= 0
          local callback = sr32(base + 0x1C) or 0
          local x = sr16(base + 0x20) or 0
          local y = sr16(base + 0x22) or 0
          return inUse, invisible, callback, x, y
        end

        local iu0, inv0, cb0, x0, y0 = readSpriteInfo(sid0)
        local iu1, inv1, cb1, x1, y1 = readSpriteInfo(sid1)
        logf("  [DIAG] Sprite[%d]: inUse=%s invisible=%s cb=%s pos=%d,%d",
          sid0, tostring(iu0), tostring(inv0), hex(cb0), x0 or 0, y0 or 0)
        logf("  [DIAG] Sprite[%d]: inUse=%s invisible=%s cb=%s pos=%d,%d",
          sid1, tostring(iu1), tostring(inv1), hex(cb1), x1 or 0, y1 or 0)

        -- Also check sprite ID 2-5 for healthbox and other battle sprites
        for sid = 2, 7 do
          local iu, inv, cb, sx, sy = readSpriteInfo(sid)
          if iu then
            logf("  [DIAG] Sprite[%d]: inUse=%s invisible=%s cb=%s pos=%d,%d",
              sid, tostring(iu), tostring(inv), hex(cb), sx or 0, sy or 0)
          end
        end
      end
    end

    -- KEY SIMULATION v2: State-driven A-button pressing based on gBattleCommunication
    --
    -- gBattleCommunication[battler] tracks HTASS state per battler:
    --   0 = BEFORE_ACTION_CHOSEN (ChooseAction being emitted)
    --   1 = WAIT_ACTION_CHOSEN (controller waiting for Fight/Bag/Pokemon/Run input)
    --   2 = WAIT_ACTION_CASE_CHOSEN (processing action type)
    --   3 = WAIT_MOVE_CHOSEN (controller waiting for move selection input)
    --   4 = WAIT_ACTION_CONFIRMED_SET
    --   5 = CONFIRMED (done for this battler)
    --
    -- BattleMainCB2 uses if-else: either HTASS runs (ef==0) or controllers run (ef!=0).
    -- When comm[0]==1 and ef&0x01: player controller is showing Fight menu, press A to select.
    -- When comm[0]==3 and ef&0x01: player controller is showing Move menu, press A to select.
    -- When comm[0]>=4: player already confirmed, wait for turn execution.
    --
    -- GBA keys: 0=A, 1=B, 2=Select, 3=Start, 4=Right, 5=Left, 6=Up, 7=Down
    local KEY_A = 0

    if currentBmf == CFG.HandleTurnActionSelectionState then
      local ef = sr32(CFG.gBattleControllerExecFlags) or 0
      local comm0 = sr8(CFG.gBattleCommunication) or 0
      local comm1 = sr8(CFG.gBattleCommunication + 1) or 0
      local ctrl0 = sr32(CFG.gBattlerControllerFuncs) or 0

      -- FORCE PLAYER/OPPONENT ACTIONS: Always FIGHT with move slot 0
      -- The player controller auto-completes ChooseAction with action=1 (USE_ITEM)
      -- for unknown reasons. Force action=0 every frame ensures HTASS processes
      -- the FIGHT → ChooseMove path. Also prevents cafid=29 garbage in turn execution.
      sw8(CFG.gChosenActionByBattler, 0)      -- Player: B_ACTION_USE_MOVE = 0
      sw8(CFG.gChosenActionByBattler + 1, 0)  -- Opponent: B_ACTION_USE_MOVE = 0
      sw16(CFG.gChosenMoveByBattler, 0)       -- Player: first move slot
      sw16(CFG.gChosenMoveByBattler + 2, 0)   -- Opponent: first move slot
      -- Force gActionsByTurnOrder to valid values (prevents cafid out-of-range)
      sw8(0x020233F2, 0)  -- gActionsByTurnOrder[0] = USE_MOVE
      sw8(0x020233F3, 0)  -- gActionsByTurnOrder[1] = USE_MOVE
      sw8(0x020233F4, 0)  -- gActionsByTurnOrder[2] = USE_MOVE
      sw8(0x020233F5, 0)  -- gActionsByTurnOrder[3] = USE_MOVE

      if not mon.turnStartFrame then
        mon.turnStartFrame = framesSinceBMC
        mon.keyPhase = "idle"
        mon.keyHoldTimer = 0
        mon.keyTarget = nil
        mon.prevCommForKey = -1
        mon.turnInputAttempts = 0
        mon.idleTimer = 0
        mon.comm1StuckFrame = nil  -- Track how long comm[1] is stuck at 3
        -- Log HP at start of each turn
        local hp0 = sr16(BMON_BASE + 0x2A) or 0
        local hp1 = sr16(BMON_BASE + BMON_SIZE + 0x2A) or 0
        logf("  [TURN] Action selection started at f+%d (turn %d) HP: player=%d enemy=%d",
          framesSinceBMC, (mon.turnsInjected or 0) + 1, hp0, hp1)
        if mon.prevPlayerHP and hp0 ~= mon.prevPlayerHP then
          logf("  [TURN] Player HP changed: %d -> %d (dmg=%d)", mon.prevPlayerHP, hp0, mon.prevPlayerHP - hp0)
        end
        if mon.prevEnemyHP and hp1 ~= mon.prevEnemyHP then
          logf("  [TURN] Enemy HP changed: %d -> %d (dmg=%d)", mon.prevEnemyHP, hp1, mon.prevEnemyHP - hp1)
        end
        mon.prevPlayerHP = hp0
        mon.prevEnemyHP = hp1
        -- Diagnostic: gBattlerByTurnOrder, gBattleTypeFlags, gChosenActionByBattler
        local btbo0 = sr8(0x020233F6) or 255
        local btbo1 = sr8(0x020233F7) or 255
        local btfDiag = sr32(CFG.gBattleTypeFlags) or 0
        local act0d = sr8(CFG.gChosenActionByBattler) or 255
        local act1d = sr8(CFG.gChosenActionByBattler + 1) or 255
        logf("  [TURN] gBattlerByTurnOrder=[%d,%d] btf=%s act=[%d,%d]",
          btbo0, btbo1, hex(btfDiag), act0d, act1d)
        takeScreenshot(string.format("turn%d_start_f%04d", (mon.turnsInjected or 0) + 1, framesSinceBMC))
      end

      mon.keyHoldTimer = mon.keyHoldTimer + 1

      -- Log gBattleCommunication transitions
      if comm0 ~= mon.prevCommForKey then
        logf("  [INPUT] comm[0]: %d -> %d (ef=%s ctrl0=%s) at f+%d",
          mon.prevCommForKey or -1, comm0, hex(ef), hex(ctrl0), framesSinceBMC)
        mon.prevCommForKey = comm0
      end

      -- OPPONENT FORCE-ADVANCE: If comm[1] stuck at 3 with ef==0 for too long,
      -- manually complete the opponent's action selection.
      -- This is needed because the AI opponent controller may not respond properly
      -- to ChooseMove in our emulated link battle setup.
      if comm1 == 3 and ef == 0 then
        if not mon.comm1StuckFrame then
          mon.comm1StuckFrame = framesSinceBMC
        elseif framesSinceBMC - mon.comm1StuckFrame >= 60 then
          -- Stuck for 60+ frames: force-advance opponent to confirmed (state 5)
          -- Set opponent's action = FIGHT (0) and move = first move (slot 0)
          sw8(CFG.gChosenActionByBattler + 1, 0)    -- B_ACTION_USE_MOVE = 0
          sw16(CFG.gChosenMoveByBattler + 2, 0)     -- chosenMoveByBattler[1] = slot 0
          sw8(CFG.gBattleCommunication + 1, 5)       -- advance to CONFIRMED (state 5)
          logf("  [FIX] Force-advanced comm[1]: 3 -> 5 (stuck %d frames, set act=0 move=0)",
            framesSinceBMC - mon.comm1StuckFrame)
          mon.comm1StuckFrame = nil
          -- Take diagnostic screenshot
          takeScreenshot(string.format("opp_forced_f%04d", framesSinceBMC))
        end
      else
        mon.comm1StuckFrame = nil
      end

      -- State machine for key simulation
      if mon.keyPhase == "idle" then
        mon.idleTimer = (mon.idleTimer or 0) + 1

        if comm0 == 1 and (ef & 0x01) ~= 0 then
          -- Player controller waiting for action selection (Fight/Bag/Pokemon/Run)
          mon.keyPhase = "wait_render"
          mon.keyHoldTimer = 0
          mon.keyTarget = "fight"
          mon.idleTimer = 0
          logf("  [INPUT] Detected: waiting for Fight (comm0=1, ef=0x%02X) at f+%d", ef, framesSinceBMC)
        elseif comm0 == 3 and (ef & 0x01) ~= 0 then
          -- Player controller waiting for move selection
          mon.keyPhase = "wait_render"
          mon.keyHoldTimer = 0
          mon.keyTarget = "move"
          mon.idleTimer = 0
          logf("  [INPUT] Detected: waiting for Move (comm0=3, ef=0x%02X, ctrl0=%s) at f+%d",
            ef, hex(ctrl0), framesSinceBMC)
        elseif comm0 >= 4 then
          -- Player already confirmed, waiting for turn to start
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
          mon.idleTimer = 0
          logf("  [INPUT] Player confirmed (comm0=%d), waiting for turn at f+%d", comm0, framesSinceBMC)
        elseif mon.idleTimer > 120 then
          -- Stuck in idle — try pressing A aggressively
          logf("  [INPUT] Stuck idle %d frames (comm0=%d, ef=%s, ctrl0=%s), force pressing at f+%d",
            mon.idleTimer, comm0, hex(ef), hex(ctrl0), framesSinceBMC)
          mon.keyPhase = "force_press"
          mon.keyHoldTimer = 0
          mon.idleTimer = 0
        end

      elseif mon.keyPhase == "wait_render" then
        -- Wait 10 frames for menu UI to fully render
        if mon.keyHoldTimer >= 10 then
          mon.keyPhase = "pressing"
          mon.keyHoldTimer = 0
          emu:addKey(KEY_A)
          mon.turnInputAttempts = (mon.turnInputAttempts or 0) + 1
          logf("  [INPUT] Pressing A for %s (attempt %d) at f+%d",
            mon.keyTarget, mon.turnInputAttempts, framesSinceBMC)
        end

      elseif mon.keyPhase == "pressing" then
        -- Hold A for 4 frames
        if mon.keyHoldTimer >= 4 then
          emu:clearKey(KEY_A)
          takeScreenshot(string.format("%s_pressed_f%04d", mon.keyTarget or "key", framesSinceBMC))
          logf("  [INPUT] A released (%s) at f+%d (comm0=%d, ef=%s)",
            mon.keyTarget, framesSinceBMC, comm0, hex(ef))
          mon.keyPhase = "wait_response"
          mon.keyHoldTimer = 0
        end

      elseif mon.keyPhase == "wait_response" then
        -- Wait for comm[0] to change or a state transition
        -- After pressing A for Fight: comm[0] should go 1 → 2 (then 3 for ChooseMove)
        -- After pressing A for Move: comm[0] should go 3 → 4 → 5
        if comm0 >= 4 then
          -- Action confirmed
          logf("  [INPUT] Response: confirmed (comm0=%d) at f+%d", comm0, framesSinceBMC)
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
        elseif mon.keyHoldTimer > 90 then
          -- Timeout — input didn't cause state change, retry from idle
          logf("  [INPUT] Response timeout (comm0=%d, ef=%s, ctrl0=%s), retrying at f+%d",
            comm0, hex(ef), hex(ctrl0), framesSinceBMC)
          mon.keyPhase = "idle"
          mon.idleTimer = 0
          mon.keyHoldTimer = 0
        end

      elseif mon.keyPhase == "wait_turn" then
        -- Both battlers should reach state 5, then HTASS transitions to SetActionsAndBattlersTurnOrder
        -- bmf will change away from HandleTurnActionSelectionState
        if mon.keyHoldTimer > 300 then
          logf("  [INPUT] Turn start timeout (comm0=%d, comm1=%d, ef=%s) at f+%d",
            comm0, comm1, hex(ef), framesSinceBMC)
          mon.keyPhase = "force_press"
          mon.keyHoldTimer = 0
        end

      elseif mon.keyPhase == "force_press" then
        -- Aggressive: press A every 20 frames
        local cycle = mon.keyHoldTimer % 20
        if cycle <= 3 then
          emu:addKey(KEY_A)
        elseif cycle == 4 then
          emu:clearKey(KEY_A)
        end
        -- Check if state advanced
        if comm0 >= 4 and ef == 0 then
          emu:clearKey(KEY_A)
          mon.keyPhase = "wait_turn"
          mon.keyHoldTimer = 0
        end
        -- Exhaustion timeout
        if mon.keyHoldTimer > 600 then
          logf("  [INPUT] Force press exhausted at f+%d, back to idle", framesSinceBMC)
          emu:clearKey(KEY_A)
          mon.keyPhase = "idle"
          mon.idleTimer = 0
          mon.keyHoldTimer = 0
        end
      end

      -- Periodic state logging during action selection
      local turnFrame = framesSinceBMC - (mon.turnStartFrame or framesSinceBMC)
      if turnFrame % 30 == 0 then
        logf("  [HTASS] f+%d phase=%s target=%s timer=%d comm=%d/%d ef=%s ctrl0=%s attempts=%d",
          framesSinceBMC, mon.keyPhase or "nil", mon.keyTarget or "-", mon.keyHoldTimer,
          comm0, comm1, hex(ef), hex(ctrl0 & 0xFFFF), mon.turnInputAttempts or 0)
      end

    else
      -- Left HandleTurnActionSelectionState — turn is executing or something changed
      if mon.turnStartFrame then
        if mon.keyPhase ~= "idle" then
          mon.turnsInjected = (mon.turnsInjected or 0) + 1
          logf("  [TURN] Turn %d now executing (bmf=%s, phase was %s) at f+%d",
            mon.turnsInjected, hex(currentBmf), mon.keyPhase or "nil", framesSinceBMC)
          takeScreenshot(string.format("turn%d_exec_f%04d", mon.turnsInjected, framesSinceBMC))
        end
        -- Reset key state for next turn
        emu:clearKey(KEY_A)  -- Safety release
        mon.turnStartFrame = nil
        mon.keyPhase = nil
        mon.keyHoldTimer = 0
        mon.keyTarget = nil
        mon.prevCommForKey = nil
        mon.idleTimer = 0
      end
    end

    -- Also re-inject gBattleResources if cleared
    if mon.battleResPtr and sr32(CFG.gBattleResources) == 0 then
      sw32(CFG.gBattleResources, mon.battleResPtr)
    end

    -- Per-frame EXEC logging during turn execution
    if mon.bmfForceAdvanced then
      local RunTurnActionsFunctions = 0x0803E371
      local SetActionsAndBattlersTurnOrder = 0x0803D8F1
      local CheckChangingTurnOrderEffects = 0x0803E0ED
      local HandleEndTurn = 0x0803B96D
      local BattleTurnPassed = 0x0803BA25

      if currentBmf == RunTurnActionsFunctions or currentBmf == SetActionsAndBattlersTurnOrder
         or currentBmf == CheckChangingTurnOrderEffects or currentBmf == HandleEndTurn
         or currentBmf == BattleTurnPassed then
        -- MAINTAIN action/move values every frame during execution
        -- BattleTurnPassed writes 0xFF to gChosenActionByBattler → corrupts next turn
        -- Also maintain gActionsByTurnOrder to prevent cafid out-of-range
        sw8(CFG.gChosenActionByBattler, 0)      -- B_ACTION_USE_MOVE
        sw8(CFG.gChosenActionByBattler + 1, 0)
        sw16(CFG.gChosenMoveByBattler, 0)       -- First move slot
        sw16(CFG.gChosenMoveByBattler + 2, 0)
        sw8(0x020233F2, 0)  -- gActionsByTurnOrder[0]
        sw8(0x020233F3, 0)  -- gActionsByTurnOrder[1]
        sw8(0x020233F4, 0)
        sw8(0x020233F5, 0)
        -- Also force cafid to 0 if it's out-of-range (safety against sTurnActionsFuncsTable overflow)
        local cafidCheck = sr8(0x020233FB) or 0
        if cafidCheck > 12 then  -- sTurnActionsFuncsTable has ~13 valid entries (0-12)
          sw8(0x020233FB, 0)  -- gCurrentActionFuncId = 0 (ACTION_USE_MOVE)
        end

        local ef = sr32(CFG.gBattleControllerExecFlags)
        local ab = sr8(CFG.gActiveBattler)
        local ctan = sr8(0x020233FA)
        local cafid = sr8(0x020233FB)
        local outcome = sr8(CFG.gBattleOutcome)
        local bmonHP0 = sr16(BMON_BASE + 0x2A)
        local bmonHP1 = sr16(BMON_BASE + BMON_SIZE + 0x2A)
        local atbo0 = sr8(0x020233F2)
        local atbo1 = sr8(0x020233F3)
        local act0 = sr8(CFG.gChosenActionByBattler)
        local act1 = sr8(CFG.gChosenActionByBattler + 1)
        if not mon.turnExecLogCount then mon.turnExecLogCount = 0 end
        mon.turnExecLogCount = mon.turnExecLogCount + 1
        if mon.turnExecLogCount <= 30 or mon.turnExecLogCount % 5 == 0 then
          logf("  [EXEC] f+%d bmf=%s ef=%s ab=%d ctan=%d cafid=%d out=%d hp=%d/%d atbo=%d/%d act=%d/%d",
            framesSinceBMC, hex(currentBmf), hex(ef), ab or -1, ctan or -1, cafid or -1,
            outcome or -1, bmonHP0 or -1, bmonHP1 or -1, atbo0 or -1, atbo1 or -1, act0 or -1, act1 or -1)
        end
      else
        mon.turnExecLogCount = nil
      end

      -- Periodic status log
      if framesSinceBMC % 40 == 0 then
        local c0 = sr8(CFG.gBattleCommunication)
        local c1 = sr8(CFG.gBattleCommunication + 1)
        local ef = sr32(CFG.gBattleControllerExecFlags)
        local a0 = sr8(CFG.gChosenActionByBattler)
        local a1 = sr8(CFG.gChosenActionByBattler + 1)
        logf("  [STATUS] f+%d: bmf=%s comm=%d/%d ef=%s act=%d/%d turns=%d",
          framesSinceBMC, hex(currentBmf), c0 or -1, c1 or -1, hex(ef),
          a0 or -1, a1 or -1, mon.turnsInjected or 0)
      end
    end
  end

  -- Periodic log — more frequent during sprite load phase
  local shouldLog = false
  if f <= 400 then
    shouldLog = (f % 15 == 0)  -- Every 15 frames during sprite loading
  elseif f <= 800 then
    shouldLog = (f % 30 == 0)
  else
    shouldLog = (f % 60 == 0)
  end
  if shouldLog then
    local btf = sr32(CFG.gBattleTypeFlags)
    local bc = sr8(0x020233E4)
    local execF = sr32(CFG.gBattleControllerExecFlags)
    local pal0 = nil
    pcall(function() pal0 = emu.memory.palette:read16(0) end)
    local act0 = sr8(CFG.gChosenActionByBattler)
    local act1 = sr8(CFG.gChosenActionByBattler + 1)
    local comm1 = sr8(CFG.gBattleCommunication + 1)
    local ab = sr8(CFG.gActiveBattler)
    local bgPal2 = nil
    local objPal0 = nil
    pcall(function() bgPal2 = emu.memory.palette:read16(0x40) end)
    pcall(function() objPal0 = emu.memory.palette:read16(0x200) end)
    logf("  [f=%3d] cb2=%s inB=%s comm=%d/%d btf=%s bmf=%s bc=%s ef=%s pal=%s/%s/%s ab=%s act=%d/%d",
      f, labelCb2(cb2), tostring(inBattle), comm0 or -1, comm1 or -1, hex(btf), hex(bmf), tostring(bc), hex(execF),
      hex16(pal0), hex16(bgPal2), hex16(objPal0),
      tostring(ab), act0 or -1, act1 or -1)
  end

  -- Monitor battle outcome and HP
  if mon.bmfForceAdvanced and f % 60 == 0 then
    local outcome = sr8(CFG.gBattleOutcome)
    -- Read HP of both Pokemon from gPlayerParty and gEnemyParty
    local playerHP = sr16(CFG.gPlayerParty + CFG.HP_OFFSET)
    local enemyHP = sr16(CFG.gEnemyParty + CFG.HP_OFFSET)
    if outcome and outcome ~= 0 then
      logf("  [OUTCOME] f+%d: gBattleOutcome=%d (1=won,2=lost) playerHP=%d enemyHP=%d turns=%d",
        f - (mon.firstBattleCb2Frame or 0), outcome, playerHP or -1, enemyHP or -1, mon.turnsInjected or 0)
      takeScreenshot(string.format("battle_outcome_%d_f%04d", outcome, f))
    elseif f % 120 == 0 then
      logf("  [HP] f+%d: playerHP=%d enemyHP=%d turns=%d",
        f - (mon.firstBattleCb2Frame or 0), playerHP or -1, enemyHP or -1, mon.turnsInjected or 0)
    end
  end

  -- End?
  if f >= mon.maxFrames then
    return true  -- done
  end

  -- End early if battle outcome is determined
  if mon.bmfForceAdvanced then
    local outcome = sr8(CFG.gBattleOutcome)
    if outcome and outcome ~= 0 then
      -- Let the game process the outcome for 300 more frames (animations)
      if not mon.outcomeFrame then
        mon.outcomeFrame = f
        logf("  [END] Battle outcome %d detected at f=%d, waiting 300 frames for animations", outcome, f)
      elseif f - mon.outcomeFrame >= 300 then
        logf("  [END] Battle ended with outcome %d after %d turns", outcome, mon.turnsInjected or 0)
        takeScreenshot("battle_ended")
        return true
      end
    end
  end

  -- End early if battle running 6000+ frames after BattleMainCB2
  -- Increased from 3600: key simulation needs ~500 frames/turn, up to 5+ turns
  if mon.battleMainReached and f >= mon.firstBattleCb2Frame + 6000 then
    log("Battle running for 6000 frames after BattleMainCB2 — ending")
    takeScreenshot("battle_running_final")
    return true
  end

  return false
end

-- ============================================================
-- Finish: restore and write results
-- ============================================================
local function finish()
  -- Safety: release all simulated keys
  pcall(function() emu:clearKey(0) end)
  pcall(function() emu:clearKey(1) end)

  log("=== RESULTS ===")
  logf("Transitions: %d", #mon.transitions)

  log("--- CB2 History ---")
  for val, f in pairs(mon.cb2History) do
    logf("  %s at frame %d", labelCb2(val), f)
  end

  log("--- All Transitions ---")
  for _, t in ipairs(mon.transitions) do
    logf("  %s", t)
  end

  if mon.battleMainReached then
    logf("RESULT: SUCCESS — BattleMainCB2 at frame %d", mon.firstBattleCb2Frame or -1)
    logf("  Turns injected: %d", mon.turnsInjected or 0)
    local outcome = sr8(CFG.gBattleOutcome)
    logf("  Final gBattleOutcome: %d (0=ongoing,1=won,2=lost)", outcome or -1)
    local playerHP = sr16(CFG.gPlayerParty + CFG.HP_OFFSET)
    local enemyHP = sr16(CFG.gEnemyParty + CFG.HP_OFFSET)
    logf("  Final HP: player=%d enemy=%d", playerHP or -1, enemyHP or -1)
  elseif mon.inBattleTriggered then
    log("RESULT: PARTIAL — inBattle=1 but no BattleMainCB2")
  else
    log("RESULT: FAILED — Battle did not start")
  end

  -- Final state
  logf("Final: cb2=%s inB=%s comm0=%s",
    labelCb2(sr32(CFG.callback2Addr)),
    tostring(sr8(CFG.gMainInBattle)),
    tostring(sr8(CFG.gBattleCommunication)))

  -- Restore ROM
  log("--- Restoring ROM patches ---")
  for _, p in ipairs(originals.rom) do
    if p.sz == 2 then wr16(p.off, p.val) else wr32(p.off, p.val) end
  end
  logf("Restored %d ROM patches", #originals.rom)

  takeScreenshot("battle_init_final")
  writeResults()
end

-- ============================================================
-- Main frame handler (state machine)
-- ============================================================

local function onFrame()
  frameCount = frameCount + 1

  if phase == "init" then
    -- Connect to result listener on first frame
    if frameCount == 1 then
      connectResultSocket()
    end
    -- Wait 60 frames for mGBA to stabilize
    if frameCount >= 60 then
      log("Loading save state slot 1...")
      pcall(function() emu:loadStateSlot(1) end)
      phase = "waitload"
      phaseFrame = frameCount
    end

  elseif phase == "waitload" then
    -- Wait 120 frames for save state to fully load
    if frameCount - phaseFrame >= 120 then
      log("Save state loaded. Checking state...")
      local cb2 = sr32(CFG.callback2Addr)
      local rawIB = sr8(CFG.gMainInBattle)
      -- inBattle is bit 1 of the bitfield byte (bit 0 = oamLoadDisabled)
      local inBattle = rawIB and (((rawIB & 0x02) ~= 0) and 1 or 0) or nil
      local pc = sr8(CFG.gPlayerPartyCount)
      logf("callback2=%s rawInBattle=0x%02X inBattle=%s partyCount=%s",
        hex(cb2), rawIB or 0, tostring(inBattle), tostring(pc))

      if not pc or pc == 0 or pc > 6 then
        log("FAIL: No valid party after save state load. Is slot 1 an overworld state?")
        phase = "done"
        writeResults()
        return
      end

      if inBattle and inBattle ~= 0 then
        log("WARN: inBattle=1 after save state load — may be in battle transition. Proceeding anyway...")
        -- Don't abort — the save state might just have the flag set during a non-battle state
        -- The battle test will set everything up from scratch
      end

      phase = "battle"
      phaseFrame = frameCount
    end

  elseif phase == "battle" then
    -- One-shot: set up and trigger battle
    local ok = doBattleSetup()
    if ok then
      mon.prevCb2 = CFG.CB2_InitBattle
      mon.prevInBattle = 0
      mon.prevComm0 = 0
      mon.cb2History = { [CFG.CB2_InitBattle] = 0 }
      phase = "monitoring"
      phaseFrame = frameCount
    else
      log("Battle setup failed")
      phase = "done"
      writeResults()
    end

  elseif phase == "monitoring" then
    local done = monitorFrame()
    if done then
      phase = "done"
      finish()
    end

  end
  -- phase == "done": do nothing
end

-- Register
callbacks:add("frame", onFrame)
console:log("[RunTest] Frame callback registered. Waiting for stabilization...")
