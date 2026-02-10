--[[
  Scanner: Find CB2_InitBattle and related addresses in Run & Bun ROM

  Strategy:
  1. Search ROM literal pools for CB2_HandleStartBattle (0x08037B45)
     → finds CB2_InitBattleInternal (which calls SetMainCallback2(CB2_HandleStartBattle))
  2. Search ROM literal pools for CB2_InitBattleInternal address
     → finds CB2_InitBattle (which calls CB2_InitBattleInternal())
  3. Search for CB2_ReturnToFieldContinueScriptPlayMapMusic
     → needed for gMain.savedCallback
  4. Find gMain.savedCallback offset by analyzing CB2_InitBattle

  Run in mGBA: Tools > Scripting > Load Script
  Results printed to console.
]]

local CHUNK = 4096
local ROM_SIZE = 0x02000000  -- 32MB max, scan what exists
local CB2_HANDLE_START = 0x08037B45  -- Known CB2_HandleStartBattle address

-- Helper: read u16 from binary string at 1-indexed position
local function strU16(s, pos)
  local b0, b1 = string.byte(s, pos, pos + 1)
  if not b0 or not b1 then return nil end
  return b0 + b1 * 256
end

-- Helper: decode THUMB BL target from two halfwords + PC address
local function decodeBL(instrH, instrL, pc)
  local off11hi = instrH & 0x07FF
  local off11lo = instrL & 0x07FF
  local fullOff = (off11hi << 12) | (off11lo << 1)
  if fullOff >= 0x400000 then fullOff = fullOff - 0x800000 end
  return pc + fullOff
end

-- Find all literal pool references to a 32-bit value in ROM
local function findLiteralPoolRefs(targetValue, maxROMSize)
  local b0 = targetValue & 0xFF
  local b1 = (targetValue >> 8) & 0xFF
  local b2 = (targetValue >> 16) & 0xFF
  local b3 = (targetValue >> 24) & 0xFF
  local refs = {}

  for base = 0, maxROMSize - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do  -- aligned to 4
        local d0, d1, d2, d3 = string.byte(data, i, i + 3)
        if d0 == b0 and d1 == b1 and d2 == b2 and d3 == b3 then
          table.insert(refs, base + i - 1)
        end
      end
    end
  end

  return refs
end

-- Find the containing THUMB function for a literal pool entry
-- Walks backward from the literal to find PUSH {LR} prologue
local function findContainingFunction(litOff)
  local searchStart = math.max(0, litOff - 512)
  local readLen = litOff - searchStart
  if readLen < 2 then return nil end

  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
  if not ok or not data then return nil end

  -- Walk backward to find last PUSH {LR} or PUSH {R4-R7, LR}
  local funcStart = nil
  for pos = readLen - 1, 1, -2 do
    if pos >= 1 and pos + 1 <= #data then
      local instr = strU16(data, pos)
      if instr and ((instr & 0xFF00) == 0xB500 or (instr & 0xFF00) == 0xB400) then
        funcStart = searchStart + pos - 1
        break
      end
    end
  end

  return funcStart
end

-- Analyze a THUMB function: count BLs, find BL targets, find function end
local function analyzeFunction(funcRomOff, maxSize)
  maxSize = maxSize or 2048
  local readLen = math.min(maxSize, 4096)

  -- Read in chunks
  local chunks = {}
  for chunkBase = funcRomOff, funcRomOff + readLen - 1, CHUNK do
    local chunkLen = math.min(CHUNK, funcRomOff + readLen - chunkBase)
    local ok, cData = pcall(emu.memory.cart0.readRange, emu.memory.cart0, chunkBase, chunkLen)
    if ok and cData then
      table.insert(chunks, cData)
    end
  end
  local data = table.concat(chunks)
  if #data < 4 then return nil end

  -- Verify starts with PUSH
  local firstInstr = strU16(data, 1)
  if not firstInstr or ((firstInstr & 0xFF00) ~= 0xB500 and (firstInstr & 0xFF00) ~= 0xB400) then
    return nil
  end

  -- Find function end and collect BL targets
  local funcEnd = nil
  local blTargets = {}
  local pos = 1
  while pos <= #data - 1 do
    local instr = strU16(data, pos)
    if not instr then break end

    -- POP {PC} or BX LR = function end
    if pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
      funcEnd = pos + 2
      break
    end

    -- BL instruction (two halfwords)
    if pos <= #data - 3 then
      local next = strU16(data, pos + 2)
      if next and (instr & 0xF800) == 0xF000 and (next & 0xF800) == 0xF800 then
        local blPC = 0x08000000 + funcRomOff + (pos - 1) + 4
        local target = decodeBL(instr, next, blPC)
        table.insert(blTargets, { offset = pos - 1, target = target })
        pos = pos + 4
      else
        pos = pos + 2
      end
    else
      pos = pos + 2
    end
  end

  local size = funcEnd and (funcEnd - 1) or #data
  return {
    romOff = funcRomOff,
    addr = 0x08000000 + funcRomOff + 1,  -- THUMB address
    size = size,
    blTargets = blTargets,
    blCount = #blTargets,
    hasEnd = funcEnd ~= nil
  }
end

-- ============================================================
-- MAIN SCANNER
-- ============================================================

console:log("=== CB2_InitBattle Scanner ===")
console:log("")

-- Determine actual ROM size (scan until we hit all-0xFF)
local actualROMSize = ROM_SIZE
for testSize = 0x200000, ROM_SIZE, 0x200000 do  -- test 2MB increments
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, testSize - 4, 4)
  if not ok then
    actualROMSize = testSize - 0x200000
    break
  end
end
console:log(string.format("ROM size estimate: %d MB", actualROMSize / (1024*1024)))

-- ===== STEP 1: Find functions referencing CB2_HandleStartBattle =====
console:log("")
console:log("--- Step 1: Find CB2_HandleStartBattle refs in literal pools ---")
local handleStartRefs = findLiteralPoolRefs(CB2_HANDLE_START, actualROMSize)
console:log(string.format("Found %d literal pool refs to CB2_HandleStartBattle (0x%08X)", #handleStartRefs, CB2_HANDLE_START))

local initBattleInternalCandidates = {}
for _, litOff in ipairs(handleStartRefs) do
  local funcStart = findContainingFunction(litOff)
  if funcStart then
    local info = analyzeFunction(funcStart)
    if info and info.hasEnd then
      -- CB2_InitBattleInternal is a LARGE function (400-2000 bytes, many BL calls)
      -- It's NOT CB2_HandleStartBattle itself (which we already know)
      if info.addr ~= CB2_HANDLE_START and info.size >= 100 and info.size <= 2000 then
        -- Check if it BL-calls functions that look like SetMainCallback2
        -- (SetMainCallback2 would be a small function that stores to gMain.callback2)
        local isDuplicate = false
        for _, c in ipairs(initBattleInternalCandidates) do
          if c.addr == info.addr then isDuplicate = true; break end
        end
        if not isDuplicate then
          table.insert(initBattleInternalCandidates, info)
        end
      end
    end
  end
end

-- Sort by size descending (CB2_InitBattleInternal is one of the larger functions)
table.sort(initBattleInternalCandidates, function(a, b) return a.size > b.size end)

console:log(string.format("CB2_InitBattleInternal candidates: %d", #initBattleInternalCandidates))
for i, c in ipairs(initBattleInternalCandidates) do
  console:log(string.format("  Candidate %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
  if i <= 3 then
    for j, bl in ipairs(c.blTargets) do
      console:log(string.format("    BL%d → 0x%08X", j, bl.target))
    end
  end
end

-- The best candidate is the LARGEST function (CB2_InitBattleInternal does a LOT of setup)
local cb2InitBattleInternal = nil
if #initBattleInternalCandidates > 0 then
  cb2InitBattleInternal = initBattleInternalCandidates[1]
  console:log(string.format("\nBEST CB2_InitBattleInternal = 0x%08X (%d bytes, %d BLs)",
    cb2InitBattleInternal.addr, cb2InitBattleInternal.size, cb2InitBattleInternal.blCount))
end

-- ===== STEP 2: Find functions that BL to CB2_InitBattleInternal =====
if cb2InitBattleInternal then
  console:log("")
  console:log("--- Step 2: Find CB2_InitBattle (calls CB2_InitBattleInternal) ---")

  -- CB2_InitBattle directly calls CB2_InitBattleInternal() (not via SetMainCallback2)
  -- So we search literal pools for CB2_InitBattleInternal's address
  local internalAddr = cb2InitBattleInternal.addr
  local internalRefs = findLiteralPoolRefs(internalAddr, actualROMSize)
  console:log(string.format("Found %d literal pool refs to CB2_InitBattleInternal (0x%08X)", #internalRefs, internalAddr))

  -- Also search for BL instructions that target CB2_InitBattleInternal
  -- BL is relative, so we can't search literal pools for it
  -- Instead, scan a region around CB2_InitBattleInternal for functions that BL to it

  local cb2InitBattleCandidates = {}

  -- First: check literal pool refs
  for _, litOff in ipairs(internalRefs) do
    local funcStart = findContainingFunction(litOff)
    if funcStart then
      local info = analyzeFunction(funcStart, 512)
      if info and info.hasEnd and info.addr ~= internalAddr then
        -- CB2_InitBattle is a small-medium function (100-400 bytes, 3-8 BLs)
        if info.size >= 30 and info.size <= 500 then
          local isDuplicate = false
          for _, c in ipairs(cb2InitBattleCandidates) do
            if c.addr == info.addr then isDuplicate = true; break end
          end
          if not isDuplicate then
            table.insert(cb2InitBattleCandidates, info)
          end
        end
      end
    end
  end

  -- Also scan nearby ROM for functions that BL directly to CB2_InitBattleInternal
  local targetPC = internalAddr & 0xFFFFFFFE  -- clear THUMB bit
  local scanStart = math.max(0, cb2InitBattleInternal.romOff - 0x10000)
  local scanEnd = math.min(actualROMSize, cb2InitBattleInternal.romOff + 0x10000)

  for base = scanStart, scanEnd - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
    if ok and data then
      for pos = 1, #data - 3, 2 do
        local h = strU16(data, pos)
        local l = strU16(data, pos + 2)
        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800 then
          local blPC = 0x08000000 + base + (pos - 1) + 4
          local target = decodeBL(h, l, blPC)
          if target == targetPC or target == (targetPC | 1) then
            -- Found a BL to CB2_InitBattleInternal!
            local funcStart = findContainingFunction(base + pos - 1)
            if funcStart then
              local info = analyzeFunction(funcStart, 512)
              if info and info.hasEnd and info.addr ~= internalAddr and info.size >= 30 and info.size <= 500 then
                local isDuplicate = false
                for _, c in ipairs(cb2InitBattleCandidates) do
                  if c.addr == info.addr then isDuplicate = true; break end
                end
                if not isDuplicate then
                  table.insert(cb2InitBattleCandidates, info)
                end
              end
            end
          end
        end
      end
    end
  end

  -- Sort by: has BL to AllocateBattleResources-like function, then by size
  table.sort(cb2InitBattleCandidates, function(a, b)
    if a.blCount ~= b.blCount then return a.blCount > b.blCount end
    return a.size > b.size
  end)

  console:log(string.format("CB2_InitBattle candidates: %d", #cb2InitBattleCandidates))
  for i, c in ipairs(cb2InitBattleCandidates) do
    console:log(string.format("  Candidate %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
    for j, bl in ipairs(c.blTargets) do
      console:log(string.format("    BL%d → 0x%08X", j, bl.target))
    end
  end

  if #cb2InitBattleCandidates > 0 then
    local best = cb2InitBattleCandidates[1]
    console:log(string.format("\nBEST CB2_InitBattle = 0x%08X (%d bytes, %d BLs)", best.addr, best.size, best.blCount))
  end
end

-- ===== STEP 3: Find CB2_ReturnToFieldContinueScriptPlayMapMusic =====
-- This is the callback used to return to the overworld after a battle.
-- It's commonly stored in gMain.savedCallback before a battle.
-- We can find it by looking at what CB2_EndTrainerBattle calls SetMainCallback2 with.
-- For now, find CB2_Overworld's literal pool (0x080A89A5) and look nearby for return callbacks.
console:log("")
console:log("--- Step 3: Find savedCallback address & return callback ---")

-- gMain base = 0x02020648, callback2 at +0x04 = 0x0202064C (known)
-- savedCallback is at +0x08 in the decomp... but R&B has modified gMain struct
-- Let's verify: read what's at gMain+0x08 right now
local gMainBase = 0x02020648
local savedCbOff = 0x08
local okS, savedCb = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + savedCbOff)
if okS then
  console:log(string.format("gMain.savedCallback (gMain+0x08) = 0x%08X", savedCb))
  -- Check if this looks like a ROM function pointer (0x08xxxxxx)
  if savedCb >= 0x08000000 and savedCb < 0x0A000000 then
    console:log("  -> Looks like a valid ROM function pointer!")
    console:log("  -> This is likely CB2_ReturnToFieldContinueScriptPlayMapMusic or CB2_Overworld")
  else
    console:log("  -> Does NOT look like a ROM function pointer")
    console:log("  -> gMain.savedCallback might be at a different offset in R&B")

    -- Scan nearby offsets for a ROM pointer
    for off = 0x04, 0x20, 0x04 do
      local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
      if ok2 and val >= 0x08000000 and val < 0x0A000000 then
        console:log(string.format("  gMain+0x%02X = 0x%08X (ROM ptr)", off, val))
      end
    end
  end
end

-- ===== STEP 4: Try to find CB2_ReturnToFieldContinueScriptPlayMapMusic =====
-- This function is called as SetMainCallback2 target by CB2_EndTrainerBattle.
-- It sets up the overworld return. It likely calls CB2_ReturnToField internally.
-- For now, search for functions near CB2_Overworld (0x080A89A5) that are used as callbacks.

-- Actually, let's search for literal pool refs to CB2_Overworld (0x080A89A5)
-- CB2_ReturnToField sets callback2 = CB2_Overworld, so it references it.
local cb2Overworld = 0x080A89A5
local overworldRefs = findLiteralPoolRefs(cb2Overworld, actualROMSize)
console:log(string.format("\nFound %d literal pool refs to CB2_Overworld (0x%08X)", #overworldRefs, cb2Overworld))

-- Analyze the containing functions — small functions that reference CB2_Overworld
-- are likely CB2_ReturnToField variants
local returnCallbackCandidates = {}
for _, litOff in ipairs(overworldRefs) do
  local funcStart = findContainingFunction(litOff)
  if funcStart then
    local info = analyzeFunction(funcStart, 256)
    if info and info.hasEnd and info.size >= 10 and info.size <= 200 then
      local isDuplicate = false
      for _, c in ipairs(returnCallbackCandidates) do
        if c.addr == info.addr then isDuplicate = true; break end
      end
      if not isDuplicate then
        table.insert(returnCallbackCandidates, info)
      end
    end
  end
end

table.sort(returnCallbackCandidates, function(a, b) return a.size < b.size end)
console:log(string.format("CB2_ReturnToField* candidates (small funcs referencing CB2_Overworld): %d", #returnCallbackCandidates))
for i, c in ipairs(returnCallbackCandidates) do
  if i <= 10 then
    console:log(string.format("  %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
  end
end

-- ===== SUMMARY =====
console:log("")
console:log("=== SUMMARY ===")
console:log(string.format("CB2_HandleStartBattle      = 0x%08X (known)", CB2_HANDLE_START))
if cb2InitBattleInternal then
  console:log(string.format("CB2_InitBattleInternal     = 0x%08X (%d bytes)", cb2InitBattleInternal.addr, cb2InitBattleInternal.size))
end
if #initBattleInternalCandidates > 0 then
  -- noop, already printed
end
if cb2InitBattleCandidates and #cb2InitBattleCandidates > 0 then
  console:log(string.format("CB2_InitBattle             = 0x%08X (%d bytes)", cb2InitBattleCandidates[1].addr, cb2InitBattleCandidates[1].size))
end
if #returnCallbackCandidates > 0 then
  console:log(string.format("CB2_ReturnToField* (first) = 0x%08X (%d bytes)", returnCallbackCandidates[1].addr, returnCallbackCandidates[1].size))
end

console:log("")
console:log("=== Copy these to config/run_and_bun.lua battle_link section ===")
if cb2InitBattleCandidates and #cb2InitBattleCandidates > 0 then
  console:log(string.format("CB2_InitBattle = 0x%08X,", cb2InitBattleCandidates[1].addr))
end
if cb2InitBattleInternal then
  console:log(string.format("CB2_InitBattleInternal = 0x%08X,", cb2InitBattleInternal.addr))
end

console:log("")
console:log("Scanner complete! Run this in mGBA to find the addresses.")
console:log("Then update config/run_and_bun.lua and reload the client.")
