--[[
  ROM Function Signature Scanner

  Scans ROM literal pools for references to known EWRAM/IO addresses,
  then identifies containing functions by walking backward to PUSH {LR}.

  Uses the proven readRange-based ROM scanner from hal.lua for performance.

  TARGETS:
  - GetMultiplayerId: references IO register 0x04000120 (SIO_MULTI_CNT)
  - gBattleResources: EWRAM pointer, found via Phase 1A/1B diff
  - CreateTask: references gTasks array (EWRAM)
  - gWirelessCommType: EWRAM variable
  - gLinkPlayers: EWRAM array
  - gReceivedRemoteLinkPlayers: EWRAM variable
  - gBlockReceivedStatus: EWRAM array
  - gBattleCommunication: EWRAM array

  USAGE:
  1. Load this script in mGBA
  2. Results printed to console immediately (ROM scan, no game state needed)
  3. Copy addresses into config/run_and_bun.lua battle_link section
]]

console:log("=== ROM FUNCTION SIGNATURE SCANNER ===")
console:log("")

local SCAN_SIZE = 0x800000  -- 8MB ROM
local CHUNK = 4096

-- Helper: read u16 little-endian from binary string at 1-indexed position
local function strU16(s, pos)
  if pos < 1 or pos + 1 > #s then return nil end
  local b0, b1 = string.byte(s, pos, pos + 1)
  if not b0 or not b1 then return nil end
  return b0 + b1 * 256
end

-- Helper: read u32 little-endian from binary string
local function strU32(s, pos)
  if pos < 1 or pos + 3 > #s then return nil end
  local b0, b1, b2, b3 = string.byte(s, pos, pos + 3)
  if not b0 then return nil end
  return b0 + b1 * 256 + b2 * 65536 + b3 * 16777216
end

-- Helper: decode THUMB BL target from two halfwords + PC address
local function decodeBL(instrH, instrL, pc)
  local off11hi = instrH & 0x07FF
  local off11lo = instrL & 0x07FF
  local fullOff = (off11hi << 12) | (off11lo << 1)
  if fullOff >= 0x400000 then fullOff = fullOff - 0x800000 end
  return pc + fullOff
end

--[[
  Scan ROM for all occurrences of a 32-bit value in literal pools.
  Returns list of ROM offsets where the value appears.
]]
local function findLiteralRefs(targetValue)
  local refs = {}
  local b0 = targetValue & 0xFF
  local b1 = (targetValue >> 8) & 0xFF
  local b2 = (targetValue >> 16) & 0xFF
  local b3 = (targetValue >> 24) & 0xFF

  for base = 0, SCAN_SIZE - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do  -- 4-byte aligned for literal pools
        if string.byte(data, i) == b0 and
           string.byte(data, i + 1) == b1 and
           string.byte(data, i + 2) == b2 and
           string.byte(data, i + 3) == b3 then
          table.insert(refs, base + i - 1)
        end
      end
    end
  end

  return refs
end

--[[
  Given a literal pool offset, walk backward to find the containing function.
  Returns { addr = ROM_addr_with_thumb, romOff = ROM_offset, size = approx_size }
]]
local function findContainingFunction(litOff)
  local searchStart = math.max(0, litOff - 512)
  local readLen = litOff - searchStart
  if readLen < 2 then return nil end

  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
  if not ok or not data then return nil end

  for back = 2, readLen, 2 do
    local pos = readLen - back + 1
    if pos >= 1 and pos + 1 <= #data then
      local instr = strU16(data, pos)
      if instr and ((instr & 0xFF00) == 0xB400 or (instr & 0xFF00) == 0xB500) then
        local funcRomOff = searchStart + pos - 1
        local funcAddr = 0x08000000 + funcRomOff + 1  -- +1 for THUMB
        return { addr = funcAddr, romOff = funcRomOff }
      end
    end
  end

  return nil
end

--[[
  Analyze a function: count BL calls, function size, extract BL targets.
]]
local function analyzeFunction(romOff)
  local readLen = math.min(256, SCAN_SIZE - romOff)
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, romOff, readLen)
  if not ok or not data then return nil end

  local funcEnd = nil
  local blCount = 0
  local blTargets = {}
  local pos = 1

  while pos <= #data - 1 do
    local instr = strU16(data, pos)
    if not instr then break end

    -- Detect function end (POP {PC} or BX LR), skip first instruction
    if pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
      funcEnd = pos + 2
      break
    end

    -- Detect BL instruction pair
    if pos + 3 <= #data then
      local next = strU16(data, pos + 2)
      if next and (instr & 0xF800) == 0xF000 and (next & 0xF800) == 0xF800 then
        blCount = blCount + 1
        local blPC = 0x08000000 + romOff + (pos - 1) + 4
        local target = decodeBL(instr, next, blPC)
        table.insert(blTargets, target)
        pos = pos + 4
      else
        pos = pos + 2
      end
    else
      pos = pos + 2
    end
  end

  local size = funcEnd and (funcEnd - 1) or nil
  return {
    size = size,
    blCount = blCount,
    blTargets = blTargets,
  }
end

-- ============================================================
-- TARGET 1: GetMultiplayerId
-- References IO register 0x04000120 (SIO_MULTI_CNT)
-- Very short function (<30 instructions), returns player index
-- ============================================================

console:log("--- TARGET: GetMultiplayerId ---")
console:log("  Scanning for refs to SIO_MULTI_CNT (0x04000120)...")

local sioRefs = findLiteralRefs(0x04000120)
console:log(string.format("  Found %d refs to 0x04000120", #sioRefs))

local getMultiCandidates = {}
for _, litOff in ipairs(sioRefs) do
  local func = findContainingFunction(litOff)
  if func then
    local analysis = analyzeFunction(func.romOff)
    if analysis and analysis.size and analysis.size <= 60 then
      -- GetMultiplayerId is very small: reads SIO register, shifts, masks, returns
      local dup = false
      for _, c in ipairs(getMultiCandidates) do
        if c.addr == func.addr then dup = true; break end
      end
      if not dup then
        table.insert(getMultiCandidates, {
          addr = func.addr,
          size = analysis.size,
          blCount = analysis.blCount,
        })
      end
    end
  end
end

table.sort(getMultiCandidates, function(a, b) return a.size < b.size end)
for i, c in ipairs(getMultiCandidates) do
  console:log(string.format("  Candidate %d: 0x%08X (%d bytes, %d BL calls)%s",
    i, c.addr, c.size, c.blCount,
    c.blCount == 0 and " *** BEST (no calls = leaf function)" or ""))
end
console:log("")

-- ============================================================
-- TARGET 2: gWirelessCommType
-- EWRAM variable, value should be 0 or 1 during normal play
-- Referenced by many link/wireless functions
-- Search for common patterns in wireless code
-- ============================================================

console:log("--- TARGET: gWirelessCommType ---")
console:log("  Scanning for EWRAM vars with wireless comm characteristics...")
console:log("  (This requires battle state — use find_battle_functions.lua first)")
console:log("")

-- ============================================================
-- TARGET 3: gBattleCommunication
-- 8-byte array in EWRAM used for battle state machine sync
-- Usually near other battle globals
-- ============================================================

console:log("--- TARGET: gBattleCommunication ---")
console:log("  Typically near gBattleTypeFlags (0x020090E8)")
console:log("  Use ewram_battle_diff.lua to find changed blocks near this address")
console:log("")

-- ============================================================
-- TARGET 4: gBlockReceivedStatus
-- EWRAM array used for link data transfer tracking
-- ============================================================

console:log("--- TARGET: gBlockReceivedStatus ---")
console:log("  Scanning for refs to common link status patterns...")

-- Look for 0x04000128 (SIOCNT) — another link register used by the battle system
local siocntRefs = findLiteralRefs(0x04000128)
console:log(string.format("  Found %d refs to SIOCNT (0x04000128)", #siocntRefs))

-- List functions referencing SIOCNT (these are link communication functions)
local siocntFuncs = {}
for _, litOff in ipairs(siocntRefs) do
  local func = findContainingFunction(litOff)
  if func then
    local dup = false
    for _, f in ipairs(siocntFuncs) do
      if f.addr == func.addr then dup = true; break end
    end
    if not dup then
      local analysis = analyzeFunction(func.romOff)
      table.insert(siocntFuncs, {
        addr = func.addr,
        size = analysis and analysis.size or 0,
        blCount = analysis and analysis.blCount or 0,
      })
    end
  end
end

console:log(string.format("  %d functions reference SIOCNT:", #siocntFuncs))
for i = 1, math.min(10, #siocntFuncs) do
  local f = siocntFuncs[i]
  console:log(string.format("    0x%08X (%s bytes, %d BL)",
    f.addr, f.size and tostring(f.size) or "?", f.blCount))
end
console:log("")

-- ============================================================
-- TARGET 5: CB2_HandleStartBattle / CB2_InitBattle
-- References gBattleTypeFlags (0x020090E8)
-- One of the first functions called when a battle starts
-- ============================================================

console:log("--- TARGET: Battle Init Functions ---")
console:log("  Scanning for refs to gBattleTypeFlags (0x020090E8)...")

local btfRefs = findLiteralRefs(0x020090E8)
console:log(string.format("  Found %d refs to gBattleTypeFlags", #btfRefs))

local btfFuncs = {}
for _, litOff in ipairs(btfRefs) do
  local func = findContainingFunction(litOff)
  if func then
    local dup = false
    for _, f in ipairs(btfFuncs) do
      if f.addr == func.addr then dup = true; break end
    end
    if not dup then
      local analysis = analyzeFunction(func.romOff)
      table.insert(btfFuncs, {
        addr = func.addr,
        size = analysis and analysis.size or 0,
        blCount = analysis and analysis.blCount or 0,
        blTargets = analysis and analysis.blTargets or {},
      })
    end
  end
end

table.sort(btfFuncs, function(a, b) return (a.size or 999) < (b.size or 999) end)
console:log(string.format("  %d functions reference gBattleTypeFlags:", #btfFuncs))
for i = 1, math.min(20, #btfFuncs) do
  local f = btfFuncs[i]
  local blStr = ""
  for j, t in ipairs(f.blTargets) do
    if j <= 3 then
      blStr = blStr .. string.format(" BL%d->0x%08X", j, t)
    end
  end
  console:log(string.format("    0x%08X (%s bytes, %d BL)%s",
    f.addr, f.size and tostring(f.size) or "?", f.blCount, blStr))
end
console:log("")

-- ============================================================
-- SUMMARY
-- ============================================================

console:log("=== SCAN COMPLETE ===")
console:log("")
console:log("Next steps:")
console:log("  1. Test GetMultiplayerId candidates (smallest leaf function)")
console:log("  2. Run find_battle_functions.lua during a battle for watchpoint data")
console:log("  3. Run ewram_battle_diff.lua for EWRAM diff (find gBattleResources)")
console:log("  4. Cross-reference battle init functions with callback2 transitions")
console:log("  5. Fill discovered addresses into config/run_and_bun.lua battle_link section")
console:log("")
console:log("For ROM patching (if cart0 write works):")
console:log("  - GetMultiplayerId: MOV R0, #0 (host) or MOV R0, #1 (client)")
console:log("  - NOP wireless/link check instructions in battle init")
console:log("")
console:log("=== END ROM SCAN ===")
