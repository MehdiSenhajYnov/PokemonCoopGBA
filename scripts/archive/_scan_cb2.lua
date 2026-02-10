--[[
  Autonomous scanner: Find CB2_InitBattle, CB2_ReturnToField, and verify savedCallback offset.
  Writes results to _scan_results.json in project root.
  Designed for --script CLI execution.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local CHUNK = 4096
local CB2_HANDLE_START = 0x08037B45

-- Write progress marker
local function writeProgress(stage)
  local f = io.open("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt", "w")
  if f then f:write(stage .. "\n"); f:close() end
end

writeProgress("started")

-- Helper: read u16 from binary string at 1-indexed position
local function strU16(s, pos)
  local b0, b1 = string.byte(s, pos, pos + 1)
  if not b0 or not b1 then return nil end
  return b0 + b1 * 256
end

-- Helper: read u32 from binary string at 1-indexed position
local function strU32(s, pos)
  local b0, b1, b2, b3 = string.byte(s, pos, pos + 3)
  if not b0 or not b1 or not b2 or not b3 then return nil end
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
      for i = 1, #data - 3, 4 do
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
local function findContainingFunction(litOff)
  local searchStart = math.max(0, litOff - 512)
  local readLen = litOff - searchStart
  if readLen < 2 then return nil end

  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
  if not ok or not data then return nil end

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

-- Analyze a THUMB function
local function analyzeFunction(funcRomOff, maxSize)
  maxSize = maxSize or 2048
  local readLen = math.min(maxSize, 4096)

  local chunks = {}
  for chunkBase = funcRomOff, funcRomOff + readLen - 1, CHUNK do
    local chunkLen = math.min(CHUNK, funcRomOff + readLen - chunkBase)
    local ok, cData = pcall(emu.memory.cart0.readRange, emu.memory.cart0, chunkBase, chunkLen)
    if ok and cData then table.insert(chunks, cData) end
  end
  local data = table.concat(chunks)
  if #data < 4 then return nil end

  local firstInstr = strU16(data, 1)
  if not firstInstr or ((firstInstr & 0xFF00) ~= 0xB500 and (firstInstr & 0xFF00) ~= 0xB400) then
    return nil
  end

  local funcEnd = nil
  local blTargets = {}
  local pos = 1
  while pos <= #data - 1 do
    local instr = strU16(data, pos)
    if not instr then break end

    if pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
      funcEnd = pos + 2
      break
    end

    if pos <= #data - 3 then
      local nxt = strU16(data, pos + 2)
      if nxt and (instr & 0xF800) == 0xF000 and (nxt & 0xF800) == 0xF800 then
        local blPC = 0x08000000 + funcRomOff + (pos - 1) + 4
        local target = decodeBL(instr, nxt, blPC)
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
    addr = 0x08000000 + funcRomOff + 1,
    size = size,
    blTargets = blTargets,
    blCount = #blTargets,
    hasEnd = funcEnd ~= nil
  }
end

-- ============================================================
-- MAIN SCANNER (runs inside frame callback to ensure ROM is loaded)
-- ============================================================

local scanDone = false
local frameCb
frameCb = callbacks:add("frame", function()
  if scanDone then return end
  scanDone = true
  frameCb:remove()

  writeProgress("scanning")
  console:log("=== CB2_InitBattle Autonomous Scanner ===")

  local results = {
    status = "scanning",
    CB2_HandleStartBattle = string.format("0x%08X", CB2_HANDLE_START),
    CB2_InitBattleInternal = nil,
    CB2_InitBattle = nil,
    CB2_ReturnToField_candidates = {},
    savedCallback_check = {},
    logs = {},
  }

  local function logR(msg)
    table.insert(results.logs, msg)
    console:log(msg)
  end

  -- Determine ROM size
  local actualROMSize = 0x02000000
  for testSize = 0x200000, 0x02000000, 0x200000 do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, testSize - 4, 4)
    if not ok then
      actualROMSize = testSize - 0x200000
      break
    end
  end
  logR(string.format("ROM size: %d MB", actualROMSize / (1024*1024)))

  -- STEP 1: Find functions referencing CB2_HandleStartBattle
  logR("--- Step 1: Find CB2_HandleStartBattle refs ---")
  local handleStartRefs = findLiteralPoolRefs(CB2_HANDLE_START, actualROMSize)
  logR(string.format("Found %d literal pool refs", #handleStartRefs))

  local initBattleInternalCandidates = {}
  for _, litOff in ipairs(handleStartRefs) do
    local funcStart = findContainingFunction(litOff)
    if funcStart then
      local info = analyzeFunction(funcStart)
      if info and info.hasEnd and info.addr ~= CB2_HANDLE_START and info.size >= 100 and info.size <= 2000 then
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

  table.sort(initBattleInternalCandidates, function(a, b) return a.size > b.size end)

  logR(string.format("CB2_InitBattleInternal candidates: %d", #initBattleInternalCandidates))
  for i, c in ipairs(initBattleInternalCandidates) do
    logR(string.format("  Candidate %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
  end

  local cb2InitBattleInternal = nil
  if #initBattleInternalCandidates > 0 then
    cb2InitBattleInternal = initBattleInternalCandidates[1]
    results.CB2_InitBattleInternal = string.format("0x%08X", cb2InitBattleInternal.addr)
    logR(string.format("BEST CB2_InitBattleInternal = 0x%08X (%d bytes, %d BLs)",
      cb2InitBattleInternal.addr, cb2InitBattleInternal.size, cb2InitBattleInternal.blCount))
  end

  -- STEP 2: Find CB2_InitBattle
  local cb2InitBattleCandidates = {}
  if cb2InitBattleInternal then
    logR("--- Step 2: Find CB2_InitBattle ---")

    local internalAddr = cb2InitBattleInternal.addr
    local internalRefs = findLiteralPoolRefs(internalAddr, actualROMSize)
    logR(string.format("Found %d literal pool refs to CB2_InitBattleInternal", #internalRefs))

    for _, litOff in ipairs(internalRefs) do
      local funcStart = findContainingFunction(litOff)
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

    -- Also scan nearby ROM for BL instructions targeting CB2_InitBattleInternal
    local targetPC = internalAddr & 0xFFFFFFFE
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

    table.sort(cb2InitBattleCandidates, function(a, b)
      if a.blCount ~= b.blCount then return a.blCount > b.blCount end
      return a.size > b.size
    end)

    logR(string.format("CB2_InitBattle candidates: %d", #cb2InitBattleCandidates))
    for i, c in ipairs(cb2InitBattleCandidates) do
      logR(string.format("  Candidate %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
      for j, bl in ipairs(c.blTargets) do
        logR(string.format("    BL%d -> 0x%08X", j, bl.target))
      end
    end

    if #cb2InitBattleCandidates > 0 then
      results.CB2_InitBattle = string.format("0x%08X", cb2InitBattleCandidates[1].addr)
      logR(string.format("BEST CB2_InitBattle = 0x%08X", cb2InitBattleCandidates[1].addr))
    end
  end

  -- STEP 3: Find CB2_ReturnToField candidates
  logR("--- Step 3: CB2_ReturnToField candidates ---")
  local cb2Overworld = 0x080A89A5
  local overworldRefs = findLiteralPoolRefs(cb2Overworld, actualROMSize)
  logR(string.format("Found %d literal pool refs to CB2_Overworld", #overworldRefs))

  local returnCandidates = {}
  for _, litOff in ipairs(overworldRefs) do
    local funcStart = findContainingFunction(litOff)
    if funcStart then
      local info = analyzeFunction(funcStart, 256)
      if info and info.hasEnd and info.size >= 10 and info.size <= 200 then
        local isDuplicate = false
        for _, c in ipairs(returnCandidates) do
          if c.addr == info.addr then isDuplicate = true; break end
        end
        if not isDuplicate then
          table.insert(returnCandidates, info)
        end
      end
    end
  end

  table.sort(returnCandidates, function(a, b) return a.size < b.size end)
  for i, c in ipairs(returnCandidates) do
    if i <= 10 then
      table.insert(results.CB2_ReturnToField_candidates,
        string.format("0x%08X (%d bytes, %d BLs)", c.addr, c.size, c.blCount))
      logR(string.format("  %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
    end
  end

  -- STEP 4: Check gMain.savedCallback
  logR("--- Step 4: gMain.savedCallback ---")
  local gMainBase = 0x02020648
  for off = 0x00, 0x20, 0x04 do
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
    if ok then
      local isROM = val >= 0x08000000 and val < 0x0A000000
      local entry = string.format("gMain+0x%02X = 0x%08X%s", off, val, isROM and " (ROM ptr)" or "")
      table.insert(results.savedCallback_check, entry)
      logR(entry)
    end
  end

  -- STEP 5: Verify known battle addresses
  logR("--- Step 5: Quick battle address verification ---")
  local verifyAddrs = {
    { name = "gBattleTypeFlags", addr = 0x020090E8, size = 4 },
    { name = "gPlayerParty[0].personality", addr = 0x02023A98, size = 4 },
    { name = "gPlayerPartyCount", addr = 0x02023A95, size = 1 },
    { name = "gMainInBattle", addr = 0x020206AE, size = 1 },
    { name = "gBattleResources", addr = 0x02023A18, size = 4 },
  }
  for _, v in ipairs(verifyAddrs) do
    local ok, val
    if v.size == 1 then
      ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, v.addr - 0x02000000)
    else
      ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, v.addr - 0x02000000)
    end
    if ok then
      logR(string.format("  %s = 0x%X", v.name, val))
    end
  end

  -- Write results
  results.status = "complete"
  writeProgress("writing_results")

  -- Simple JSON serialization
  local json = "{\n"
  json = json .. '  "status": "complete",\n'
  json = json .. '  "CB2_HandleStartBattle": "' .. results.CB2_HandleStartBattle .. '",\n'
  json = json .. '  "CB2_InitBattleInternal": ' .. (results.CB2_InitBattleInternal and ('"' .. results.CB2_InitBattleInternal .. '"') or "null") .. ',\n'
  json = json .. '  "CB2_InitBattle": ' .. (results.CB2_InitBattle and ('"' .. results.CB2_InitBattle .. '"') or "null") .. ',\n'

  json = json .. '  "CB2_ReturnToField_candidates": [\n'
  for i, c in ipairs(results.CB2_ReturnToField_candidates) do
    json = json .. '    "' .. c .. '"' .. (i < #results.CB2_ReturnToField_candidates and ',' or '') .. '\n'
  end
  json = json .. '  ],\n'

  json = json .. '  "savedCallback_check": [\n'
  for i, c in ipairs(results.savedCallback_check) do
    json = json .. '    "' .. c .. '"' .. (i < #results.savedCallback_check and ',' or '') .. '\n'
  end
  json = json .. '  ],\n'

  json = json .. '  "logs": [\n'
  for i, l in ipairs(results.logs) do
    json = json .. '    "' .. l:gsub('"', '\\"'):gsub('\\', '\\\\') .. '"' .. (i < #results.logs and ',' or '') .. '\n'
  end
  json = json .. '  ]\n'
  json = json .. '}\n'

  local f = io.open(OUTPUT, "w")
  if f then
    f:write(json)
    f:close()
    logR("Results written to " .. OUTPUT)
  else
    logR("ERROR: Could not write results")
  end

  writeProgress("done")
  console:log("=== Scanner complete ===")
end)
