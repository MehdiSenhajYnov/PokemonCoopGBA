--[[
  Battle Module — PvP Combat Management

  Handles:
  - Party data reading and injection
  - Battle triggering via gBattleTypeFlags
  - AI choice interception and replacement
  - RNG synchronization
  - Battle outcome detection

  This module is used in conjunction with the duel warp system.
  After both players warp to the duel room:
  1. Exchange party data via network
  2. Inject opponent's party into gEnemyParty
  3. Trigger battle with BATTLE_TYPE_SECRET_BASE
  4. Intercept AI decisions and replace with real player choices
  5. Sync RNG each turn to ensure identical outcomes
  6. Detect battle end and return to origin

  IMPORTANT: The battle addresses must be scanned and configured in
  config/run_and_bun.lua before this module will work.
]]

local Battle = {}

-- Configuration (loaded from game config)
local config = nil
local ADDRESSES = nil
local HAL = nil

-- Battle type flags (loaded from config.battleFlags if available, fallback to hardcoded)
local BATTLE_TYPE_DOUBLE = 0x00000001
local BATTLE_TYPE_LINK = 0x00000002
local BATTLE_TYPE_IS_MASTER = 0x00000004
local BATTLE_TYPE_TRAINER = 0x00000008
local BATTLE_TYPE_FIRST_BATTLE = 0x00000010
local BATTLE_TYPE_RECORDED = 0x01000000
local BATTLE_TYPE_SECRET_BASE = 0x08000000

-- Special trainer ID that preserves gEnemyParty
local TRAINER_SECRET_BASE = 1024

-- Party structure constants (defaults, overridden from config.pokemon if available)
local PARTY_SIZE = 600      -- 6 Pokemon x 100 bytes each (FULL_PARTY_BYTES)
local POKEMON_SIZE = 100    -- sizeof(struct Pokemon) = BoxPokemon(80) + stats(20)
local POKEMON_HP_OFFSET = 86  -- +0x56: u16 current HP (decimal for clarity)

-- Battle state
local battleState = {
  active = false,
  isMaster = false,
  opponentParty = nil,      -- 600 bytes of opponent's party
  localChoice = nil,        -- Our choice this turn
  remoteChoice = nil,       -- Choice received from opponent
  waitingForRemote = false, -- Waiting for opponent's choice
  prevExecFlags = 0,        -- Previous gBattleControllerExecFlags value
  turnCount = 0,
  originPos = nil,          -- Position to return to after battle
  prevInBattle = 0,         -- Previous inBattle value for transition detection
  battleDetected = false,   -- True once inBattle 0→1 seen (actual combat running)
}

--[[
  Initialize the battle module with game configuration.
  @param gameConfig table containing battle addresses
]]
function Battle.init(gameConfig, halModule)
  config = gameConfig
  HAL = halModule
  if config and config.battle then
    ADDRESSES = config.battle
    -- Load pokemon struct constants from config if available
    if config.pokemon then
      PARTY_SIZE = config.pokemon.FULL_PARTY_BYTES or PARTY_SIZE
      POKEMON_SIZE = config.pokemon.PARTY_MON_SIZE or POKEMON_SIZE
      POKEMON_HP_OFFSET = config.pokemon.HP_OFFSET or POKEMON_HP_OFFSET
    end
    -- Load battle flag constants from config if available
    if config.battleFlags then
      BATTLE_TYPE_TRAINER = config.battleFlags.TRAINER or BATTLE_TYPE_TRAINER
      BATTLE_TYPE_SECRET_BASE = config.battleFlags.SECRET_BASE or BATTLE_TYPE_SECRET_BASE
      BATTLE_TYPE_IS_MASTER = config.battleFlags.IS_MASTER or BATTLE_TYPE_IS_MASTER
    end
    console:log("[Battle] Initialized with battle config")
    console:log(string.format("[Battle] gPlayerParty=0x%08X gEnemyParty=0x%08X",
      ADDRESSES.gPlayerParty or 0, ADDRESSES.gEnemyParty or 0))
  else
    console:log("[Battle] WARNING: No battle config available")
  end
end

--[[
  Check if battle module is properly configured.
  @return boolean
]]
function Battle.isConfigured()
  return ADDRESSES ~= nil
    and ADDRESSES.gPlayerParty ~= nil
    and ADDRESSES.gEnemyParty ~= nil
    and ADDRESSES.gBattleTypeFlags ~= nil
end

--[[
  Convert absolute EWRAM address to WRAM offset.
  @param address absolute address (0x02XXXXXX)
  @return offset for emu.memory.wram
]]
local function toWRAMOffset(address)
  return address - 0x02000000
end

--[[
  Convert absolute IWRAM address to IWRAM offset.
  @param address absolute address (0x03XXXXXX)
  @return offset for emu.memory.iwram
]]
local function toIWRAMOffset(address)
  return address - 0x03000000
end

--[[
  Read local player's party data (600 bytes).
  @return table of 600 bytes, or nil on error
]]
function Battle.readLocalParty()
  if not ADDRESSES or not ADDRESSES.gPlayerParty then
    console:log("[Battle] ERROR: gPlayerParty address not configured")
    return nil
  end

  local data = {}
  local baseOffset = toWRAMOffset(ADDRESSES.gPlayerParty)

  local ok = pcall(function()
    for i = 0, PARTY_SIZE - 1 do
      data[i + 1] = emu.memory.wram:read8(baseOffset + i)
    end
  end)

  if ok and #data == PARTY_SIZE then
    console:log("[Battle] Local party read (600 bytes)")
    return data
  end

  console:log("[Battle] ERROR: Failed to read local party")
  return nil
end

--[[
  Inject opponent's party into gEnemyParty.
  @param partyData table of 600 bytes
  @return boolean success
]]
function Battle.injectEnemyParty(partyData)
  if not ADDRESSES or not ADDRESSES.gEnemyParty then
    console:log("[Battle] ERROR: gEnemyParty address not configured")
    return false
  end

  if not partyData or #partyData ~= PARTY_SIZE then
    console:log("[Battle] ERROR: Invalid party data (expected 600 bytes)")
    return false
  end

  local baseOffset = toWRAMOffset(ADDRESSES.gEnemyParty)

  local ok = pcall(function()
    for i = 1, PARTY_SIZE do
      emu.memory.wram:write8(baseOffset + i - 1, partyData[i])
    end
  end)

  if ok then
    console:log("[Battle] Enemy party injected (600 bytes)")
    battleState.opponentParty = partyData
    return true
  end

  console:log("[Battle] ERROR: Failed to inject enemy party")
  return false
end

--[[
  Start a PvP battle.
  Prerequisites: gEnemyParty already injected, golden state available.

  @param isMaster boolean - true if this player is the RNG master
  @param originPos table - {x, y, mapGroup, mapId} to return to after battle
  @return boolean success
]]
function Battle.startBattle(isMaster, originPos)
  if not Battle.isConfigured() then
    console:log("[Battle] ERROR: Battle module not configured")
    return false
  end

  battleState.isMaster = isMaster
  battleState.active = true
  battleState.turnCount = 0
  battleState.originPos = originPos
  battleState.waitingForRemote = false
  battleState.localChoice = nil
  battleState.remoteChoice = nil
  battleState.prevExecFlags = 0

  -- Set gBattleTypeFlags = TRAINER | SECRET_BASE (and optionally IS_MASTER)
  local flags = BATTLE_TYPE_TRAINER + BATTLE_TYPE_SECRET_BASE
  if isMaster then
    flags = flags + BATTLE_TYPE_IS_MASTER
  end

  local ok1 = pcall(emu.memory.wram.write32, emu.memory.wram,
    toWRAMOffset(ADDRESSES.gBattleTypeFlags), flags)

  if not ok1 then
    console:log("[Battle] ERROR: Failed to write gBattleTypeFlags")
    battleState.active = false
    return false
  end

  console:log(string.format("[Battle] Battle flags written: 0x%08X master=%s",
    flags, tostring(isMaster)))

  -- Trigger battle via CB2_LoadMap (detects battle flags and loads battle scene)
  if HAL then
    HAL.blankScreen()
    HAL.triggerMapLoad()
    console:log("[Battle] triggerMapLoad called — CB2_LoadMap will start battle")
  else
    console:log("[Battle] WARNING: HAL not available — cannot trigger battle")
    battleState.active = false
    return false
  end

  return true
end

--[[
  Called every frame during battle.
  Detects AI decisions and intercepts them.
]]
function Battle.tick()
  if not battleState.active then return end
  if not ADDRESSES or not ADDRESSES.gBattleControllerExecFlags then return end

  -- Read current exec flags
  local ok, flags = pcall(emu.memory.wram.read32, emu.memory.wram,
    toWRAMOffset(ADDRESSES.gBattleControllerExecFlags))
  if not ok then return end

  local opponentBit = 0x02  -- Bit 1 = opponent controller (battler index 1)

  -- Detect: AI just decided (bit went from 1 to 0)
  local prevHadBit = (battleState.prevExecFlags & opponentBit) ~= 0
  local currHasBit = (flags & opponentBit) ~= 0

  if prevHadBit and not currHasBit then
    -- AI decided! Freeze by putting the bit back
    pcall(emu.memory.wram.write32, emu.memory.wram,
      toWRAMOffset(ADDRESSES.gBattleControllerExecFlags), flags | opponentBit)

    battleState.waitingForRemote = true
    console:log("[Battle] AI decided — waiting for remote choice")
  end

  -- If we have the remote choice, inject it
  if battleState.waitingForRemote and battleState.remoteChoice then
    Battle.injectRemoteChoice(battleState.remoteChoice)
    battleState.remoteChoice = nil
    battleState.waitingForRemote = false
    battleState.turnCount = battleState.turnCount + 1
  end

  battleState.prevExecFlags = flags
end

--[[
  Inject remote player's choice into gBattleBufferB[opponent].
  @param choice table {action="move"|"switch", slot/switchIndex, target}
]]
function Battle.injectRemoteChoice(choice)
  if not ADDRESSES or not ADDRESSES.gBattleBufferB then
    console:log("[Battle] ERROR: gBattleBufferB not configured")
    return
  end

  -- Opponent's buffer is at gBattleBufferB + 0x200 (battler 1, 512 bytes per buffer)
  local bufferOffset = toWRAMOffset(ADDRESSES.gBattleBufferB) + 0x200

  if choice.action == "move" then
    -- CONTROLLER_TWORETURNVALUES command for move selection
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 0, 0x22)
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 1, 10)  -- action type
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 2, choice.slot or 0)
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 3, choice.target or 0)

  elseif choice.action == "switch" then
    -- CONTROLLER_CHOSENMONRETURNVALUE command for switch
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 0, 0x23)
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 1, choice.switchIndex or 0)
  end

  -- Unfreeze: clear opponent bit
  local ok, flags = pcall(emu.memory.wram.read32, emu.memory.wram,
    toWRAMOffset(ADDRESSES.gBattleControllerExecFlags))
  if ok then
    pcall(emu.memory.wram.write32, emu.memory.wram,
      toWRAMOffset(ADDRESSES.gBattleControllerExecFlags), flags & ~0x02)
  end

  console:log(string.format("[Battle] Injected remote choice: %s", choice.action))
end

--[[
  Capture local player's choice from gBattleBufferB[player].
  @return table {action, slot, target} or {action, switchIndex} or nil
]]
function Battle.captureLocalChoice()
  if not ADDRESSES or not ADDRESSES.gBattleBufferB then
    return nil
  end

  -- Player's buffer is at gBattleBufferB + 0x000 (battler 0)
  local bufferOffset = toWRAMOffset(ADDRESSES.gBattleBufferB)

  local ok, cmd = pcall(emu.memory.wram.read8, emu.memory.wram, bufferOffset + 0)
  if not ok then return nil end

  if cmd == 0x22 then  -- CONTROLLER_TWORETURNVALUES (move)
    local slot = emu.memory.wram:read8(bufferOffset + 2)
    local target = emu.memory.wram:read8(bufferOffset + 3)
    return { action = "move", slot = slot, target = target }

  elseif cmd == 0x23 then  -- CONTROLLER_CHOSENMONRETURNVALUE (switch)
    local switchIndex = emu.memory.wram:read8(bufferOffset + 1)
    return { action = "switch", switchIndex = switchIndex }
  end

  return nil
end

--[[
  Check if local player has made their choice this turn.
  @return boolean
]]
function Battle.hasPlayerChosen()
  if not ADDRESSES or not ADDRESSES.gBattleControllerExecFlags then
    return false
  end

  local ok, flags = pcall(emu.memory.wram.read32, emu.memory.wram,
    toWRAMOffset(ADDRESSES.gBattleControllerExecFlags))
  if not ok then return false end

  -- Player bit (bit 0) cleared = player has chosen
  local playerBit = 0x01
  return (flags & playerBit) == 0
end

--[[
  Set the remote choice received from network.
  @param choice table {action, slot/switchIndex, target}
]]
function Battle.setRemoteChoice(choice)
  battleState.remoteChoice = choice
end

--[[
  Read the current RNG value.
  @return u32 RNG value
]]
function Battle.readRng()
  if not ADDRESSES or not ADDRESSES.gRngValue then
    return 0
  end

  local addr = ADDRESSES.gRngValue
  local ok, val

  if addr >= 0x03000000 and addr < 0x03008000 then
    ok, val = pcall(emu.memory.iwram.read32, emu.memory.iwram, toIWRAMOffset(addr))
  else
    ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, toWRAMOffset(addr))
  end

  if ok then return val end
  return 0
end

--[[
  Write RNG value for synchronization.
  @param value u32 RNG value
]]
function Battle.writeRng(value)
  if not ADDRESSES or not ADDRESSES.gRngValue then
    return
  end

  local addr = ADDRESSES.gRngValue

  if addr >= 0x03000000 and addr < 0x03008000 then
    pcall(emu.memory.iwram.write32, emu.memory.iwram, toIWRAMOffset(addr), value)
  else
    pcall(emu.memory.wram.write32, emu.memory.wram, toWRAMOffset(addr), value)
  end
end

--[[
  Called when receiving RNG sync from network (master -> slave).
  @param rngValue u32 RNG value from master
]]
function Battle.onRngSync(rngValue)
  if not battleState.isMaster then
    Battle.writeRng(rngValue)
    console:log(string.format("[Battle] RNG synced: 0x%08X", rngValue))
  end
end

--[[
  Check if we're waiting for remote choice.
  @return boolean
]]
function Battle.isWaitingForRemote()
  return battleState.waitingForRemote
end

--[[
  Check if this is a new turn (for RNG sync timing).
  Based on turnCount changing.
  @return boolean
]]
function Battle.isNewTurn()
  -- This would need more sophisticated detection
  -- For now, we sync RNG when we inject a remote choice
  return false
end

--[[
  Check if battle is active.
  @return boolean
]]
function Battle.isActive()
  return battleState.active
end

--[[
  Check if this player is the master.
  @return boolean
]]
function Battle.isMaster()
  return battleState.isMaster
end

--[[
  Check if battle has finished.
  Uses transition tracking: battle is finished when inBattle goes from 1→0.
  @return boolean
]]
function Battle.isFinished()
  if not battleState.active then return false end

  -- Method 1: Check gBattleOutcome (if available)
  if ADDRESSES and ADDRESSES.gBattleOutcome then
    local ok, outcome = pcall(emu.memory.wram.read8, emu.memory.wram,
      toWRAMOffset(ADDRESSES.gBattleOutcome))
    if ok and outcome ~= 0 then
      return true
    end
  end

  -- Method 2: Transition tracking on gMain.inBattle
  -- Only finished if we SAW inBattle=1 (battle started) and now it's 0 (battle ended)
  if ADDRESSES and ADDRESSES.gMainInBattle then
    local ok, inBattle = pcall(emu.memory.wram.read8, emu.memory.wram,
      toWRAMOffset(ADDRESSES.gMainInBattle))
    if ok then
      -- Detect 0→1: battle actually started
      if battleState.prevInBattle == 0 and inBattle == 1 then
        battleState.battleDetected = true
        console:log("[Battle] inBattle 0→1: combat is running")
      end
      -- Detect 1→0: battle ended (only if we saw it start)
      if battleState.battleDetected and battleState.prevInBattle == 1 and inBattle == 0 then
        console:log("[Battle] inBattle 1→0: combat finished")
        return true
      end
      battleState.prevInBattle = inBattle
    end
  end

  return false
end

--[[
  Get battle outcome.
  @return string "win", "lose", "flee", "completed", or nil
]]
function Battle.getOutcome()
  -- Method 1: Use gBattleOutcome if available
  if ADDRESSES and ADDRESSES.gBattleOutcome then
    local ok, outcome = pcall(emu.memory.wram.read8, emu.memory.wram,
      toWRAMOffset(ADDRESSES.gBattleOutcome))
    if ok and outcome ~= 0 then
      if outcome == 1 then return "win"
      elseif outcome == 2 then return "lose"
      elseif outcome == 7 then return "flee"
      end
    end
  end

  -- Method 2: Fallback — check HP of both parties for PvP outcome
  if ADDRESSES and ADDRESSES.gPlayerParty and ADDRESSES.gEnemyParty then
    local playerHP = 0
    local enemyHP = 0
    local playerBase = toWRAMOffset(ADDRESSES.gPlayerParty)
    local enemyBase = toWRAMOffset(ADDRESSES.gEnemyParty)
    for i = 0, 5 do
      local ok1, hp1 = pcall(emu.memory.wram.read16, emu.memory.wram,
        playerBase + i * POKEMON_SIZE + POKEMON_HP_OFFSET)
      if ok1 then playerHP = playerHP + hp1 end
      local ok2, hp2 = pcall(emu.memory.wram.read16, emu.memory.wram,
        enemyBase + i * POKEMON_SIZE + POKEMON_HP_OFFSET)
      if ok2 then enemyHP = enemyHP + hp2 end
    end
    if playerHP == 0 then
      return "lose"
    elseif enemyHP == 0 then
      return "win"
    end
  end

  -- Final fallback: battle completed but outcome unknown
  return "completed"
end

--[[
  Get the origin position (for returning after battle).
  @return table {x, y, mapGroup, mapId} or nil
]]
function Battle.getOriginPos()
  return battleState.originPos
end

--[[
  Get turn count.
  @return number
]]
function Battle.getTurnCount()
  return battleState.turnCount
end

--[[
  Reset the battle module state.
]]
function Battle.reset()
  battleState.active = false
  battleState.isMaster = false
  battleState.opponentParty = nil
  battleState.localChoice = nil
  battleState.remoteChoice = nil
  battleState.waitingForRemote = false
  battleState.prevExecFlags = 0
  battleState.turnCount = 0
  battleState.originPos = nil
  battleState.prevInBattle = 0
  battleState.battleDetected = false
end

return Battle
