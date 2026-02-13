--[[
  Battle Module — GBA-PK Buffer Relay Approach

  Approach: Keep BATTLE_TYPE_LINK active throughout the battle. Instead of clearing
  LINK and swapping to AI controllers, relay gBattleBufferA/B between players via TCP.
  The ROM's link battle engine handles sprites, animations, turn order natively.

  Init chain: CB2_InitBattle → CB2_InitBattleInternal → CB2_HandleStartBattle → BattleMainCB2

  IS_MASTER: Only master gets BATTLE_TYPE_IS_MASTER (like real link cable).
  CLIENT follows slave path in InitBtlControllersInternal (reversed positions/controllers).
  gBattleMainFunc = BeginBattleIntro is written by Lua on CLIENT (slave path only sets dummy).

  Slot mapping (asymmetric):
    Master (GetMultiplayerId=0): battler 0 = Player, battler 1 = LinkOpponent
    Slave  (GetMultiplayerId=1): battler 0 = LinkOpponent, battler 1 = Player

  Buffer relay (MAIN_LOOP) — GBA-PK Stage 7:
    Host reads gBattleControllerExecFlags[1-4] each frame.
    When a battler's high-nibble bit is set (PLAYERS2), that battler needs network service.
    Host reads bufferA/B from memory, sends to client via TCP.
    Client writes received bufferA/B to memory, acknowledges.
    Exec flags manage synchronization: bits 0-3 active, bits 4-7 network.
    Battle end: bufferA command ID 0x37 = GetAwayExit.

  Flow:
  1. Exchange party data via network
  2. Inject opponent's party into gEnemyParty
  3. Apply ROM/EWRAM patches to fake link hardware
  4. Set gBattleTypeFlags, gMain.savedCallback, callback2 = CB2_InitBattle
  5. Game runs full initialization chain (11 link sync cases, VS screen)
  6. At BattleMainCB2: transition to MAIN_LOOP (LINK stays active!)
  7. Engine pacing via GetBlockReceivedStatus: return 0 to block, 0x0F to unblock
  8. Action sync: read gChosenAction/Move locally, relay via TCP, inject remote choice
  9. Battle ends naturally → gMain.savedCallback returns to overworld
  10. Restore ROM patches, return to origin
]]

local Battle = {}

-- Configuration (loaded from game config)
local config = nil
local ADDRESSES = nil
local LINK = nil  -- battle_link section
local HAL = nil

-- Battle type flags (from config.battleFlags, with fallbacks)
local BATTLE_TYPE_LINK = 0x00000002
local BATTLE_TYPE_IS_MASTER = 0x00000004
local BATTLE_TYPE_TRAINER = 0x00000008
local BATTLE_TYPE_LINK_IN_BATTLE = 0x00000020  -- Bit 5: auto-set by engine when LINK starts
local BATTLE_TYPE_RECORDED = 0x01000000  -- Bit 24: needed for BattleMainCB2 transition gate

-- Party structure constants
local PARTY_SIZE = 600
local POKEMON_SIZE = 100
local POKEMON_HP_OFFSET = 86

-- Buffer relay constants (GBA-PK reads 256 bytes for both bufA and bufB per battler)
local BUFFER_READ_SIZE = 256    -- bytes to read/relay from bufferA/B per battler
local BATTLER_BUFFER_STRIDE = 0x200  -- 512 bytes per battler slot

-- Exec flag constants (from GBA-PK)
local FLAGS_SENDING   = 1
local FLAGS_WRITTEN   = 2
local FLAGS_ACTIVATED = 4
local FLAGS_FINISHED  = 8
local FLAGS_UPDATE_PKMN = 64
local PLAYERS  = { [1]=0x01, [2]=0x02, [3]=0x04, [4]=0x08 } -- bits 0-3: exec active
local PLAYERS2 = { [1]=0x10, [2]=0x20, [3]=0x40, [4]=0x80 } -- bits 4-7: network wait

-- Battle end command ID
local CMD_GET_AWAY_EXIT = 0x37

-- Battle outcome flags
local B_OUTCOME_LINK_BATTLE_RAN = 0x80  -- OR'd into gBattleOutcome when Run is used in link battle

-- Helper: convert absolute EWRAM address to WRAM offset
local function toWRAMOffset(address)
  return address - 0x02000000
end

-- Helper: convert absolute IWRAM address to IWRAM offset
local function toIWRAMOffset(address)
  return address - 0x03000000
end

-- Helper: check if an address is in IWRAM range
local function isIWRAM(address)
  return address >= 0x03000000 and address < 0x03008000
end

-- Helper: read from the correct memory domain
local function readMem8(address)
  if isIWRAM(address) then
    return emu.memory.iwram:read8(toIWRAMOffset(address))
  else
    return emu.memory.wram:read8(toWRAMOffset(address))
  end
end

local function readMem16(address)
  if isIWRAM(address) then
    return emu.memory.iwram:read16(toIWRAMOffset(address))
  else
    return emu.memory.wram:read16(toWRAMOffset(address))
  end
end

local function readMem32(address)
  if isIWRAM(address) then
    return emu.memory.iwram:read32(toIWRAMOffset(address))
  else
    return emu.memory.wram:read32(toWRAMOffset(address))
  end
end

local function writeMem8(address, value)
  if isIWRAM(address) then
    emu.memory.iwram:write8(toIWRAMOffset(address), value)
  else
    emu.memory.wram:write8(toWRAMOffset(address), value)
  end
end

local function writeMem16(address, value)
  if isIWRAM(address) then
    emu.memory.iwram:write16(toIWRAMOffset(address), value)
  else
    emu.memory.wram:write16(toWRAMOffset(address), value)
  end
end

local function writeMem32(address, value)
  if isIWRAM(address) then
    emu.memory.iwram:write32(toIWRAMOffset(address), value)
  else
    emu.memory.wram:write32(toWRAMOffset(address), value)
  end
end

-- Forward declarations (defined after startLinkBattle, called from within it)
local initLocalLinkPlayer

-- ============================================================
-- State Machine
-- ============================================================

local STAGE = {
  IDLE           = 0,
  STARTING       = 3,   -- callback2 = CB2_InitBattle, waiting for battle engine to start
  MAIN_LOOP      = 5,   -- Battle running, relay buffers (GBA-PK Stage 7)
  ENDING         = 6,   -- Battle ending, wait then cleanup
  RESTORING      = 7,   -- Restoring patches
  DONE           = 8,   -- Battle complete
}

local state = {
  stage = STAGE.IDLE,
  frameCounter = 0,
  isMaster = false,
  opponentParty = nil,
  prevInBattle = 0,
  battleDetected = false,
  battleCallbackSeen = false,
  stageTimer = 0,
  stageClock = 0,           -- os.clock() at stage entry (real-time, speedhack-safe)
  remoteBuffers = {},
  romPatches = {},
  ewramPatches = {},
  battleFlags = nil,
  isLinkBattle = false,
  remoteReady = false,
  sendFn = nil,
  savedCallback1 = nil,  -- save callback1 before battle to restore after
  localPartyBackup = nil,     -- backup of gPlayerParty BEFORE battle init (Cases 4/6 overwrite it!)
  battleEntryMethod = "direct_write",  -- "loadscript37", "direct_write", or "direct_fallback"
  battleMainReached = false,  -- BattleMainCB2 callback detected
  cachedOutcome = nil,        -- Outcome cached at detection time (before DMA corruption)
  forceEndPending = false,
  forceEndFrame = 0,

  -- GBA-PK Buffer Relay state
  relay = {
    -- Slot mapping (0-indexed for memory, 1-indexed for PLAYERS/PLAYERS2)
    localSlot = 0,       -- master=0, slave=1 (0-indexed)
    remoteSlot = 1,      -- master=1, slave=0 (0-indexed)
    localBattler = 1,    -- master=1, slave=2 (1-indexed for PLAYERS arrays)
    remoteBattler = 2,   -- master=2, slave=1 (1-indexed for PLAYERS arrays)

    -- GBA-PK protocol state (mirrors playerBattle.Waiting_Status bitmask)
    waitingStatus = 0,
    bufferID = 0,        -- which battler we're servicing (1-indexed, 0 = none)
    sendID = 0,          -- bitmask of battler slots we've sent

    -- Remote player's GBA-PK state (mirrors otherplayerBattle)
    remoteWaitingStatus = 0,
    remoteBufferID = 0,
    remoteSendID = 0,
    remoteBattleflags = { 0, 0, 0, 0 },
    remoteTransferStage = 0,

    -- Remote buffer data (received via TCP)
    remoteBufferA = nil,   -- array of bytes
    remoteBufferB = nil,   -- array of bytes
    remoteAttacker = 0,
    remoteTarget = 0,
    remoteAbsent = 0,
    remoteEffect = 0,

    -- Has remote sent us any data yet?
    remoteDataReceived = false,

    -- Comm advancement (stages 5-6 in GBA-PK)
    commAdvanced = false,
    commReady = false,

    -- Action sync state (GBA-PK buffer relay approach)
    localReady = false,
    remoteReady = false,
    remoteAction = nil,      -- {action=N, move=M} or nil
    localAction = nil,       -- {action=N, move=M} or nil
    lastTurn = -1,
    introComplete = false,
    remoteMainloopReady = false,  -- true when remote player enters MAIN_LOOP (GBA-PK readiness)
    engineBlocked = true,    -- GetBlockReceivedStatus returns 0 when true
    turnPhase = "idle",      -- "idle" | "selecting" | "waiting_remote" | "executing"
    lastComm0 = 0,           -- previous gBattleCommunication[0] for turn boundary detection
    savedBattleStruct = nil,    -- cached pointer for protection
    savedBattleResources = nil, -- cached pointer for protection
    lastRelayActivityFrame = 0,
  },
}

local debugOptions = {
  log = false,
  screenshot = false,
  telemetry = false,
  screenshotCooldownFrames = 300,
  screenshotMaxPerSession = 8,
}

local screenshotState = {
  count = 0,
  lastFrame = -999999,
}

local function toBoolean(value, fallback)
  if value == nil then return fallback end
  return value == true
end

local function toPositiveInt(value, fallback)
  local n = tonumber(value)
  if not n then return fallback end
  n = math.floor(n)
  if n < 0 then n = 0 end
  return n
end

local function shouldCaptureScreenshot()
  if not debugOptions.screenshot then
    return false
  end

  local maxPerSession = debugOptions.screenshotMaxPerSession or 0
  if maxPerSession > 0 and screenshotState.count >= maxPerSession then
    return false
  end

  local cooldown = debugOptions.screenshotCooldownFrames or 0
  if cooldown > 0 then
    local frameNow = tonumber(state.frameCounter) or 0
    if (frameNow - (screenshotState.lastFrame or -999999)) < cooldown then
      return false
    end
    screenshotState.lastFrame = frameNow
  end

  screenshotState.count = screenshotState.count + 1
  return true
end

local function captureScreenshot(path)
  if not path or not shouldCaptureScreenshot() then
    return false
  end
  pcall(function()
    emu:screenshot(path)
  end)
  return true
end

function Battle.setDebugOptions(options)
  local opts = options or {}
  debugOptions.log = toBoolean(opts.log, debugOptions.log)
  debugOptions.screenshot = toBoolean(opts.screenshot, debugOptions.screenshot)
  debugOptions.telemetry = toBoolean(opts.telemetry, debugOptions.telemetry)
  debugOptions.screenshotCooldownFrames = toPositiveInt(opts.screenshotCooldownFrames, debugOptions.screenshotCooldownFrames)
  debugOptions.screenshotMaxPerSession = toPositiveInt(opts.screenshotMaxPerSession, debugOptions.screenshotMaxPerSession)
end

-- ============================================================
-- Initialization
-- ============================================================

function Battle.init(gameConfig, halModule)
  config = gameConfig
  HAL = halModule
  if config and config.battle then
    ADDRESSES = config.battle
    LINK = config.battle_link or {}

    if config.pokemon then
      PARTY_SIZE = config.pokemon.FULL_PARTY_BYTES or PARTY_SIZE
      POKEMON_SIZE = config.pokemon.PARTY_MON_SIZE or POKEMON_SIZE
      POKEMON_HP_OFFSET = config.pokemon.HP_OFFSET or POKEMON_HP_OFFSET
    end
    if LINK and LINK.battlerBufferSize then
      BATTLER_BUFFER_STRIDE = LINK.battlerBufferSize
    end
    if config.battleFlags then
      BATTLE_TYPE_LINK = config.battleFlags.LINK or BATTLE_TYPE_LINK
      BATTLE_TYPE_LINK_IN_BATTLE = config.battleFlags.LINK_IN_BATTLE or BATTLE_TYPE_LINK_IN_BATTLE
      BATTLE_TYPE_IS_MASTER = config.battleFlags.IS_MASTER or BATTLE_TYPE_IS_MASTER
      BATTLE_TYPE_TRAINER = config.battleFlags.TRAINER or BATTLE_TYPE_TRAINER
      BATTLE_TYPE_RECORDED = config.battleFlags.RECORDED or BATTLE_TYPE_RECORDED
    end
    if config.debug and config.debug.battle then
      Battle.setDebugOptions(config.debug.battle)
    end

    console:log("[Battle] Initialized (GBA-PK buffer relay mode)")
    console:log(string.format("[Battle] gPlayerParty=0x%08X gEnemyParty=0x%08X",
      ADDRESSES.gPlayerParty or 0, ADDRESSES.gEnemyParty or 0))

    if LINK and LINK.CB2_InitBattle then
      console:log(string.format("[Battle] CB2_InitBattle=0x%08X", LINK.CB2_InitBattle))
    else
      console:log("[Battle] WARNING: CB2_InitBattle not configured -- run find_cb2_initbattle.lua")
    end

    -- Clean up stale ROM patches from previous sessions
    Battle.cleanupStalePatches()
  else
    console:log("[Battle] WARNING: No battle config available")
  end
end

function Battle.setSendFn(fn)
  state.sendFn = fn
end

function Battle.isConfigured()
  return ADDRESSES ~= nil
    and ADDRESSES.gPlayerParty ~= nil
    and ADDRESSES.gEnemyParty ~= nil
    and ADDRESSES.gBattleTypeFlags ~= nil
end

function Battle.isLinkConfigured()
  return LINK ~= nil and LINK.GetMultiplayerId ~= nil
end

-- ============================================================
-- Stale Patch Cleanup
-- ============================================================

function Battle.cleanupStalePatches()
  if not LINK or not LINK.patches then return end
  local cleaned = 0

  local patchRestore = {
    { name = "playerBufExecSkip",       patchVal = 0xE01C, origVal = 0xD01C, sz = 2 },
    { name = "linkOpponentBufExecSkip", patchVal = 0xE01C, origVal = 0xD01C, sz = 2 },
    { name = "prepBufDataTransferLocal",  patchVal = 0xE008, origVal = 0xD008, sz = 2 },
    { name = "isLinkTaskFinished",      patchVal = 0x47702001, origVal = nil, sz = 4 },
    { name = "getBlockReceivedStatus",  patchVal = 0x4770200F, origVal = nil, sz = 4 },
    -- markBattlerExecLocal, isBattlerExecLocal, markAllBattlersExecLocal:
    -- REMOVED from active patches (GBA-PK uses bits 28-31 for link exec).
    -- Still clean up stale patches from previous sessions:
    { name = "markBattlerExecLocal",    patchVal = 0xE010, origVal = 0xD010, sz = 2, romOffset = 0x040F50 },
    { name = "isBattlerExecLocal",      patchVal = 0xE00E, origVal = 0xD00E, sz = 2, romOffset = 0x040EFC },
    { name = "markAllBattlersExecLocal", patchVal = 0xE018, origVal = 0xD018, sz = 2, romOffset = 0x040E88 },
    { name = "initBtlControllersBeginIntro", patchVal = 0x46C0, origVal = 0xD01D, sz = 2, romOffset = 0x032ACE },
    -- OLD WRONG patches (targeted PlayerBufferExecCompleted instead of HandleLinkBattleSetup):
    { name = "nopHandleLinkBattleSetup_hi", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x06F420 },
    { name = "nopHandleLinkBattleSetup_lo", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x06F422 },
    -- CORRECT HandleLinkBattleSetup NOP patches (restore on cleanup):
    { name = "nopHandleLinkSetup_SetUpBV_hi", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x032494 },
    { name = "nopHandleLinkSetup_SetUpBV_lo", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x032496 },
    { name = "nopHandleLinkSetup_CB2Init_hi", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x036456 },
    { name = "nopHandleLinkSetup_CB2Init_lo", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x036458 },
    -- TryReceiveLinkBattleData NOP in VBlankIntrHandler:
    { name = "nopTryRecvLinkBattleData_hi", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x0007BC },
    { name = "nopTryRecvLinkBattleData_lo", patchVal = 0x46C0, origVal = nil, sz = 2, romOffset = 0x0007BE },
  }

  for _, pr in ipairs(patchRestore) do
    local patch = LINK.patches and LINK.patches[pr.name]
    local offset = (patch and patch.romOffset) or pr.romOffset
    if offset then
      if pr.sz == 2 then
        local ok, cur = pcall(function() return emu.memory.cart0:read16(offset) end)
        if ok and cur == pr.patchVal and pr.origVal then
          pcall(function() emu.memory.cart0:write16(offset, pr.origVal) end)
          cleaned = cleaned + 1
        end
      elseif pr.sz == 4 then
        local ok, cur = pcall(function() return emu.memory.cart0:read32(offset) end)
        if ok and cur == pr.patchVal then
          console:log(string.format("[Battle] WARNING: %s still patched (restart mGBA)", pr.name))
        end
      end
    end
  end

  if LINK.GetMultiplayerId then
    local gmidOff = (LINK.GetMultiplayerId & 0xFFFFFFFE) - 0x08000000
    local ok, instr = pcall(function() return emu.memory.cart0:read16(gmidOff) end)
    if ok and (instr == 0x2000 or instr == 0x2001) then
      console:log("[Battle] WARNING: GetMultiplayerId still patched -- restart mGBA for clean ROM")
    end
  end

  if cleaned > 0 then
    console:log(string.format("[Battle] Cleaned %d stale ROM patches", cleaned))
  end
end

-- ============================================================
-- Party Read/Write
-- ============================================================

function Battle.readLocalParty()
  if not ADDRESSES or not ADDRESSES.gPlayerParty then return nil end

  local data = {}
  local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)

  local ok = pcall(function()
    for i = 0, PARTY_SIZE - 1 do
      data[i + 1] = emu.memory.wram:read8(baseOffset + i)
    end
  end)

  if ok and #data == PARTY_SIZE then return data end
  return nil
end

function Battle.injectEnemyParty(partyData, isMasterParam)
  if not ADDRESSES or not ADDRESSES.gEnemyParty then return false end
  if not partyData or #partyData ~= PARTY_SIZE then return false end

  local effectiveIsMaster = state.isMaster
  if isMasterParam ~= nil then effectiveIsMaster = isMasterParam end

  local baseOffset = toWRAMOffset(ADDRESSES.gEnemyParty)

  local ok = pcall(function()
    for i = 1, PARTY_SIZE do
      emu.memory.wram:write8(baseOffset + i - 1, partyData[i])
    end
  end)

  if ok then
    -- Count non-empty party members (personality != 0 = valid Pokemon)
    local count = 0
    local healthFlags = 0
    for i = 0, 5 do
      local off = i * POKEMON_SIZE
      local p = partyData[off + 1] + partyData[off + 2] * 256
                + partyData[off + 3] * 65536 + partyData[off + 4] * 16777216
      if p ~= 0 then
        count = count + 1
        local hp = partyData[off + POKEMON_HP_OFFSET + 1] + partyData[off + POKEMON_HP_OFFSET + 2] * 256
        if hp > 0 then
          healthFlags = healthFlags | (1 << (i * 2))
        else
          healthFlags = healthFlags | (3 << (i * 2))
        end
      end
    end

    -- Set gEnemyPartyCount
    if ADDRESSES.gEnemyPartyCount then
      pcall(writeMem8, ADDRESSES.gEnemyPartyCount, count)
    end

    -- Write party to gBlockRecvBuffer for CB2_HandleStartBattle's memcpy
    if LINK and LINK.gBlockRecvBuffer then
      local enemySlot = effectiveIsMaster and 1 or 0
      local stride = LINK.gBlockRecvBufferStride or 0x100
      local bufAddr = LINK.gBlockRecvBuffer + enemySlot * stride
      local bufOff = toWRAMOffset(bufAddr)
      pcall(function()
        emu.memory.wram:write8(bufOff + 0, 0x00)                    -- versionSignatureLo = 0
        emu.memory.wram:write8(bufOff + 1, 0x03)                    -- versionSignatureHi = 3 (Emerald)
        emu.memory.wram:write8(bufOff + 2, healthFlags & 0xFF)      -- vsScreenHealthFlagsLo
        emu.memory.wram:write8(bufOff + 3, (healthFlags >> 8) & 0xFF)  -- vsScreenHealthFlagsHi
        for i = 1, math.min(PARTY_SIZE, 252) do
          emu.memory.wram:write8(bufOff + 4 + i - 1, partyData[i])
        end
      end)
    end

    -- Write local player's health flags to own gBlockRecvBuffer slot (for VS screen pokeballs)
    if LINK and LINK.gBlockRecvBuffer and ADDRESSES.gPlayerParty then
      local localStride = LINK.gBlockRecvBufferStride or 0x100
      local localSlot = effectiveIsMaster and 0 or 1
      local localBufOff = toWRAMOffset(LINK.gBlockRecvBuffer + localSlot * localStride)
      local localHealthFlags = 0
      pcall(function()
        for i = 0, 5 do
          local pOff = toWRAMOffset(ADDRESSES.gPlayerParty) + i * POKEMON_SIZE
          local p = emu.memory.wram:read32(pOff)
          if p ~= 0 then
            local hp = emu.memory.wram:read16(pOff + POKEMON_HP_OFFSET)
            if hp > 0 then
              localHealthFlags = localHealthFlags | (1 << (i * 2))
            else
              localHealthFlags = localHealthFlags | (3 << (i * 2))
            end
          end
        end
        emu.memory.wram:write8(localBufOff + 0, 0x00)                          -- versionSignatureLo = 0
        emu.memory.wram:write8(localBufOff + 1, 0x03)                          -- versionSignatureHi = 3 (Emerald)
        emu.memory.wram:write8(localBufOff + 2, localHealthFlags & 0xFF)       -- vsScreenHealthFlagsLo
        emu.memory.wram:write8(localBufOff + 3, (localHealthFlags >> 8) & 0xFF) -- vsScreenHealthFlagsHi
      end)
    end

    -- Set up gLinkPlayers entries for link battle identification
    if LINK and LINK.gLinkPlayers then
      local lpOff = toWRAMOffset(LINK.gLinkPlayers)
      pcall(function()
        -- Player 0 (master)
        emu.memory.wram:write16(lpOff + 0x00, 3)          -- version = Emerald
        emu.memory.wram:write8(lpOff + 0x13, 0)           -- gender = male
        emu.memory.wram:write32(lpOff + 0x14, 0x2233)     -- linkType = SINGLE_BATTLE
        emu.memory.wram:write16(lpOff + 0x18, 0)          -- id = 0
        emu.memory.wram:write16(lpOff + 0x1A, 2)          -- language = English
        -- Player 1 (slave)
        local p1 = lpOff + 0x1C
        emu.memory.wram:write16(p1 + 0x00, 3)             -- version = Emerald
        emu.memory.wram:write8(p1 + 0x13, 0)              -- gender = male
        emu.memory.wram:write32(p1 + 0x14, 0x2233)        -- linkType = SINGLE_BATTLE
        emu.memory.wram:write16(p1 + 0x18, 1)             -- id = 1
        emu.memory.wram:write16(p1 + 0x1A, 2)             -- language = English
      end)
    end

    console:log(string.format("[Battle] Enemy party injected (600 bytes, %d Pokemon, healthFlags=0x%04X)", count, healthFlags))
    state.opponentParty = partyData
    return true
  end
  return false
end

-- ============================================================
-- ROM Patching
-- ============================================================

local function applyRAMPatch(addr, value, size)
  local original, ok
  if size == 1 then
    ok, original = pcall(readMem8, addr)
    if ok then pcall(writeMem8, addr, value) end
  elseif size == 2 then
    ok, original = pcall(readMem16, addr)
    if ok then pcall(writeMem16, addr, value) end
  elseif size == 4 then
    ok, original = pcall(readMem32, addr)
    if ok then pcall(writeMem32, addr, value) end
  end
  if ok then
    table.insert(state.ewramPatches, { addr = addr, size = size, original = original })
    return true
  end
  return false
end

local function applyROMPatch(romOffset, value, size)
  local original, okRead, okWrite
  if size == 2 then
    okRead, original = pcall(emu.memory.cart0.read16, emu.memory.cart0, romOffset)
    if okRead then okWrite = pcall(emu.memory.cart0.write16, emu.memory.cart0, romOffset, value) end
  elseif size == 4 then
    okRead, original = pcall(emu.memory.cart0.read32, emu.memory.cart0, romOffset)
    if okRead then okWrite = pcall(emu.memory.cart0.write32, emu.memory.cart0, romOffset, value) end
  end

  if okRead and okWrite then
    local okV, rb
    if size == 2 then
      okV, rb = pcall(emu.memory.cart0.read16, emu.memory.cart0, romOffset)
    else
      okV, rb = pcall(emu.memory.cart0.read32, emu.memory.cart0, romOffset)
    end
    if okV and rb == value then
      table.insert(state.romPatches, { romOffset = romOffset, size = size, original = original })
      return true
    end
  end
  return false
end

function Battle.applyPatches(isMaster)
  state.romPatches = {}
  state.ewramPatches = {}
  local patchCount = 0
  local romPatchWorks = false

  -- RAM patches: gWirelessCommType = 0, gReceivedRemoteLinkPlayers = 1
  if LINK and LINK.gWirelessCommType then
    if applyRAMPatch(LINK.gWirelessCommType, 0, 1) then patchCount = patchCount + 1 end
  end
  if LINK and LINK.gReceivedRemoteLinkPlayers then
    if applyRAMPatch(LINK.gReceivedRemoteLinkPlayers, 1, 1) then patchCount = patchCount + 1 end
  end

  -- ROM patch: GetMultiplayerId -> MOV R0,#n; BX LR
  if LINK and LINK.GetMultiplayerId then
    local romOff = (LINK.GetMultiplayerId & 0xFFFFFFFE) - 0x08000000
    local movValue = isMaster and 0x2000 or 0x2001
    if applyROMPatch(romOff, movValue, 2) then
      romPatchWorks = true
      patchCount = patchCount + 1
      if applyROMPatch(romOff + 2, 0x4770, 2) then patchCount = patchCount + 1 end
      console:log(string.format("[Battle] Patched GetMultiplayerId: MOV R0,#%d; BX LR", isMaster and 0 or 1))
    end
  end

  -- Additional ROM patches (BEQ->B skips, NOP patches)
  if romPatchWorks and LINK and LINK.patches then
    for name, patch in pairs(LINK.patches) do
      if patch.romOffset and patch.value and patch.size then
        if applyROMPatch(patch.romOffset, patch.value, patch.size) then
          patchCount = patchCount + 1
          console:log(string.format("[Battle] Applied ROM patch: %s", name))
        end
      end
    end
  end

  console:log(string.format("[Battle] Applied %d patches (%d ROM, %d RAM)",
    patchCount, #state.romPatches, #state.ewramPatches))
  return patchCount > 0
end

function Battle.restorePatches()
  local restored = 0

  for _, patch in ipairs(state.romPatches) do
    local ok
    if patch.size == 2 then
      ok = pcall(emu.memory.cart0.write16, emu.memory.cart0, patch.romOffset, patch.original)
    elseif patch.size == 4 then
      ok = pcall(emu.memory.cart0.write32, emu.memory.cart0, patch.romOffset, patch.original)
    end
    if ok then restored = restored + 1 end
  end

  for _, patch in ipairs(state.ewramPatches) do
    local ok
    if patch.size == 1 then ok = pcall(writeMem8, patch.addr, patch.original)
    elseif patch.size == 2 then ok = pcall(writeMem16, patch.addr, patch.original)
    elseif patch.size == 4 then ok = pcall(writeMem32, patch.addr, patch.original)
    end
    if ok then restored = restored + 1 end
  end

  console:log(string.format("[Battle] Restored %d/%d patches",
    restored, #state.romPatches + #state.ewramPatches))
  state.romPatches = {}
  state.ewramPatches = {}
end

-- ============================================================
-- Battle Setup
-- ============================================================

function Battle.startLinkBattle(isMaster)
  if not Battle.isConfigured() then
    console:log("[Battle] ERROR: not configured")
    return false
  end

  if not config or not config.warp then
    console:log("[Battle] ERROR: no warp config")
    return false
  end

  state.isMaster = isMaster
  state.prevInBattle = 0
  state.battleDetected = false
  state.battleCallbackSeen = false
  state.stageTimer = 0
  state.remoteBuffers = {}
  state.remoteReady = false

  -- Set up buffer relay slot mapping (GBA-PK: 1-indexed battler IDs)
  state.relay.localSlot = isMaster and 0 or 1     -- 0-indexed for memory addressing
  state.relay.remoteSlot = isMaster and 1 or 0     -- 0-indexed for memory addressing
  state.relay.localBattler = isMaster and 1 or 2   -- 1-indexed for PLAYERS/PLAYERS2
  state.relay.remoteBattler = isMaster and 2 or 1  -- 1-indexed for PLAYERS/PLAYERS2
  state.relay.waitingStatus = 0
  state.relay.bufferID = 0
  state.relay.sendID = 0
  state.relay.remoteWaitingStatus = 0
  state.relay.remoteBufferID = 0
  state.relay.remoteSendID = 0
  state.relay.remoteBattleflags = { 0, 0, 0, 0 }
  state.relay.remoteTransferStage = 7  -- Start at 7 (active battle)
  state.relay.remoteBufferA = nil
  state.relay.remoteBufferB = nil
  state.relay.remoteAttacker = 0
  state.relay.remoteTarget = 0
  state.relay.remoteAbsent = 0
  state.relay.remoteEffect = 0
  state.relay.commAdvanced = false
  state.relay.commReady = false
  state.relay.lastBufferHash = {}

  -- Initialize buffer relay tables early (onRemoteBufferCmd can arrive during STARTING)
  state.relay.battleflags = { 0, 0, 0, 0 }
  state.relay.pendingRelay = {}
  state.relay.pendingCmd = {}
  state.relay.processingCmd = {}
  state.relay.remoteBufferB_queue = {}
  state.relay.activeCmd = {}             -- CLIENT: per-frame re-write data during processing
  state.relay.lastClientBufB = {}        -- HOST: per-frame re-write of CLIENT's bufferB
  state.relay.ctxWritten = {}            -- CLIENT: context vars written once per command (not per-frame)
  state.relay.pendingAck = {}            -- D5: HOST waits for CLIENT ACK before activating remote battler
  state.relay.introComplete = false

  -- CRITICAL: Save local party BEFORE battle init!
  state.localPartyBackup = Battle.readLocalParty()
  if state.localPartyBackup then
    console:log(string.format("[Battle] Local party backed up (%d bytes)", #state.localPartyBackup))
  else
    console:log("[Battle] WARNING: Could not backup local party!")
  end

  -- Determine battle entry point
  local battleEntryAddr = nil
  local entryName = "?"

  if LINK and LINK.CB2_InitBattle then
    battleEntryAddr = LINK.CB2_InitBattle
    entryName = "CB2_InitBattle"
  elseif LINK and LINK.CB2_HandleStartBattle then
    battleEntryAddr = LINK.CB2_HandleStartBattle
    entryName = "CB2_HandleStartBattle (fallback)"
  else
    console:log("[Battle] ERROR: no battle entry address configured")
    return false
  end

  -- Set battle type flags
  -- GBA-PK style: Only HOST gets IS_MASTER. Slave gets LINK+TRAINER only.
  -- This prevents DMA corruption on the master that was caused by both having IS_MASTER.
  local flags = BATTLE_TYPE_LINK | BATTLE_TYPE_TRAINER
  if isMaster then
    flags = flags | BATTLE_TYPE_IS_MASTER
  end
  state.battleFlags = flags
  state.isLinkBattle = true

  local ok = pcall(writeMem32, ADDRESSES.gBattleTypeFlags, flags)
  if not ok then
    console:log("[Battle] ERROR: failed to write gBattleTypeFlags")
    return false
  end
  console:log(string.format("[Battle] gBattleTypeFlags = 0x%08X (master=%s)", flags, tostring(isMaster)))

  -- Apply ROM+EWRAM patches BEFORE triggering battle
  Battle.applyPatches(isMaster)

  -- GBA-PK style: clear stale controller function pointers from previous battles
  if LINK and LINK.gBattlerControllerFuncs then
    for i = 0, 3 do pcall(writeMem32, LINK.gBattlerControllerFuncs + i * 4, 0) end
    console:log("[Battle] Pre-cleared gBattlerControllerFuncs (4 x u32 = 0)")
  end

  -- Set gBlockReceivedStatus to 0x00 (GBA-PK stage 2: clear before InitiateBattle)
  -- Will be set to 0x03 at comm skip (stage 4-5), then 0x0F by maintainLinkState during battle.
  if LINK and LINK.gBlockReceivedStatus then
    for i = 0, 3 do pcall(writeMem8, LINK.gBlockReceivedStatus + i, 0x00) end
  end

  -- Clear link status byte
  if LINK and LINK.linkStatusByte then
    pcall(writeMem8, LINK.linkStatusByte, 0)
  end

  -- Set gMain.savedCallback for proper return-to-overworld after battle
  local gMainBase = config.warp.callback2Addr - 4  -- callback2 is at gMain+0x04
  local savedCbOffset = (LINK and LINK.savedCallbackOffset) or 0x08
  local savedCallbackAddr = gMainBase + savedCbOffset
  if LINK and LINK.CB2_ReturnToField then
    pcall(writeMem32, savedCallbackAddr, LINK.CB2_ReturnToField)
    console:log(string.format("[Battle] savedCallback = 0x%08X (CB2_ReturnToField)", LINK.CB2_ReturnToField))
  elseif config.warp.cb2Overworld then
    pcall(writeMem32, savedCallbackAddr, config.warp.cb2Overworld)
    console:log(string.format("[Battle] savedCallback = 0x%08X (CB2_Overworld fallback)", config.warp.cb2Overworld))
  end

  -- Save callback1 so we can restore it after battle
  local ok1, cb1 = pcall(readMem32, gMainBase + 0x00)
  if ok1 and cb1 >= 0x08000000 and cb1 < 0x0A000000 then
    state.savedCallback1 = cb1
    console:log(string.format("[Battle] Saved callback1 = 0x%08X", cb1))
  end

  -- NULL callback1 before triggering battle
  pcall(writeMem32, gMainBase + 0x00, 0)

  -- Clear gBattleCommunication[MULTIUSE_STATE]
  if LINK and LINK.gBattleCommunication then
    pcall(writeMem8, LINK.gBattleCommunication, 0)
  end

  -- GBA-PK: Initialize local link player (reads real name from SaveBlock2)
  -- Must be called BEFORE triggering battle so VS screen shows real player name
  if initLocalLinkPlayer() then
    console:log("[Battle] InitLocalLinkPlayer: real name written to gLinkPlayers[0]")
  else
    console:log("[Battle] InitLocalLinkPlayer: using fallback names (PLAYER/RIVAL)")
  end

  -- Clear sBlockSend (10 bytes) — GBA-PK clears this at stage 2
  if LINK and LINK.sBlockSend then
    for i = 0, 9 do pcall(writeMem8, LINK.sBlockSend + i, 0) end
  end

  -- Clear gLinkCallback — prevent stale link callback from firing
  if LINK and LINK.gLinkCallback then
    pcall(writeMem32, LINK.gLinkCallback, 0)
  end

  -- GBA-PK: Do NOT blank screen — battle engine handles transitions naturally

  -- Reset gMain.state to 0
  local stateOff = config.warp.gMainStateOffset or 0x438
  pcall(writeMem16, gMainBase + stateOff, 0)

  -- === Battle Entry: Direct callback2 write ===
  -- NOTE: loadscript(37) removed — it never changed callback2 in time (always fell back to
  -- direct_write after 15 frames), and it created Task_StartWiredCableClubBattle (0x080D1655)
  -- which survived the battle (outside killLinkTasks range) and overwrote savedCallback to
  -- CB2_ReturnFromCableClubBattle, causing a post-battle save screen + double fade.
  pcall(writeMem32, config.warp.callback2Addr, battleEntryAddr)
  state.battleEntryMethod = "direct_write"
  console:log(string.format("[Battle] callback2 = 0x%08X (direct write)", battleEntryAddr))

  -- Transition to STARTING stage
  state.stage = STAGE.STARTING
  state.frameCounter = 0
  state.stageTimer = 0
  state.stageClock = os.clock()
  screenshotState.count = 0
  screenshotState.lastFrame = -999999

  if state.sendFn then
    state.sendFn({ type = "duel_stage", stage = STAGE.STARTING })
  end

  console:log(string.format("[Battle] Battle started (master=%s, entry=%s)", tostring(isMaster), entryName))
  return true
end

-- ============================================================
-- Buffer Relay Helpers
-- ============================================================

local function readEWRAMBlock(addr, size)
  local offset = toWRAMOffset(addr)
  local data = {}
  local ok = pcall(function()
    for i = 0, size - 1 do data[i + 1] = emu.memory.wram:read8(offset + i) end
  end)
  if ok and #data == size then return data end
  return nil
end

local function writeEWRAMBlock(addr, data)
  local offset = toWRAMOffset(addr)
  local ok = pcall(function()
    for i = 1, #data do emu.memory.wram:write8(offset + i - 1, data[i]) end
  end)
  return ok
end

local function hashBytes(data)
  if not data then return 0 end
  local h = 0
  for i = 1, #data do
    h = ((h << 5) + h + data[i]) & 0xFFFFFFFF
  end
  return h
end

-- Cached buffer base addresses (verified once, reused)
local cachedBufABase = nil
local cachedBufBBase = nil
local bufferAddressesVerified = false

-- Dereference gBattleResources to get heap-allocated buffer base addresses
local function getBufferAddresses()
  -- Return cached if already verified
  if bufferAddressesVerified and cachedBufABase then
    return cachedBufABase, cachedBufBBase
  end

  if not LINK or not LINK.gBattleResources then return nil, nil end

  local ok, resPtr = pcall(readMem32, LINK.gBattleResources)
  if not ok or not resPtr or resPtr < 0x02000000 or resPtr > 0x0203FFFF then
    return nil, nil
  end

  -- Try configured offset first, fallback to vanilla expansion offset
  local offsets_to_try = {
    { a = LINK.bufferA_offset or 0x024, b = LINK.bufferB_offset or 0x824, label = "R&B" },
    { a = 0x010, b = 0x810, label = "vanilla-expansion" },
  }

  for _, off in ipairs(offsets_to_try) do
    local bufABase = resPtr + off.a
    local bufBBase = resPtr + off.b
    -- Verify: bufferB should be exactly bufferA + 0x800 (4 battlers × 0x200)
    if bufBBase - bufABase == 0x800 then
      -- Verify the computed addresses are in valid EWRAM range
      if bufABase >= 0x02000000 and bufBBase + 0x800 <= 0x02040000 then
        if not bufferAddressesVerified then
          console:log(string.format("[Battle] Buffer addresses: resPtr=0x%08X bufA=0x%08X bufB=0x%08X (%s offsets 0x%03X/0x%03X)",
            resPtr, bufABase, bufBBase, off.label, off.a, off.b))
          bufferAddressesVerified = true
        end
        cachedBufABase = bufABase
        cachedBufBBase = bufBBase
        return bufABase, bufBBase
      end
    end
  end

  return nil, nil
end

-- Read bufferA and bufferB for a given battler slot (0-indexed)
-- GBA-PK reads 256 bytes per buffer per battler
local function readBattlerBuffers(battlerSlot)
  local bufABase, bufBBase = getBufferAddresses()
  if not bufABase or not bufBBase then return nil, nil end

  local bufAAddr = bufABase + battlerSlot * BATTLER_BUFFER_STRIDE
  local bufBAddr = bufBBase + battlerSlot * BATTLER_BUFFER_STRIDE

  local bufA = readEWRAMBlock(bufAAddr, BUFFER_READ_SIZE)
  local bufB = readEWRAMBlock(bufBAddr, BUFFER_READ_SIZE)

  return bufA, bufB
end

-- Write bufferA and bufferB for a given battler slot (0-indexed)
local function writeBattlerBuffers(battlerSlot, bufA, bufB)
  local bufABase, bufBBase = getBufferAddresses()
  if not bufABase or not bufBBase then return false end

  if bufA and #bufA > 0 then
    local bufAAddr = bufABase + battlerSlot * BATTLER_BUFFER_STRIDE
    writeEWRAMBlock(bufAAddr, bufA)
  end

  if bufB and #bufB > 0 then
    local bufBAddr = bufBBase + battlerSlot * BATTLER_BUFFER_STRIDE
    writeEWRAMBlock(bufBAddr, bufB)
  end

  return true
end

-- ============================================================
-- Buffer Relay Network Handlers
-- ============================================================

function Battle.onRemoteBuffer(message)
  if not message then return end
  local relay = state.relay

  -- Store remote player's GBA-PK protocol state (mirrors otherplayerBattle in GBA-PK)
  if message.p ~= nil then relay.remoteWaitingStatus = message.p end
  if message.bufID ~= nil then relay.remoteBufferID = message.bufID end
  if message.sendID ~= nil then relay.remoteSendID = message.sendID end
  if message.ef then relay.remoteBattleflags = message.ef end

  -- Store buffer data for writing in next tick
  if message.bufA then relay.remoteBufferA = message.bufA end
  if message.bufB then relay.remoteBufferB = message.bufB end
  if message.attacker ~= nil then relay.remoteAttacker = message.attacker end
  if message.target ~= nil then relay.remoteTarget = message.target end
  if message.absent ~= nil then relay.remoteAbsent = message.absent end
  if message.effect ~= nil then relay.remoteEffect = message.effect end

  -- Mark that we have received at least one message from remote
  relay.remoteDataReceived = true
end

function Battle.onRemoteChoice(message)
  if not message then return end
  if message.action ~= nil then
    state.relay.remoteAction = {
      action = message.action,
      move = message.move or 0
    }
    state.relay.remoteReady = true
    console:log(string.format("[Battle] Remote choice received: action=%d move=%d",
      message.action, message.move or 0))
  end
end

-- GBA-PK Buffer Relay: CLIENT receives command from HOST (bufferA)
function Battle.onRemoteBufferCmd(message)
  if not message or message.battler == nil then return end
  state.relay.lastRelayActivityFrame = state.stageTimer
  -- Store both bufA and ctx (attacker/target/absent/effect) for the relay protocol
  state.relay.pendingCmd[message.battler] = { bufA = message.bufA, bufB = message.bufB, ctx = message.ctx }
  console:log(string.format("[Battle] CLIENT: Received bufA cmd from HOST for battler %d (cmd=0x%02X)",
    message.battler, (message.bufA and message.bufA[1]) or 0))
end

-- GBA-PK Buffer Relay: HOST receives response from CLIENT (bufferB)
function Battle.onRemoteBufferResp(message)
  if not message or message.battler == nil then return end
  state.relay.lastRelayActivityFrame = state.stageTimer
  state.relay.remoteBufferB_queue[message.battler] = message.bufB
  console:log(string.format("[Battle] HOST: Received bufB resp from CLIENT for battler %d",
    message.battler))
end

-- D5: HOST receives ACK from CLIENT (bufferA written confirmation)
-- GBA-PK waits for FLAGS.WRITTEN before activating controller — this is our equivalent.
function Battle.onRemoteBufferAck(message)
  if not message or message.battler == nil then return end
  state.relay.lastRelayActivityFrame = state.stageTimer
  if state.relay.pendingAck then
    state.relay.pendingAck[message.battler] = true
  end
  console:log(string.format("[Battle] HOST: Received ACK from CLIENT for battler %d", message.battler))
end

function Battle.onRemoteStage(remoteStage)
  -- Handle string stage names (GBA-PK readiness signaling)
  if remoteStage == "mainloop_ready" then
    state.relay.remoteMainloopReady = true
    console:log("[Battle] Remote player entered MAIN_LOOP — relay enabled")
    return
  end
  local stageNum = tonumber(remoteStage)
  if stageNum and stageNum >= STAGE.STARTING then
    state.remoteReady = true
  end
end

-- ============================================================
-- Maintain Link State (called every frame while LINK active)
-- ============================================================

local function maintainLinkState(blockRecvStatus)
  if not LINK then return end
  -- blockRecvStatus: 0x0F during STARTING pre-comm-skip (engine needs "all received" to advance),
  --                  0x03 during MAIN_LOOP (GBA-PK leaves at 0x03 after comm skip, never touches again)
  local brs = blockRecvStatus or 0x0F
  if LINK.gReceivedRemoteLinkPlayers then
    pcall(writeMem8, LINK.gReceivedRemoteLinkPlayers, 1)
  end
  if LINK.gWirelessCommType then
    pcall(writeMem8, LINK.gWirelessCommType, 0)
  end
  if LINK.gBlockReceivedStatus then
    for i = 0, 3 do pcall(writeMem8, LINK.gBlockReceivedStatus + i, brs) end
  end
  if LINK.linkStatusByte then
    pcall(writeMem8, LINK.linkStatusByte, 0)
  end
  -- NOTE: gBlockRecvBuffer byte 2 is vsScreenHealthFlagsLo (NOT dataSize).
  -- Previously zeroed here to prevent VBlank garbage memcpy, but ROM patch #10
  -- (NOP TryReceiveLinkBattleData) already prevents that. Zeroing byte 2 destroyed
  -- the health flags written by injectEnemyParty, causing incorrect VS screen pokeballs.
end

-- ============================================================
-- Maintain gLinkPlayers names (prevent infinite text print)
-- ROOT CAUSE: DoBattleIntro expands "{LINK_OPPONENT} wants to battle!" text
-- GBA-PK style: write proper gLinkPlayers struct fields like InitiateBattle().
-- struct LinkPlayer (28 bytes = 0x1C):
--   0x00 u16 version     (VERSION_EMERALD = 3)
--   0x04 u32 trainerId
--   0x08 u8[8] name      (GBA encoded, 7 chars + 0xFF terminator)
--   0x13 u8 gender        (0=male, 1=female)
--   0x14 u32 linkType
--   0x18 u16 id           (battler id: 0 or 1)
--   0x1A u16 language     (LANGUAGE_ENGLISH = 2)
-- Must be called EVERY frame during DoBattleIntro (DMA/link ops can zero it).
-- ============================================================

-- GBA encoded fallback names: "PLAYER" and "RIVAL"
local GBA_NAME_PLAYER = {0xCA, 0xC6, 0xBB, 0xD3, 0xBF, 0xCC, 0xFF, 0x00}  -- "PLAYER" + terminator
local GBA_NAME_RIVAL  = {0xCC, 0xC3, 0xD5, 0xBB, 0xC6, 0xFF, 0x00, 0x00}  -- "RIVAL" + terminator

-- Cached real player name (read once from SaveBlock2 via initLocalLinkPlayer)
local cachedLocalName = nil
local cachedLocalGender = 0
local cachedLocalTrainerId = 0

-- Cached opponent data (received via TCP duel_player_info)
local cachedOpponentName = nil
local cachedOpponentGender = 0
local cachedOpponentTrainerId = 0

-- ============================================================
-- InitLocalLinkPlayer — Lua equivalent of ROM function
-- Reads player name, gender, trainerId from gSaveBlock2Ptr
-- and writes them to gLinkPlayers[0] (the local player entry).
-- This makes the VS screen show the real player name instead of "PLAYER".
--
-- SaveBlock2 layout (pokeemerald-expansion):
--   +0x00: u8[8]  playerName (GBA encoded, 7 chars + 0xFF terminator)
--   +0x08: u8     playerGender (0=male, 1=female)
--   +0x09: u8     specialSaveWarpFlags
--   +0x0A: u8[4]  playerTrainerId
--
-- LinkPlayer struct (28 bytes = 0x1C):
--   +0x00: u16 version     (VERSION_EMERALD = 3)
--   +0x04: u32 trainerId
--   +0x08: u8[8] name      (GBA encoded, 7 chars + 0xFF terminator)
--   +0x13: u8 gender       (0=male, 1=female)
--   +0x14: u32 linkType
--   +0x18: u16 id           (battler id: 0 or 1)
--   +0x1A: u16 language     (LANGUAGE_ENGLISH = 2)
-- ============================================================

initLocalLinkPlayer = function()
  if not LINK or not LINK.gLinkPlayers then return false end
  if not LINK.gSaveBlock2Ptr then
    console:log("[Battle] initLocalLinkPlayer: no gSaveBlock2Ptr configured, using fallback names")
    return false
  end

  -- Read gSaveBlock2Ptr (IWRAM pointer to EWRAM data)
  local ok, sb2Addr = pcall(readMem32, LINK.gSaveBlock2Ptr)
  if not ok or sb2Addr < 0x02000000 or sb2Addr > 0x0203FFFF then
    console:log(string.format("[Battle] initLocalLinkPlayer: invalid gSaveBlock2Ptr = 0x%08X", sb2Addr or 0))
    return false
  end

  -- Read player name (8 bytes at SB2+0x00)
  local playerName = {}
  for i = 0, 7 do
    local okN, byte = pcall(readMem8, sb2Addr + i)
    playerName[i + 1] = (okN and byte) or 0xFF
  end
  -- Ensure 0xFF terminator
  if playerName[8] ~= 0xFF then playerName[8] = 0xFF end

  -- Read gender (SB2+0x08)
  local okG, gender = pcall(readMem8, sb2Addr + 0x08)
  gender = (okG and gender) or 0

  -- Read trainerId (4 bytes at SB2+0x0A, stored as u32)
  local okT, trainerId = pcall(readMem32, sb2Addr + 0x0A)
  trainerId = (okT and trainerId) or 0

  -- Cache for maintainLinkPlayers
  cachedLocalName = playerName
  cachedLocalGender = gender
  cachedLocalTrainerId = trainerId

  -- Write to gLinkPlayers[0]
  local glp = LINK.gLinkPlayers
  pcall(function()
    writeMem16(glp + 0x00, 3)            -- version = VERSION_EMERALD
    writeMem32(glp + 0x04, trainerId)    -- trainerId
    for i = 0, 7 do                      -- name
      writeMem8(glp + 0x08 + i, playerName[i + 1])
    end
    writeMem8(glp + 0x13, gender)        -- gender
    writeMem32(glp + 0x14, 0x2233)       -- linkType = SINGLE_BATTLE
    writeMem16(glp + 0x18, 0)            -- id = 0 (local player)
    writeMem16(glp + 0x1A, 2)            -- language = LANGUAGE_ENGLISH
  end)

  -- Log the decoded name for debugging
  local nameStr = ""
  for i = 1, 7 do
    local b = playerName[i]
    if b == 0xFF then break end
    -- GBA text: A=0xBB, a=0xD5, space=0x00
    if b >= 0xBB and b <= 0xD4 then
      nameStr = nameStr .. string.char(string.byte("A") + (b - 0xBB))
    elseif b >= 0xD5 and b <= 0xEE then
      nameStr = nameStr .. string.char(string.byte("a") + (b - 0xD5))
    elseif b == 0x00 then
      nameStr = nameStr .. " "
    else
      nameStr = nameStr .. string.format("<%02X>", b)
    end
  end
  console:log(string.format("[Battle] initLocalLinkPlayer: name='%s' gender=%d trainerId=0x%08X", nameStr, gender, trainerId))
  return true
end

-- NOTE: triggerLoadscript37 REMOVED — it created Task_StartWiredCableClubBattle (0x080D1655)
-- which survived the battle (outside killLinkTasks range 0x08025000-0x0804A000) and
-- overwrote savedCallback to CB2_ReturnFromCableClubBattle, causing post-battle save screen
-- + double fade. Direct callback2 write is always used now.

local function loadscriptClear()
    if not (LINK and LINK.gScriptLoad) then return end
    -- GBA-PK RemoveScriptFromMemory: mode=513, ptr=0 = disabled
    local clearData = {0, 0, 513, 0, 0, 0, 0, 0, 0, 0, 0, 0}
    local slOff = LINK.gScriptLoad - 0x03000000
    for i, w in ipairs(clearData) do
        emu.memory.iwram:write32(slOff + (i-1)*4, w)
    end
end

local function maintainLinkPlayers()
  if not LINK or not LINK.gLinkPlayers then return end
  pcall(function()
    local LP_SIZE = 0x1C  -- sizeof(struct LinkPlayer) = 28 bytes

    -- Use real names from SaveBlock2 (local) and TCP exchange (opponent)
    local localName = cachedLocalName or (state.isMaster and GBA_NAME_PLAYER or GBA_NAME_RIVAL)
    local remoteName = cachedOpponentName or GBA_NAME_RIVAL
    local names = {
      [0] = state.isMaster and localName or remoteName,
      [1] = state.isMaster and remoteName or localName,
    }

    -- Write entries 0 and 1 (host and client)
    for i = 0, 1 do
      local base = LINK.gLinkPlayers + i * LP_SIZE
      -- version = VERSION_EMERALD (3)
      writeMem16(base + 0x00, 3)
      -- trainerId (local for our slot, opponent for remote slot)
      local tid = 0
      if (i == 0 and state.isMaster) or (i == 1 and not state.isMaster) then
        tid = cachedLocalTrainerId
      else
        tid = cachedOpponentTrainerId
      end
      if tid ~= 0 then writeMem32(base + 0x04, tid) end
      -- name (8 bytes at offset 0x08)
      for j = 0, 7 do
        writeMem8(base + 0x08 + j, names[i][j + 1])
      end
      -- gender (local for our slot, opponent for remote slot)
      local g = 0
      if (i == 0 and state.isMaster) or (i == 1 and not state.isMaster) then
        g = cachedLocalGender
      else
        g = cachedOpponentGender
      end
      writeMem8(base + 0x13, g)
      -- id = battler index
      writeMem16(base + 0x18, i)
      -- language = LANGUAGE_ENGLISH (2)
      writeMem16(base + 0x1A, 2)
    end

    -- Entry 4 (offset 4*0x1C = 0x70): battle text uses this for opponent name display
    local opponentEntry = state.isMaster and 1 or 0
    local textBase = LINK.gLinkPlayers + 4 * LP_SIZE
    writeMem16(textBase + 0x00, 3)
    for j = 0, 7 do
      writeMem8(textBase + 0x08 + j, names[opponentEntry][j + 1])
    end
    writeMem8(textBase + 0x13, 0)
    writeMem16(textBase + 0x1A, 2)
  end)
end

-- ============================================================
-- Kill Link Tasks (prevent EWRAM heap corruption)
-- gTasks at 0x03005E10 (IWRAM), 16 tasks × 40 bytes
-- Task.func at +0x00, Task.isActive at +0x04
-- ============================================================
local GTASKS_ADDR = 0x03005E10  -- IWRAM
local TASK_SIZE = 40
local TASK_COUNT = 16
local TASK_DUMMY = 0x080C6FF1   -- TaskDummy (THUMB) — safe no-op function

local function killLinkTasks()
  local killedTasks = 0
  local activeTasks = {}
  pcall(function()
    for i = 0, TASK_COUNT - 1 do
      local taskBase = GTASKS_ADDR + i * TASK_SIZE
      local isActive = emu.memory.iwram:read8(toIWRAMOffset(taskBase) + 4)
      if isActive == 1 then
        local func = emu.memory.iwram:read32(toIWRAMOffset(taskBase))
        table.insert(activeTasks, { idx = i, func = func })

        -- Kill tasks in link/comm ROM range (0x08025000-0x0804A000)
        -- This covers: link_rfu.c, link.c, cable_club.c, battle_controllers.c link tasks
        -- Including: HandleLinkBattleSetup, Task_WaitForLinkPlayerConnection,
        -- Task_HandleSendLinkBuffersData, Task_HandleCopyReceivedLinkBuffersData
        local funcBase = func & 0xFFFFFFFE  -- Clear THUMB bit
        local isLinkRange = (funcBase >= 0x08025000 and funcBase < 0x0804A000)

        if isLinkRange then
          emu.memory.iwram:write32(toIWRAMOffset(taskBase), TASK_DUMMY)
          killedTasks = killedTasks + 1
        end
      end
    end
  end)
  return killedTasks, activeTasks
end

-- ============================================================
-- State Machine Tick
-- ============================================================

function Battle.tick()
  if state.stage == STAGE.IDLE then return end

  state.frameCounter = (state.frameCounter or 0) + 1
  state.stageTimer = state.stageTimer + 1

  -- Read inBattle (bitfield: bit 1 of byte at gMain+0x439)
  local inBattle = nil
  if ADDRESSES and ADDRESSES.gMainInBattle then
    local ok, val = pcall(readMem8, ADDRESSES.gMainInBattle)
    if ok then
      inBattle = ((val & 0x02) ~= 0) and 1 or 0
    end
  end

  -- Track inBattle transitions
  if inBattle then
    if state.prevInBattle == 0 and inBattle == 1 then
      state.battleDetected = true
      console:log("[Battle] inBattle 0->1: battle engine running")
    end
    state.prevInBattle = inBattle
  end

  -- === STAGE: STARTING ===
  -- GBA-PK stages 3-6: ROM patches, party exchange, comm advancement, VS screen
  if state.stage == STAGE.STARTING then
    -- (Loadscript(37) fallback removed — direct_write is always used now)

    -- Keep link-related RAM values correct during init
    -- GBA-PK: 0x0F before comm advancement (engine needs it to advance through early cases)
    --         0x03 after comm advancement to 7 (skip link exchange, states 7-10 auto-advance)
    -- Note: GetBlockReceivedStatus is patched to return 0x0F always, so memory value
    -- doesn't affect engine behavior — but this aligns with GBA-PK's timing.
    local brsValue = state.relay.commAdvanced and 0x03 or 0x0F
    maintainLinkState(brsValue)

    -- Maintain gLinkPlayers names DURING STARTING to ensure 0xFF terminators
    -- are present BEFORE DoBattleIntro begins (which starts at MAIN_LOOP).
    -- This is belt-and-suspenders: the main defense is in MAIN_LOOP every frame.
    maintainLinkPlayers()

    -- Kill link tasks EARLY to prevent DMA corruption (esp. on master)
    -- The task at 0x08035975 does link buffer operations that corrupt EWRAM heap
    -- when IS_MASTER is set. Kill every 30 frames in case tasks get re-created.
    if state.stageTimer <= 5 or state.stageTimer % 30 == 0 then
      local killed, tasks = killLinkTasks()
      if killed > 0 then
        local taskLog = {}
        for _, t in ipairs(tasks) do
          table.insert(taskLog, string.format("[%d]=0x%08X", t.idx, t.func))
        end
        console:log(string.format("[Battle] STARTING: killed %d link tasks: %s", killed, table.concat(taskLog, " ")))
      end
    end

    -- Force battle type flags during init (keep LINK active)
    if ADDRESSES and ADDRESSES.gBattleTypeFlags and state.battleFlags then
      local ok, currentFlags = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
      if ok then
        local merged = currentFlags | state.battleFlags
        if merged ~= currentFlags then
          pcall(writeMem32, ADDRESSES.gBattleTypeFlags, merged)
        end
      end
    end

    -- Detect CB2_HandleStartBattle (needed for comm advancement)
    local inHandleStartBattle = false
    if LINK and LINK.CB2_HandleStartBattle and config and config.warp then
      local okCb, cb2 = pcall(readMem32, config.warp.callback2Addr)
      if okCb and cb2 == LINK.CB2_HandleStartBattle then
        inHandleStartBattle = true
      end
    end

    -- Re-inject BOTH parties every 10 frames during CB2_HandleStartBattle
    -- (Cases 4/6/8 copy from gBlockRecvBuffer and overwrite parties)
    if inHandleStartBattle and state.stageTimer % 10 == 0 then
      if state.localPartyBackup and ADDRESSES and ADDRESSES.gPlayerParty then
        local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)
        pcall(function()
          for i = 1, PARTY_SIZE do
            emu.memory.wram:write8(baseOffset + i - 1, state.localPartyBackup[i])
          end
        end)
      end
      if state.opponentParty and ADDRESSES and ADDRESSES.gEnemyParty then
        local baseOffset = toWRAMOffset(ADDRESSES.gEnemyParty)
        pcall(function()
          for i = 1, PARTY_SIZE do
            emu.memory.wram:write8(baseOffset + i - 1, state.opponentParty[i])
          end
        end)
      end
    end

    -- === STAGE 4-5: Wait for comm==2, inject parties, skip to state 7 ===
    -- R&B has 11 states (0-10) in CB2_HandleStartBattle, NOT 17 like vanilla expansion.
    -- States 3-6 do link party exchange via SendBlock/memcpy — we do this via TCP instead.
    -- State 7 = InitBattleControllers (critical!), states 8-9 = more link data, state 10 = SetMainCallback2(BattleMainCB2).
    -- Skip from state 2 to state 7 to avoid unnecessary link operations while preserving
    -- the InitBattleControllers call and BattleMainCB2 transition.
    -- NOTE: Setting comm to 12 (old value) made CB2_HandleStartBattle exit immediately
    -- (CMP R0, #10; BHI → exit), preventing BattleMainCB2 from ever being set.
    -- Without BattleMainCB2, RunTextPrinters() was never called → empty textboxes!
    if inHandleStartBattle and not state.relay.commAdvanced and LINK and LINK.gBattleCommunication then
      local okC, comm0 = pcall(readMem8, LINK.gBattleCommunication)
      if okC then
        if comm0 >= 2 and comm0 < 7 then
          -- Re-inject parties before skipping (ensures correct data for VS screen health flags)
          if state.opponentParty and ADDRESSES and ADDRESSES.gEnemyParty then
            Battle.injectEnemyParty(state.opponentParty)
          end
          if state.localPartyBackup and ADDRESSES and ADDRESSES.gPlayerParty then
            local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)
            pcall(function()
              for i = 1, PARTY_SIZE do
                emu.memory.wram:write8(baseOffset + i - 1, state.localPartyBackup[i])
              end
            end)
          end

          -- Skip to state 7 (InitBattleControllers) — states 3-6 are link exchange, handled by TCP
          pcall(writeMem8, LINK.gBattleCommunication, 7)
          -- Set gBlockReceivedStatus = 0x03 (GBA-PK stage 4: players 0+1 "received")
          if LINK.gBlockReceivedStatus then
            for i = 0, 3 do pcall(writeMem8, LINK.gBlockReceivedStatus + i, 0x03) end
          end
          -- D1 fix: OR merge instead of overwrite — preserve any bits the ROM engine set during cases 0-2
          if ADDRESSES and ADDRESSES.gBattleTypeFlags and state.battleFlags then
            local okBtf, curBtf = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
            if okBtf then
              pcall(writeMem32, ADDRESSES.gBattleTypeFlags, curBtf | state.battleFlags)
            else
              pcall(writeMem32, ADDRESSES.gBattleTypeFlags, state.battleFlags)
            end
          end
          pcall(writeMem8, LINK.gReceivedRemoteLinkPlayers, 1)
          -- GBA-PK defense-in-depth: clear exec flags + bufferA at comm skip
          -- NOTE: gBattlerControllerFuncs NOT cleared here — InitBtlControllersInternal
          -- already set them. HOST=master path (Player/LinkOpp), CLIENT=slave path
          -- (LinkOpp/Player — reversed, matching relay localSlot/remoteSlot mapping).
          if LINK.gBattleControllerExecFlags then
            pcall(writeMem32, LINK.gBattleControllerExecFlags, 0)
          end
          local bufAClr = getBufferAddresses()
          if bufAClr then pcall(writeMem32, bufAClr, 0) end
          -- Re-apply savedCallback (Task_StartWiredCableClubBattle overwrites it at case 7)
          if LINK.CB2_ReturnToField and config and config.warp then
            local gmBase = config.warp.callback2Addr - 4
            local savedCbAddr = gmBase + ((LINK and LINK.savedCallbackOffset) or 0x08)
            pcall(writeMem32, savedCbAddr, LINK.CB2_ReturnToField)
          end
          state.relay.commAdvanced = true
          console:log(string.format("[Battle] Stage 4-5: comm[0]=%d -> 7 (R&B: skip to InitBattleControllers), parties re-injected", comm0))
        elseif comm0 >= 7 then
          state.relay.commAdvanced = true
        end
      end
    end

    -- CLIENT FIX: Write gBattleMainFunc = BeginBattleIntro
    -- Slave path sets BeginBattleIntroDummy (no-op) → battle stuck without this.
    -- Every-frame write because the exact timing of InitBtlControllersInternal (state 1 or 7) is ambiguous.
    if not state.isMaster and state.relay.commAdvanced and LINK
        and LINK.gBattleMainFunc and LINK.BeginBattleIntro then
      pcall(writeMem32, LINK.gBattleMainFunc, LINK.BeginBattleIntro)
    end

    -- === STAGE 6: Wait for states 7-10 to complete naturally ===
    -- R&B states 7-10 auto-advance with our patches (IsLinkTaskFinished→TRUE, GetBlockReceivedStatus→0x0F).
    -- State 10 calls SetMainCallback2(BattleMainCB2) which changes callback2 — detected below.
    -- No manual comm advancement needed (R&B has no state 16/18 like vanilla expansion).
    if inHandleStartBattle and state.relay.commAdvanced and not state.relay.commReady and LINK and LINK.gBattleCommunication then
      local okC, comm0 = pcall(readMem8, LINK.gBattleCommunication)
      if okC and comm0 >= 10 then
        state.relay.commReady = true
        console:log(string.format("[Battle] Stage 6: comm[0]=%d reached R&B final state 10", comm0))
      end
    end

    -- Wait for BattleMainCB2 (GBA-PK Stage 7 transition)
    local battleReady = false
    local battleReadyReason = "none"
    local battleReadyCb2 = 0
    if ADDRESSES and ADDRESSES.CB2_BattleMain and config and config.warp then
      local okCb, cb2 = pcall(readMem32, config.warp.callback2Addr)
      if okCb then
        battleReadyCb2 = cb2
        if cb2 == ADDRESSES.CB2_BattleMain then
          battleReady = true
          battleReadyReason = string.format("cb2_match(0x%08X)", cb2)
        end
      end
    elseif state.battleDetected and state.stageTimer > 300 then
      battleReady = true
      battleReadyReason = string.format("timeout(%d)", state.stageTimer)
    end

    -- Phase A: BattleMainCB2 detected → signal readiness, wait for opponent
    -- GBA-PK: sets Text_Stage=7, then waits for otherplayerBattle.Text_Stage==7
    if battleReady and not state.battleMainReached then
      state.battleMainReached = true
      state.battleReadyReason = battleReadyReason
      console:log(string.format("[Battle] BattleMainCB2 detected! reason=%s cb2=0x%08X tick=%d",
        battleReadyReason, battleReadyCb2, state.stageTimer))

      -- Final party re-injection
      if state.localPartyBackup and ADDRESSES and ADDRESSES.gPlayerParty then
        local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)
        pcall(function()
          for i = 1, PARTY_SIZE do
            emu.memory.wram:write8(baseOffset + i - 1, state.localPartyBackup[i])
          end
        end)
      end
      if state.opponentParty and ADDRESSES and ADDRESSES.gEnemyParty then
        Battle.injectEnemyParty(state.opponentParty)
      end

      -- Signal remote player (GBA-PK: otherplayerBattle.Text_Stage = 7)
      if state.sendFn then
        state.sendFn({ type = "duel_stage", stage = "mainloop_ready" })
      end
      console:log("[Battle] Sent mainloop_ready, waiting for opponent...")
    end

    -- Phase B: Both players at Stage 7 → enter MAIN_LOOP
    -- GBA-PK: Text_Stage==7 AND otherplayerBattle.Text_Stage==7
    if state.battleMainReached and state.relay.remoteMainloopReady then
      -- === TRANSITION TO MAIN_LOOP (GBA-PK Stage 7) ===
      -- LINK stays active! Link controllers handle everything.
      -- ROM patches simulate link hardware completion.
      -- We just manage exec flags and relay buffers via TCP.

      -- NOTE: No exec flags / bufferA clear here!
      -- GBA-PK only clears at comm skip (Text_Stage 5), NOT at MAIN_LOOP entry.
      -- Clearing here would race with the HOST engine: if it already dispatched a
      -- command (byte3 set) between comm skip and MAIN_LOOP, the clear destroys it
      -- → lost commands → empty textboxes or stuck battle.
      -- The comm skip clear at L1452-1454 is sufficient.

      captureScreenshot("transition_to_mainloop.png")
      console:log("[Battle] Both players ready → MAIN_LOOP (GBA-PK Stage 7: LINK active, buffer relay)")
      state.stage = STAGE.MAIN_LOOP
      state.stageTimer = 0
      state.stageClock = os.clock()
      if state.sendFn then
        state.sendFn({ type = "duel_stage", stage = STAGE.MAIN_LOOP, reason = state.battleReadyReason or "sync" })
      end
    end

    -- Diagnostic logging
    if debugOptions.log and (state.stageTimer <= 5 or state.stageTimer % 30 == 0) and config and config.warp then
      local cb2Str = "?"
      local okCb, cb2 = pcall(readMem32, config.warp.callback2Addr)
      if okCb then cb2Str = string.format("0x%08X", cb2) end

      local commState = "?"
      if LINK and LINK.gBattleCommunication then
        local okC, cs = pcall(readMem8, LINK.gBattleCommunication)
        if okC then commState = tostring(cs) end
      end

      local bmfStr = "?"
      if LINK and LINK.gBattleMainFunc then
        local okB, bmf = pcall(readMem32, LINK.gBattleMainFunc)
        if okB then bmfStr = string.format("0x%08X", bmf) end
      end

      -- Verify NOP patches every 30 frames in STARTING
      local nopOk = true
      if state.stageTimer % 30 == 1 then
        local nopChecks = {
          { off = 0x032494, name = "HLS_SBV" },
          { off = 0x032496, name = "HLS_SBV2" },
          { off = 0x036456, name = "HLS_CB2" },
          { off = 0x036458, name = "HLS_CB22" },
          { off = 0x0007BC, name = "TryRecv" },
          { off = 0x0007BE, name = "TryRecv2" },
        }
        for _, nc in ipairs(nopChecks) do
          local okR, v = pcall(emu.memory.cart0.read16, emu.memory.cart0, nc.off)
          if okR and v ~= 0x46C0 then
            nopOk = false
            console:log(string.format("[Battle] WARNING: NOP patch %s NOT applied! val=0x%04X", nc.name, v))
          end
        end
      end

      console:log(string.format("[Battle] STARTING tick=%d cb2=%s bmf=%s inBattle=%s comm[0]=%s HSB=%s",
        state.stageTimer, cb2Str, bmfStr, tostring(inBattle), commState, tostring(inHandleStartBattle)))
    end

    -- Screenshot every 150 frames in STARTING
    if state.stageTimer % 150 == 0 and state.stageTimer > 0 then
      captureScreenshot(string.format("starting_f%04d.png", state.stageTimer))
    end

    -- Timeout: 45 seconds (real-time via os.clock, speedhack-safe)
    if os.clock() - state.stageClock > 45.0 then
      console:log("[Battle] WARNING: Battle start timeout (45s)")
      Battle.restorePatches()
      state.stage = STAGE.DONE
      state.stageTimer = 0
    end
    return
  end

  -- === STAGE: MAIN_LOOP ===
  -- GBA-PK style: HOST/CLIENT buffer relay protocol.
  -- HOST drives the battle engine. CLIENT mirrors via TCP.
  -- Exec flags bytes 0-3 (bits 0-3 = active, bits 4-7 = network wait).
  -- No GBRS dynamic patching, no HTASS action sync, no iState restoration.
  if state.stage == STAGE.MAIN_LOOP then

    -- EARLY BAIL-OUT: if callback2 is no longer BattleMainCB2, battle engine has stopped.
    -- This catches:
    --   (a) Normal exit: cb2 = CB2_ReturnToField or CB2_Overworld
    --   (b) Link results screen: cb2 = CB2_InitEndLinkBattle or CB2_EndLinkBattle
    -- For case (b), the endlinkbattle script command triggers a VS results screen
    -- (PlayerHandleEndLinkBattle → SetBattleEndCallbacks → CB2_InitEndLinkBattle)
    -- which causes a visible "double fade" (fade-in results, wait, fade-out, then overworld fade-in).
    -- Fix: when cb2 leaves BattleMainCB2, force it to CB2_ReturnToField immediately,
    -- skipping any intermediate screens. The screen is already faded to black at this point.
    if not state.forceEndPending and state.stageTimer > 10 and config and config.warp then
      local okCb, cb2 = pcall(readMem32, config.warp.callback2Addr)
      if okCb then
        local battleMainAddr = ADDRESSES and ADDRESSES.CB2_BattleMain
        if battleMainAddr and cb2 ~= battleMainAddr then
          state.cachedOutcome = Battle.readOutcomeRaw()

          -- Force cb2 to CB2_ReturnToField if it's not already overworld/returnToField
          local isOverworld = (cb2 == config.warp.cb2Overworld)
          local isReturnToField = (LINK and LINK.CB2_ReturnToField and cb2 == LINK.CB2_ReturnToField)
          if not isOverworld and not isReturnToField then
            local returnCb = (LINK and LINK.CB2_ReturnToField) or config.warp.cb2Overworld
            if returnCb then
              pcall(writeMem32, config.warp.callback2Addr, returnCb)
              -- Reset gMain.state to 0 (SetMainCallback2 normally does this)
              local gMainBase = config.warp.callback2Addr - 4
              local stateOffset = config.warp.gMainStateOffset or 0x438
              pcall(writeMem32, gMainBase + stateOffset, 0)
              -- Clear BATTLE_TYPE_LINK_IN_BATTLE (CB2_InitEndLinkBattle normally does this)
              if ADDRESSES and ADDRESSES.gBattleTypeFlags then
                local okF, flags = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
                if okF and flags then
                  pcall(writeMem32, ADDRESSES.gBattleTypeFlags, flags & ~BATTLE_TYPE_LINK_IN_BATTLE)
                end
              end
              console:log(string.format("[Battle] Skipped link results screen: cb2 was 0x%08X, forced CB2_ReturnToField", cb2))
            end
          end

          state.stage = STAGE.ENDING
          state.stageTimer = 0
          state.stageClock = os.clock()
          console:log(string.format("[Battle] Quick exit: cb2=0x%08X at tick=%d", cb2, state.stageTimer))
          return
        end
      end
    end

    -- Force-end: re-inject 0x37 every frame for 30 frames (GBA-PK approach)
    if state.forceEndPending then
      local framesSinceForce = state.stageTimer - (state.forceEndFrame or 0)
      local bufABase, _ = getBufferAddresses()
      if bufABase then
        pcall(writeMem8, bufABase, CMD_GET_AWAY_EXIT)
      end
      if LINK and LINK.gBattleControllerExecFlags then
        local ok, ef0 = pcall(readMem8, LINK.gBattleControllerExecFlags)
        if ok then
          pcall(writeMem8, LINK.gBattleControllerExecFlags, (ef0 | PLAYERS[1]) & 0xCF)
        end
        pcall(writeMem8, LINK.gBattleControllerExecFlags + 2, 0)
        pcall(writeMem8, LINK.gBattleControllerExecFlags + 3, 0)
      end
      if framesSinceForce >= 30 then
        state.forceEndPending = false
        state.stage = STAGE.ENDING
        state.stageTimer = 0
        state.stageClock = os.clock()
        console:log("[Battle] Force-exit: 30f injection done → ENDING")
      end
      return  -- skip normal relay during force-end
    end

    -- Read gBattleMainFunc for context
    local currentBmf = 0
    if LINK and LINK.gBattleMainFunc then
      local okBmf, bmfVal = pcall(readMem32, LINK.gBattleMainFunc)
      if okBmf then currentBmf = bmfVal end
    end

    local isDoBattleIntro = (LINK and LINK.DoBattleIntro and currentBmf == LINK.DoBattleIntro)

    -- === FIRST FRAME: Init relay state ===
    if state.stageTimer == 1 then
      state.relay.screenshotDir = state.isMaster and "pvp_screenshots/master/" or "pvp_screenshots/slave/"
      captureScreenshot(state.relay.screenshotDir .. "mainloop_start.png")

      maintainLinkState(0x0F)
      maintainLinkPlayers()
      state.relay.localBtf = state.battleFlags

      -- Initialize GBA-PK buffer relay state
      state.relay.battleflags = { 0, 0, 0, 0 }
      state.relay.pendingRelay = {}
      state.relay.pendingCmd = {}
      state.relay.processingCmd = {}
      state.relay.remoteBufferB_queue = {}
      state.relay.activeCmd = {}             -- CLIENT: per-frame re-write data during processing
      state.relay.lastClientBufB = {}        -- HOST: per-frame re-write of CLIENT's bufferB
      state.relay.ctxWritten = {}            -- CLIENT: context vars written once per command (not per-frame)
      state.relay.introComplete = false
      state.relay.pendingAck = {}  -- D5: HOST waits for CLIENT ACK before activating remote battler

      -- D4 fix: exec flags NOT cleared here — already cleared at comm skip (stage 4-5).
      -- Clearing here would destroy any byte3 bits the engine may have set between
      -- comm skip and MAIN_LOOP entry (race condition: engine dispatches first DoBattleIntro command).

      -- D3 fix: killLinkTasks removed from MAIN_LOOP — NOP ROM patches prevent link task creation.
      -- The killLinkTasks during STARTING phase is sufficient belt-and-suspenders.

      -- Re-inject parties
      if state.localPartyBackup and ADDRESSES and ADDRESSES.gPlayerParty then
        local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)
        pcall(function()
          for i = 1, PARTY_SIZE do
            emu.memory.wram:write8(baseOffset + i - 1, state.localPartyBackup[i])
          end
        end)
      end
      if state.opponentParty and ADDRESSES and ADDRESSES.gEnemyParty then
        Battle.injectEnemyParty(state.opponentParty)
      end

      if state.sendFn then
        state.sendFn({ type = "duel_stage", stage = "mainloop_entered" })
      end

      -- (mainloop_ready already sent in STARTING phase A — both players synced before entering MAIN_LOOP)

      console:log(string.format("[Battle] MAIN_LOOP frame 1: GBA-PK buffer relay, master=%s, btf=0x%08X",
        tostring(state.isMaster), state.battleFlags))
    end

    -- ================================================================
    -- EVERY FRAME: Maintain link state + exec flags buffer relay
    -- ================================================================

    -- D2 fix: use 0x03 (GBA-PK leaves gBlockReceivedStatus at 0x03 during battle, never 0x00)
    maintainLinkState(0x03)
    -- CRITICAL: Override gReceivedRemoteLinkPlayers = 0 during active battle.
    -- ReturnFromBattleToOverworld (battle_main.c:5767) checks:
    --   if (BATTLE_TYPE_LINK && gReceivedRemoteLinkPlayers) return;
    -- With gReceivedRemoteLinkPlayers=1, the function returns early EVERY frame = deadlock.
    -- Setting to 0 lets the engine exit naturally when the battle ends.
    -- Safe: gReceivedRemoteLinkPlayers is NOT read anywhere during active battle.
    if LINK and LINK.gReceivedRemoteLinkPlayers then
      pcall(writeMem8, LINK.gReceivedRemoteLinkPlayers, 0)
    end

    -- Enforce gBattleTypeFlags (OR merge: preserve engine-set bits like LINK_IN_BATTLE)
    if ADDRESSES and ADDRESSES.gBattleTypeFlags and state.relay.localBtf then
      local okBTF, btfNow = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
      if okBTF then
        local merged = btfNow | state.relay.localBtf
        if merged ~= btfNow then
          pcall(writeMem32, ADDRESSES.gBattleTypeFlags, merged)
        end
      end
    end

    -- DoBattleIntro: maintain gLinkPlayers + auto-press A
    if isDoBattleIntro then
      maintainLinkPlayers()
      if _G.AUTO_DUEL and state.stageTimer % 15 == 0 then
        pcall(function()
          local keys = emu:getKeys()
          emu:setKeys(keys | 0x01)
        end)
      end
    end

    -- Detect DoBattleIntro completion
    if not state.relay.introComplete and state.stageTimer > 10 and not isDoBattleIntro and currentBmf ~= 0 then
      state.relay.introComplete = true
      console:log(string.format("[Battle] Intro complete! bmf=0x%08X tick=%d", currentBmf, state.stageTimer))
      captureScreenshot((state.relay.screenshotDir or "pvp_screenshots/") .. "intro_complete.png")
    end

    -- Auto-press A after intro (only if AUTO_DUEL)
    if _G.AUTO_DUEL and state.relay.introComplete and state.stageTimer % 15 == 0 then
      pcall(function()
        local keys = emu:getKeys()
        emu:setKeys(keys | 0x01)
      end)
    end

    -- ================================================================
    -- GBA-PK EXEC FLAGS BUFFER RELAY PROTOCOL
    -- ================================================================
    -- Read exec flags as 4 individual bytes
    -- byte0 = bits 0-7 (PLAYERS low active + PLAYERS2 low network)
    -- byte1 = bits 8-15
    -- byte2 = bits 16-23
    -- byte3 = bits 24-31 (PLAYERS2 high = link controller marks)
    -- ================================================================
    -- (remoteMainloopReady gate removed: both players synced before MAIN_LOOP entry)
    if LINK and LINK.gBattleControllerExecFlags then
      local efAddr = LINK.gBattleControllerExecFlags
      local efOk, byte0, byte1, byte2, byte3
      efOk = true
      local ok0, b0 = pcall(readMem8, efAddr + 0)
      local ok1, b1 = pcall(readMem8, efAddr + 1)
      local ok2, b2 = pcall(readMem8, efAddr + 2)
      local ok3, b3 = pcall(readMem8, efAddr + 3)
      if ok0 and ok1 and ok2 and ok3 then
        byte0, byte1, byte2, byte3 = b0, b1, b2, b3
      else
        efOk = false
        byte0, byte1, byte2, byte3 = 0, 0, 0, 0
      end

      local bufABase, bufBBase = getBufferAddresses()

      if efOk and bufABase and bufBBase then
        -- ============================================================
        -- GBA-PK style byte3 nibble shift:
        -- MarkBattlerForControllerExec may set bits in byte3's LOW nibble
        -- (bits 24-27) instead of HIGH nibble (bits 28-31). Shift them up
        -- so our PLAYERS2 checks work correctly.
        -- ============================================================
        if byte3 ~= 0 and (byte3 >> 4) == 0 then
          byte3 = byte3 << 4
        end

        -- Clear byte2 every frame (GBA-PK does this)
        byte2 = 0

        local remoteSlot = state.relay.remoteSlot  -- 0-indexed: master=1, slave=0
        local localSlot = state.relay.localSlot     -- 0-indexed: master=0, slave=1

        -- ============================================================
        -- HOST: Relay ALL battlers (like GBA-PK)
        -- GBA-PK sends bufferA for EVERY battler with byte3 set.
        -- D5: For REMOTE battlers, wait for CLIENT ACK before activating controller
        --     (GBA-PK waits for FLAGS.WRITTEN before clearing byte3 + setting byte0).
        --     For LOCAL battlers, activate immediately (HOST's own controller).
        -- ============================================================
        if state.isMaster then
          for battler = 0, 1 do
            local p2bit = (1 << (4 + battler))  -- PLAYERS2 bit in byte3
            local pbit = (1 << battler)          -- PLAYERS bit in byte0
            local isRemote = (battler == remoteSlot)

            -- Phase 1: Detect new command in byte3 for ANY battler
            if (byte3 & p2bit) ~= 0 and not state.relay.pendingRelay[battler] then
              state.relay.lastClientBufB[battler] = nil  -- new cycle: clear previous per-frame re-write data
              local bufAAddr = bufABase + battler * BATTLER_BUFFER_STRIDE
              local bufA = readEWRAMBlock(bufAAddr, BUFFER_READ_SIZE)
              -- GBA-PK also sends bufferB alongside bufferA (L13038-13046)
              local bufBAddr = bufBBase + battler * BATTLER_BUFFER_STRIDE
              local bufB = readEWRAMBlock(bufBAddr, BUFFER_READ_SIZE)

              if bufA and state.sendFn then
                -- Read context variables that CLIENT needs
                local ctx = {}
                if LINK then
                  if LINK.gBattlerAttacker then
                    local ok, v = pcall(readMem8, LINK.gBattlerAttacker)
                    if ok then ctx.attacker = v end
                  end
                  if LINK.gBattlerTarget then
                    local ok, v = pcall(readMem8, LINK.gBattlerTarget)
                    if ok then ctx.target = v end
                  end
                  if LINK.gAbsentBattlerFlags then
                    local ok, v = pcall(readMem8, LINK.gAbsentBattlerFlags)
                    if ok then ctx.absent = v end
                  end
                  if LINK.gEffectBattler then
                    local ok, v = pcall(readMem8, LINK.gEffectBattler)
                    if ok then ctx.effect = v end
                  end
                end

                state.sendFn({
                  type = "duel_buffer_cmd",
                  battler = battler,
                  bufA = bufA,
                  bufB = bufB,
                  ctx = ctx
                })
                state.relay.lastRelayActivityFrame = state.stageTimer
                state.relay.pendingRelay[battler] = true
                state.relay.pendingAck[battler] = nil  -- clear any stale ACK

                if isRemote then
                  -- D5: REMOTE battler — DON'T activate yet, wait for CLIENT ACK
                  -- byte3 stays set → engine stays blocked until ACK arrives (GBA-PK FLAGS.WRITTEN)
                else
                  -- LOCAL battler — activate immediately (HOST's own controller)
                  byte3 = byte3 & ~p2bit
                  byte0 = byte0 | pbit | (1 << (4 + battler))
                end

                if debugOptions.log and (state.stageTimer % 60 == 1 or state.stageTimer <= 5) then
                  console:log(string.format("[Battle] HOST: Sent bufA for battler %d %s (cmd=0x%02X)%s",
                    battler, isRemote and "REMOTE" or "LOCAL", bufA[1] or 0,
                    isRemote and " (waiting ACK)" or " (activated)"))
                end
              end
            end

            -- Phase 1.5 (D5): REMOTE battler — ACK received, now activate controller
            if state.relay.pendingRelay[battler] and isRemote and state.relay.pendingAck[battler] then
              byte3 = byte3 & ~p2bit
              byte0 = byte0 | pbit | (1 << (4 + battler))
              state.relay.pendingAck[battler] = nil
              if debugOptions.log and (state.stageTimer % 60 == 1 or state.stageTimer <= 5) then
                console:log(string.format("[Battle] HOST: ACK received for REMOTE battler %d — controller activated", battler))
              end
            end

            -- Phase 2: Check completion — controller done AND CLIENT responded
            if state.relay.pendingRelay[battler] then
              -- Guard: only check completion if controller has been activated
              -- For REMOTE pre-ACK: byte0 doesn't have pbit/p2bit, skip completion check
              local activated = not isRemote or (byte0 & (pbit | (1 << (4 + battler)))) ~= 0
              if activated then
                local controllerDone = (byte0 & pbit) == 0
                local hasBufB = state.relay.remoteBufferB_queue[battler] ~= nil

                if controllerDone and hasBufB then
                  if isRemote then
                    -- REMOTE battler: write CLIENT's bufferB to memory
                    local bufBAddr = bufBBase + battler * BATTLER_BUFFER_STRIDE
                    writeEWRAMBlock(bufBAddr, state.relay.remoteBufferB_queue[battler])
                    state.relay.lastClientBufB[battler] = state.relay.remoteBufferB_queue[battler]
                  end
                  -- LOCAL battler: don't copy bufferB (HOST's own controller wrote it)

                  -- Clear PLAYERS2 in byte0
                  byte0 = byte0 & ~(1 << (4 + battler))
                  state.relay.pendingRelay[battler] = false
                  state.relay.remoteBufferB_queue[battler] = nil

                  if debugOptions.log and (state.stageTimer % 60 == 1 or state.stageTimer <= 5) then
                    console:log(string.format("[Battle] HOST: bufB done for battler %d %s%s",
                      battler, isRemote and "REMOTE" or "LOCAL", isRemote and " (written)" or " (ACK only)"))
                  end
                elseif controllerDone and not hasBufB then
                  -- Controller done but no bufferB yet — keep PLAYERS2 to signal waiting
                  byte0 = byte0 | (1 << (4 + battler))
                end
              end
            end

            -- Per-frame re-write: persist CLIENT's bufferB for remote battler
            if not state.relay.pendingRelay[battler] and isRemote and state.relay.lastClientBufB[battler] then
              local bufBAddr = bufBBase + battler * BATTLER_BUFFER_STRIDE
              writeEWRAMBlock(bufBAddr, state.relay.lastClientBufB[battler])
            end
          end

        -- ============================================================
        -- CLIENT side
        -- HOST drives ALL battlers. CLIENT processes HOST commands
        -- for ANY battler (not just remote). For battlers the HOST
        -- doesn't relay (HOST's local), CLIENT handles byte3 locally.
        -- ============================================================
        else
          for battler = 0, 1 do
            local pbit = (1 << battler)
            local p2bit = (1 << (4 + battler))

            -- Priority 1: Process HOST command if one is pending
            if state.relay.pendingCmd[battler] and not state.relay.processingCmd[battler] then
              -- Write HOST's bufferA AND bufferB into local memory (GBA-PK L13038-13046)
              -- bufferB carries context from HOST that CLIENT controllers may read
              local bufAAddr = bufABase + battler * BATTLER_BUFFER_STRIDE
              local cmdData = state.relay.pendingCmd[battler]
              writeEWRAMBlock(bufAAddr, cmdData.bufA or cmdData)
              if cmdData.bufB then
                local bufBAddr = bufBBase + battler * BATTLER_BUFFER_STRIDE
                writeEWRAMBlock(bufBAddr, cmdData.bufB)
              end

              -- Write context variables if provided
              local ctx = cmdData.ctx
              if ctx and LINK then
                if ctx.attacker and LINK.gBattlerAttacker then pcall(writeMem8, LINK.gBattlerAttacker, ctx.attacker) end
                if ctx.target and LINK.gBattlerTarget then pcall(writeMem8, LINK.gBattlerTarget, ctx.target) end
                if ctx.absent and LINK.gAbsentBattlerFlags then pcall(writeMem8, LINK.gAbsentBattlerFlags, ctx.absent) end
                if ctx.effect and LINK.gEffectBattler then pcall(writeMem8, LINK.gEffectBattler, ctx.effect) end
              end

              -- D5: Send ACK to HOST — bufferA is written, HOST can activate controller
              if state.sendFn then
                state.sendFn({ type = "duel_buffer_ack", battler = battler })
              end

              -- Set PLAYERS in byte0 to trigger local controller
              byte0 = byte0 | pbit
              -- Clear any byte3 bit for this battler (HOST already sent it)
              byte3 = byte3 & ~p2bit

              state.relay.activeCmd[battler] = state.relay.pendingCmd[battler]  -- keep for per-frame re-write
              state.relay.pendingCmd[battler] = nil
              state.relay.processingCmd[battler] = true

              if debugOptions.log and (state.stageTimer % 60 == 1 or state.stageTimer <= 5) then
                console:log(string.format("[Battle] CLIENT: Processing HOST cmd for battler %d (cmd=0x%02X)",
                  battler, (cmdData.bufA and cmdData.bufA[1]) or 0))
              end

            end
            -- NOTE: No Priority 2 / local byte3 handling. CLIENT is 100% HOST-driven.
            -- Engine sets byte3 → stays blocked (exec flags ≠ 0) → HOST detects on its side
            -- → sends duel_buffer_cmd via TCP → Priority 1 fires → command processed.
            -- HOST will eventually relay the command via TCP (Priority 1).

            -- Per-frame re-write: persist bufferA while controller processes
            if state.relay.processingCmd[battler] and state.relay.activeCmd[battler] then
              local cmdData = state.relay.activeCmd[battler]
              local bufAAddr = bufABase + battler * BATTLER_BUFFER_STRIDE
              writeEWRAMBlock(bufAAddr, cmdData.bufA or cmdData)
              -- Context vars: write ONCE at first frame only (GBA-PK style).
              -- The engine may change gBattlerAttacker/Target during multi-frame commands
              -- (multi-target moves, ability triggers). Per-frame re-write would undo those changes.
              if not state.relay.ctxWritten[battler] then
                local ctx = cmdData.ctx
                if ctx and LINK then
                  if ctx.attacker and LINK.gBattlerAttacker then pcall(writeMem8, LINK.gBattlerAttacker, ctx.attacker) end
                  if ctx.target and LINK.gBattlerTarget then pcall(writeMem8, LINK.gBattlerTarget, ctx.target) end
                  if ctx.absent and LINK.gAbsentBattlerFlags then pcall(writeMem8, LINK.gAbsentBattlerFlags, ctx.absent) end
                  if ctx.effect and LINK.gEffectBattler then pcall(writeMem8, LINK.gEffectBattler, ctx.effect) end
                end
                state.relay.ctxWritten[battler] = true
              end
              -- NOTE: Do NOT re-write bufferB — the controller is actively writing into it
            end

            -- Check if controller finished processing a HOST command
            if state.relay.processingCmd[battler] then
              local controllerDone = (byte0 & pbit) == 0

              if controllerDone then
                -- Read bufferB result and send to HOST
                local bufBAddr = bufBBase + battler * BATTLER_BUFFER_STRIDE
                local bufB = readEWRAMBlock(bufBAddr, BUFFER_READ_SIZE)

                if bufB and state.sendFn then
                  state.sendFn({
                    type = "duel_buffer_resp",
                    battler = battler,
                    bufB = bufB
                  })
                end

                state.relay.processingCmd[battler] = false
                state.relay.activeCmd[battler] = nil  -- clear per-frame re-write data
                state.relay.ctxWritten[battler] = nil -- allow fresh ctx write on next command

                if debugOptions.log and (state.stageTimer % 60 == 1 or state.stageTimer <= 5) then
                  console:log(string.format("[Battle] CLIENT: Sent bufB resp for battler %d", battler))
                end
              end
            end
          end

          -- NOTE: byte3 is NOT cleared here. CLIENT leaves byte3 intact so the engine
          -- stays blocked (exec flags ≠ 0) until HOST relays each command via TCP.
          -- Priority 1 clears byte3 per-bit when HOST command arrives (GBA-PK model).
        end

        -- Write exec flags back to memory
        pcall(writeMem8, efAddr + 0, byte0)
        pcall(writeMem8, efAddr + 1, byte1)
        pcall(writeMem8, efAddr + 2, byte2)
        pcall(writeMem8, efAddr + 3, byte3)
      end
    end

    -- ================================================================
    -- Periodic screenshots (every 300 frames)
    -- ================================================================
    if state.stageTimer % 300 == 0 and state.stageTimer > 1 then
      captureScreenshot(string.format("%sf%04d.png", state.relay.screenshotDir or "pvp_screenshots/", state.stageTimer))
    end

    -- ================================================================
    -- BATTLE END DETECTION
    -- ================================================================
    -- Gate reduced from 120→30 frames: callback2 detection is reliable (no false positives),
    -- and shorter gate means less time where maintainLinkState runs after engine exited.
    if state.relay.introComplete and state.stageTimer > 30 and Battle.detectBattleEnd(inBattle) then
      state.cachedOutcome = Battle.readOutcomeRaw()
      state.stage = STAGE.ENDING
      state.stageTimer = 0
      state.stageClock = os.clock()
      console:log(string.format("[Battle] Battle end detected, cached outcome: %s", state.cachedOutcome or "nil"))
      return
    end

    -- ================================================================
    -- Optional telemetry (throttled, compact payload)
    -- ================================================================
    local sendTelemetryNow = debugOptions.telemetry and (state.stageTimer <= 2 or state.stageTimer % 120 == 0)
    if sendTelemetryNow and state.sendFn then
      local pendingCount = 0
      for _ in pairs(state.relay.pendingRelay) do pendingCount = pendingCount + 1 end
      local procCount = 0
      for _ in pairs(state.relay.processingCmd) do procCount = procCount + 1 end

      local diagData = {
        type = "duel_stage",
        stage = state.stageTimer,
        intro = state.relay.introComplete and 1 or 0,
        master = state.isMaster and 1 or 0,
        pendRelay = pendingCount,
        procCmd = procCount,
        turnPhase = state.relay.turnPhase,
      }

      if currentBmf and currentBmf ~= 0 then
        diagData.bmf = string.format("0x%08X", currentBmf)
      end
      if config and config.warp then
        local okCb2, cb2val = pcall(readMem32, config.warp.callback2Addr)
        if okCb2 then
          diagData.cb2 = string.format("0x%08X", cb2val)
        end
      end

      state.sendFn(diagData)
    end

    -- NOTE: Relay timeout (10s) and safety timeout (1min) REMOVED.
    -- These caused premature battle exits during normal multi-turn PvP
    -- (player thinking >10s or battle lasting >1min).
    -- Battle exit is now handled by: natural engine outcome, FF/forfeit, disconnect detection, or ping timeout.
    return
  end

  -- === STAGE: ENDING ===
  -- 3 phases:
  --   Phase 1 (frames 1-30):  Inject 0x37 exit cmd + KEEP LINK active for clean engine exit
  --   Phase 2 (frames 31-90): Clear link flags + exec flags, let engine transition to overworld
  --   Phase 3 (frame 90 or gameCleanupDone): Restore patches, force callback2 if needed
  if state.stage == STAGE.ENDING then
    local gameCleanupDone = false
    if config and config.warp then
      local okCb, cb2 = pcall(readMem32, config.warp.callback2Addr)
      if okCb then
        if cb2 == config.warp.cb2Overworld then
          gameCleanupDone = true
        elseif LINK and LINK.CB2_ReturnToField and cb2 == LINK.CB2_ReturnToField then
          gameCleanupDone = true
        end
      end
    end

    -- Phase 1 (first 30 frames): inject 0x37 exit cmd, do NOT maintain link state
    -- (gReceivedRemoteLinkPlayers must stay 0 so ReturnFromBattleToOverworld can proceed)
    if state.stageTimer <= 30 then
      -- Inject 0x37 into bufferA
      local bufABase, _ = getBufferAddresses()
      if bufABase then pcall(writeMem8, bufABase, CMD_GET_AWAY_EXIT) end

      -- Set exec flag for battler 0 ONCE (first frame) to trigger controller processing 0x37
      if state.stageTimer == 1 and LINK and LINK.gBattleControllerExecFlags then
        pcall(writeMem8, LINK.gBattleControllerExecFlags, PLAYERS[1])
      end
    end

    -- Phase 2 (frame 31): clear link flags + exec flags so engine can advance to exit sequence
    if state.stageTimer == 31 then
      -- Clear exec flags — BattleMainCB2 needs exec==0 to proceed to battle exit
      if LINK and LINK.gBattleControllerExecFlags then
        pcall(writeMem32, LINK.gBattleControllerExecFlags, 0)
      end
      -- Clear LINK flags — engine had 30 frames to process exit via link path
      if ADDRESSES and ADDRESSES.gBattleTypeFlags then
        local okF, flags = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
        if okF and flags then
          local clearMask = BATTLE_TYPE_LINK | BATTLE_TYPE_LINK_IN_BATTLE | BATTLE_TYPE_IS_MASTER | BATTLE_TYPE_RECORDED
          pcall(writeMem32, ADDRESSES.gBattleTypeFlags, flags & ~clearMask)
        end
      end
      if LINK and LINK.gReceivedRemoteLinkPlayers then
        pcall(writeMem8, LINK.gReceivedRemoteLinkPlayers, 0)
      end
      console:log("[Battle] ENDING phase 2: link flags + exec flags cleared")
    end

    -- Phase 3: cleanup when engine returned to overworld OR timeout (90 frames = 1.5s)
    if gameCleanupDone or state.stageTimer > 90 then
      Battle.restorePatches()

      -- CRITICAL: Force callback2 to overworld if engine didn't do it naturally
      -- Without this, callback2 stays at BattleMainCB2 with restored ROM patches = black screen
      if not gameCleanupDone and config and config.warp then
        local returnCb = (LINK and LINK.CB2_ReturnToField) or config.warp.cb2Overworld
        if returnCb then
          pcall(writeMem32, config.warp.callback2Addr, returnCb)
          local okCb2, stuckCb2 = pcall(readMem32, config.warp.callback2Addr)
          console:log(string.format("[Battle] FORCED callback2 = 0x%08X (was stuck, timeout at %d frames)",
            returnCb, state.stageTimer))
        end
      end

      -- Restore callback1 if we saved it
      if state.savedCallback1 and config and config.warp then
        local gMainBase = config.warp.callback2Addr - 4
        pcall(writeMem32, gMainBase + 0x00, state.savedCallback1)
        console:log(string.format("[Battle] Restored callback1 = 0x%08X", state.savedCallback1))
      end

      -- Post-battle link state cleanup (GBA-PK stages 8-9)
      -- Clear sBlockSend (10 bytes) — prevent stale send buffer data
      if LINK and LINK.sBlockSend then
        for i = 0, 9 do pcall(writeMem8, LINK.sBlockSend + i, 0) end
      end
      -- Clear gLinkCallback — stop link callback from firing post-battle
      if LINK and LINK.gLinkCallback then
        pcall(writeMem32, LINK.gLinkCallback, 0)
      end
      -- Clear script engine (GBA-PK RemoveScriptFromMemory)
      loadscriptClear()
      -- Ensure savedCallback points to overworld for clean return
      if config and config.warp then
        local gMainBase = config.warp.callback2Addr - 4
        local savedCbOffset = (LINK and LINK.savedCallbackOffset) or 0x08
        local returnCb = (LINK and LINK.CB2_ReturnToField) or config.warp.cb2Overworld
        if returnCb then
          pcall(writeMem32, gMainBase + savedCbOffset, returnCb)
        end
      end

      -- Ensure BATTLE_TYPE_LINK is cleared (belt-and-suspenders for phase 2)
      if ADDRESSES and ADDRESSES.gBattleTypeFlags then
        local okF, flags = pcall(readMem32, ADDRESSES.gBattleTypeFlags)
        if okF and flags then
          local clearMask = BATTLE_TYPE_LINK | BATTLE_TYPE_LINK_IN_BATTLE | BATTLE_TYPE_IS_MASTER | BATTLE_TYPE_RECORDED
          local newFlags = flags & ~clearMask
          if newFlags ~= flags then
            pcall(writeMem32, ADDRESSES.gBattleTypeFlags, newFlags)
          end
        end
      end

      -- Clear cached link player data
      cachedLocalName = nil
      cachedLocalGender = 0
      cachedLocalTrainerId = 0
      cachedOpponentName = nil
      cachedOpponentGender = 0
      cachedOpponentTrainerId = 0

      state.stage = STAGE.DONE
      state.stageTimer = 0
      console:log(string.format("[Battle] ENDING → DONE (natural=%s, frames=%d)",
        tostring(gameCleanupDone), state.stageTimer))
    end
    return
  end
end

-- ============================================================
-- Battle End Detection
-- ============================================================

function Battle.detectBattleEnd(inBattle)
  -- Method 1: inBattle 1->0
  if state.battleDetected and inBattle == 0 then
    console:log("[Battle] End: inBattle 1->0")
    return true
  end

  -- Method 2: callback2 changed to CB2_Overworld or CB2_ReturnToField
  if state.battleDetected and config and config.warp then
    local ok, cb2 = pcall(readMem32, config.warp.callback2Addr)
    if ok then
      if cb2 == config.warp.cb2Overworld then
        console:log("[Battle] End: callback2 = CB2_Overworld")
        return true
      end
      if LINK and LINK.CB2_ReturnToField and cb2 == LINK.CB2_ReturnToField then
        console:log("[Battle] End: callback2 = CB2_ReturnToField")
        return true
      end
    end
  end

  return false
end

-- ============================================================
-- Status Queries
-- ============================================================

function Battle.isActive()
  return state.stage ~= STAGE.IDLE and state.stage ~= STAGE.DONE
end

function Battle.isMasterPlayer()
  return state.isMaster
end

function Battle.isFinished()
  return state.stage == STAGE.DONE
end

function Battle.getStage()
  return state.stage
end

-- Read outcome directly from memory (call at detection time before cleanup)
function Battle.readOutcomeRaw()
  -- Method 1: gBattleOutcome
  if ADDRESSES and ADDRESSES.gBattleOutcome then
    local ok, outcome = pcall(readMem8, ADDRESSES.gBattleOutcome)
    if ok and outcome ~= 0 then
      local base = outcome & 0x7F  -- mask B_OUTCOME_LINK_BATTLE_RAN (0x80)
      if base == 1 then return "win"
      elseif base == 2 then return "lose"
      elseif base == 3 then return "draw"
      elseif base == 4 or base == 7 then return "flee"
      elseif base == 9 then return "forfeit"
      end
    end
  end

  -- Method 2: HP comparison (use localPartyBackup for player HP if available,
  -- since gPlayerParty may have been overwritten during battle cleanup)
  if ADDRESSES and ADDRESSES.gPlayerParty and ADDRESSES.gEnemyParty then
    local playerHP, enemyHP = 0, 0
    for i = 0, 5 do
      local ok1, hp1 = pcall(readMem16, ADDRESSES.gPlayerParty + i * POKEMON_SIZE + POKEMON_HP_OFFSET)
      if ok1 then playerHP = playerHP + hp1 end
      local ok2, hp2 = pcall(readMem16, ADDRESSES.gEnemyParty + i * POKEMON_SIZE + POKEMON_HP_OFFSET)
      if ok2 then enemyHP = enemyHP + hp2 end
    end
    if playerHP == 0 then return "lose" end
    if enemyHP == 0 then return "win" end
  end

  return "completed"
end

function Battle.getOutcome()
  -- Use cached outcome (captured at detection time, before DMA corruption)
  if state.cachedOutcome then return state.cachedOutcome end
  -- Fallback to live read
  return Battle.readOutcomeRaw()
end


function Battle.forceEnd(outcome)
  state.cachedOutcome = outcome or state.cachedOutcome
  if state.stage == STAGE.MAIN_LOOP then
    -- Don't transition immediately — inject 0x37 every frame for 30f
    state.forceEndPending = true
    state.forceEndFrame = state.stageTimer
    console:log(string.format("[Battle] Force-exit initiated: outcome=%s", outcome or "?"))
  elseif state.stage == STAGE.STARTING then
    state.stage = STAGE.DONE
    state.stageTimer = 0
  end
end

function Battle.getLocalPlayerInfo()
  if not LINK or not LINK.gSaveBlock2Ptr then return nil end
  if not cachedLocalName then initLocalLinkPlayer() end
  if not cachedLocalName then return nil end
  return { name = cachedLocalName, gender = cachedLocalGender, trainerId = cachedLocalTrainerId }
end

function Battle.setOpponentInfo(name, gender, trainerId)
  cachedOpponentName = name
  cachedOpponentGender = gender or 0
  cachedOpponentTrainerId = trainerId or 0
  if name then
    console:log(string.format("[Battle] Opponent info set: gender=%d trainerId=0x%08X", cachedOpponentGender, cachedOpponentTrainerId))
  end
end

function Battle.reset()
  if #state.romPatches > 0 or #state.ewramPatches > 0 then
    Battle.restorePatches()
  end

  -- Reset buffer address cache
  cachedBufABase = nil
  cachedBufBBase = nil
  bufferAddressesVerified = false

  -- Reset cached link player data
  cachedLocalName = nil
  cachedLocalGender = 0
  cachedLocalTrainerId = 0
  cachedOpponentName = nil
  cachedOpponentGender = 0
  cachedOpponentTrainerId = 0

  state.stage = STAGE.IDLE
  state.isMaster = false
  state.battleEntryMethod = "direct_write"
  state.opponentParty = nil
  state.prevInBattle = 0
  state.battleDetected = false
  state.battleCallbackSeen = false
  state.cachedOutcome = nil
  state.forceEndPending = false
  state.forceEndFrame = 0
  state.frameCounter = 0
  state.stageTimer = 0
  state.stageClock = 0
  state.remoteBuffers = {}
  state.romPatches = {}
  state.ewramPatches = {}
  state.battleFlags = nil
  state.isLinkBattle = false
  state.remoteReady = false
  state.savedCallback1 = nil
  state.localPartyBackup = nil
  state.battleMainReached = false

  -- Reset relay state
  state.relay.localSlot = 0
  state.relay.remoteSlot = 1
  state.relay.localBattler = 1
  state.relay.remoteBattler = 2
  state.relay.waitingStatus = 0
  state.relay.bufferID = 0
  state.relay.sendID = 0
  state.relay.remoteWaitingStatus = 0
  state.relay.remoteBufferID = 0
  state.relay.remoteSendID = 0
  state.relay.remoteBattleflags = { 0, 0, 0, 0 }
  state.relay.remoteDataReceived = false
  state.relay.remoteBufferA = nil
  state.relay.remoteBufferB = nil
  state.relay.remoteAttacker = 0
  state.relay.remoteTarget = 0
  state.relay.remoteAbsent = 0
  state.relay.remoteEffect = 0
  state.relay.commAdvanced = false
  state.relay.commReady = false
  -- Action sync state (kept for backup)
  state.relay.localReady = false
  state.relay.remoteReady = false
  state.relay.remoteAction = nil
  state.relay.localAction = nil
  state.relay.lastTurn = -1
  state.relay.introComplete = false
  state.relay.remoteMainloopReady = false
  state.relay.engineBlocked = true
  state.relay.turnPhase = "idle"
  state.relay.lastComm0 = 0
  state.relay.savedBattleStruct = nil
  state.relay.savedBattleResources = nil
  -- GBA-PK buffer relay state (new)
  state.relay.battleflags = { 0, 0, 0, 0 }
  state.relay.pendingRelay = {}
  state.relay.pendingCmd = {}
  state.relay.processingCmd = {}
  state.relay.remoteBufferB_queue = {}
  state.relay.activeCmd = {}             -- CLIENT: per-frame re-write data during processing
  state.relay.lastClientBufB = {}        -- HOST: per-frame re-write of CLIENT's bufferB
  state.relay.ctxWritten = {}            -- CLIENT: context vars written once per command (not per-frame)
  state.relay.lastRelayActivityFrame = 0
  screenshotState.count = 0
  screenshotState.lastFrame = -999999
end

Battle.STAGE = STAGE

return Battle
