--[[
  Battle Address Scanner for Run & Bun

  This script helps find battle-related memory addresses in Run & Bun ROM hack.
  Run this in mGBA's Lua console to scan for addresses.

  USAGE:
  1. Load the script in mGBA (Tools > Scripting > Load Script)
  2. Follow the instructions in the console
  3. Record the addresses found

  Reference addresses from vanilla Emerald US:
  - gPlayerParty: 0x020244EC
  - gEnemyParty: 0x02024744
  - gBattleTypeFlags: 0x02022FEC
  - gTrainerBattleOpponent_A: 0x02038BCA
  - gBattleControllerExecFlags: 0x02024068
  - gBattleBufferB: 0x02023864
  - gRngValue: 0x03005D80 (IWRAM)

  Run & Bun delta observed: ~+0x878 from vanilla for player position
  (0x020244EC vs 0x02024CBC)
]]

local EWRAM_START = 0x02000000
local EWRAM_SIZE = 0x40000
local IWRAM_START = 0x03000000
local IWRAM_SIZE = 0x8000

-- Results storage
local results = {}

--[[
  Scan EWRAM for a 32-bit value
  @param target u32 value to search for
  @return table of matching absolute addresses
]]
local function scan32(target)
  local matches = {}
  console:log(string.format("Scanning EWRAM for 0x%08X...", target))
  for offset = 0, EWRAM_SIZE - 4, 4 do
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  console:log(string.format("Found %d matches", #matches))
  return matches
end

--[[
  Scan EWRAM for a 16-bit value
  @param target u16 value to search for
  @return table of matching absolute addresses
]]
local function scan16(target)
  local matches = {}
  console:log(string.format("Scanning EWRAM for 0x%04X...", target))
  for offset = 0, EWRAM_SIZE - 2, 2 do
    local ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  console:log(string.format("Found %d matches", #matches))
  return matches
end

--[[
  Scan EWRAM for an 8-bit value
  @param target u8 value to search for
  @return table of matching absolute addresses
]]
local function scan8(target)
  local matches = {}
  console:log(string.format("Scanning EWRAM for 0x%02X...", target))
  for offset = 0, EWRAM_SIZE - 1 do
    local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  console:log(string.format("Found %d matches", #matches))
  return matches
end

--[[
  Scan IWRAM for a 32-bit value
  @param target u32 value to search for
  @return table of matching absolute addresses
]]
local function scanIWRAM32(target)
  local matches = {}
  console:log(string.format("Scanning IWRAM for 0x%08X...", target))
  for offset = 0, IWRAM_SIZE - 4, 4 do
    local ok, val = pcall(emu.memory.iwram.read32, emu.memory.iwram, offset)
    if ok and val == target then
      matches[#matches + 1] = IWRAM_START + offset
    end
  end
  console:log(string.format("Found %d matches", #matches))
  return matches
end

--[[
  Rescan: keep only addresses that still match the new value
  @param candidates table of addresses from previous scan
  @param target new value to check
  @param size read size (1, 2, or 4 bytes)
  @return filtered table of addresses
]]
local function rescan(candidates, target, size)
  local kept = {}
  console:log(string.format("Rescanning %d candidates for new value...", #candidates))
  for _, addr in ipairs(candidates) do
    local ok, val
    if addr >= IWRAM_START and addr < IWRAM_START + IWRAM_SIZE then
      local offset = addr - IWRAM_START
      if size == 1 then
        ok, val = pcall(emu.memory.iwram.read8, emu.memory.iwram, offset)
      elseif size == 2 then
        ok, val = pcall(emu.memory.iwram.read16, emu.memory.iwram, offset)
      else
        ok, val = pcall(emu.memory.iwram.read32, emu.memory.iwram, offset)
      end
    else
      local offset = addr - EWRAM_START
      if size == 1 then
        ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
      elseif size == 2 then
        ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
      else
        ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
      end
    end
    if ok and val == target then
      kept[#kept + 1] = addr
    end
  end
  console:log(string.format("Kept %d matches", #kept))
  return kept
end

--[[
  Display scan results
  @param candidates table of addresses
  @param name description of what was scanned
]]
local function show(candidates, name)
  console:log(string.format("=== %s: %d match(es) ===", name, #candidates))
  for i, addr in ipairs(candidates) do
    if i <= 20 then
      console:log(string.format("  0x%08X", addr))
    end
  end
  if #candidates > 20 then
    console:log(string.format("  ... and %d more", #candidates - 20))
  end
end

--[[
  Read current value at an address (for debugging)
  @param addr absolute address
  @param size read size (1, 2, or 4)
  @return value or nil
]]
local function peek(addr, size)
  local ok, val
  if addr >= IWRAM_START and addr < IWRAM_START + IWRAM_SIZE then
    local offset = addr - IWRAM_START
    if size == 1 then
      ok, val = pcall(emu.memory.iwram.read8, emu.memory.iwram, offset)
    elseif size == 2 then
      ok, val = pcall(emu.memory.iwram.read16, emu.memory.iwram, offset)
    else
      ok, val = pcall(emu.memory.iwram.read32, emu.memory.iwram, offset)
    end
  else
    local offset = addr - EWRAM_START
    if size == 1 then
      ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    elseif size == 2 then
      ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
    else
      ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    end
  end
  if ok then
    return val
  end
  return nil
end

--[[
  Predict Run & Bun address from vanilla Emerald address
  Uses the observed delta of +0x878 for EWRAM addresses
  @param vanillaAddr vanilla Emerald address
  @return predicted Run & Bun address
]]
local function predictRB(vanillaAddr)
  if vanillaAddr >= EWRAM_START and vanillaAddr < EWRAM_START + EWRAM_SIZE then
    return vanillaAddr + 0x878
  end
  -- IWRAM addresses are usually unchanged
  return vanillaAddr
end

-- Expose functions globally for console use
_G.scan32 = scan32
_G.scan16 = scan16
_G.scan8 = scan8
_G.scanIWRAM32 = scanIWRAM32
_G.rescan = rescan
_G.show = show
_G.peek = peek
_G.predictRB = predictRB
_G.results = results

console:log("==============================================")
console:log("Battle Address Scanner loaded!")
console:log("==============================================")
console:log("")
console:log("PREDICTED ADDRESSES (vanilla + 0x878 delta):")
console:log(string.format("  gPlayerParty:   0x%08X (vanilla: 0x020244EC)", predictRB(0x020244EC)))
console:log(string.format("  gEnemyParty:    0x%08X (vanilla: 0x02024744)", predictRB(0x02024744)))
console:log(string.format("  gBattleTypeFlags: 0x%08X (vanilla: 0x02022FEC)", predictRB(0x02022FEC)))
console:log(string.format("  gBattleControllerExecFlags: 0x%08X (vanilla: 0x02024068)", predictRB(0x02024068)))
console:log(string.format("  gRngValue:      0x03005D80 (IWRAM, likely unchanged)"))
console:log("")
console:log("=== STEP 1: Find gBattleTypeFlags ===")
console:log("  a) Enter a TRAINER battle")
console:log("  b) Execute: btf = scan32(0x8)  -- BATTLE_TYPE_TRAINER")
console:log("  c) Flee or win the battle")
console:log("  d) Execute: btf = rescan(btf, 0, 4)")
console:log("  e) Execute: show(btf, 'gBattleTypeFlags')")
console:log("")
console:log("=== STEP 2: Find gEnemyParty via HP ===")
console:log("  a) Enter battle, note enemy HP (e.g., 45)")
console:log("  b) Execute: hp = scan16(45)")
console:log("  c) Attack to change enemy HP (e.g., 32)")
console:log("  d) Execute: hp = rescan(hp, 32, 2)")
console:log("  e) Execute: show(hp, 'EnemyHP')")
console:log("  f) gEnemyParty = found address - 0x56")
console:log("")
console:log("=== STEP 3: Find gPlayerParty via HP ===")
console:log("  a) Note your lead Pokemon's HP")
console:log("  b) Execute: myHp = scan16(HP_VALUE)")
console:log("  c) Take damage, note new HP")
console:log("  d) Execute: myHp = rescan(myHp, NEW_HP, 2)")
console:log("  e) Execute: show(myHp, 'PlayerHP')")
console:log("  f) gPlayerParty = found address - 0x56")
console:log("")
console:log("=== STEP 4: Find gBattleControllerExecFlags ===")
console:log("  a) During battle, when choosing a move")
console:log("  b) Execute: ef = scan32(3) -- both battlers pending")
console:log("  c) Choose move, wait for turn to execute")
console:log("  d) Execute: ef = rescan(ef, 0, 4)")
console:log("  e) Execute: show(ef, 'gBattleControllerExecFlags')")
console:log("")
console:log("=== STEP 5: Find gMain.inBattle ===")
console:log("  a) During battle: ib = scan8(1)")
console:log("  b) Exit battle: ib = rescan(ib, 0, 1)")
console:log("  c) Execute: show(ib, 'inBattle')")
console:log("")
console:log("=== STEP 6: Verify gRngValue (IWRAM) ===")
console:log("  a) Execute: rng = peek(0x03005D80, 4)")
console:log("  b) If it returns a non-zero value that changes, it's correct")
console:log("")
console:log("=== HELPER COMMANDS ===")
console:log("  peek(addr, size)   - Read value at address")
console:log("  predictRB(vanilla) - Predict R&B address from vanilla")
console:log("")
