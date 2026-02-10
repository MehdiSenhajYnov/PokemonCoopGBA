--[[
  Autonomous scanner v2: NO frame callbacks.
  Executes directly — emu.memory should already be available when --script runs
  after ROM is loaded.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local CHUNK = 4096
local CB2_HANDLE_START = 0x08037B45

local function writeFile(path, content)
  local f = io.open(path, "w")
  if f then f:write(content); f:close(); return true end
  return false
end

-- Test if emu.memory is available
local memOk, testVal = pcall(function() return emu.memory.wram:read8(0) end)
if not memOk then
  writeFile(OUTPUT, '{"status":"error","error":"emu.memory not available"}')
  return
end

writeFile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt", "scanning_v2")

-- Helper functions
local function strU16(s, pos)
  local b0, b1 = string.byte(s, pos, pos + 1)
  if not b0 or not b1 then return nil end
  return b0 + b1 * 256
end

local function decodeBL(instrH, instrL, pc)
  local off11hi = instrH & 0x07FF
  local off11lo = instrL & 0x07FF
  local fullOff = (off11hi << 12) | (off11lo << 1)
  if fullOff >= 0x400000 then fullOff = fullOff - 0x800000 end
  return pc + fullOff
end

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

local function findContainingFunction(litOff)
  local searchStart = math.max(0, litOff - 512)
  local readLen = litOff - searchStart
  if readLen < 2 then return nil end
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
  if not ok or not data then return nil end
  for pos = readLen - 1, 1, -2 do
    if pos >= 1 and pos + 1 <= #data then
      local instr = strU16(data, pos)
      if instr and ((instr & 0xFF00) == 0xB500 or (instr & 0xFF00) == 0xB400) then
        return searchStart + pos - 1
      end
    end
  end
  return nil
end

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
      funcEnd = pos + 2; break
    end
    if pos <= #data - 3 then
      local nxt = strU16(data, pos + 2)
      if nxt and (instr & 0xF800) == 0xF000 and (nxt & 0xF800) == 0xF800 then
        local blPC = 0x08000000 + funcRomOff + (pos - 1) + 4
        local target = decodeBL(instr, nxt, blPC)
        table.insert(blTargets, { offset = pos - 1, target = target })
        pos = pos + 4
      else pos = pos + 2 end
    else pos = pos + 2 end
  end
  return {
    romOff = funcRomOff,
    addr = 0x08000000 + funcRomOff + 1,
    size = funcEnd and (funcEnd - 1) or #data,
    blTargets = blTargets,
    blCount = #blTargets,
    hasEnd = funcEnd ~= nil
  }
end

-- ============================================================
-- SCAN
-- ============================================================

local logs = {}
local function log(msg)
  table.insert(logs, msg)
  pcall(function() console:log(msg) end)
end

log("=== CB2_InitBattle Scanner v2 (direct execution) ===")

-- ROM size
local actualROMSize = 0x02000000
for testSize = 0x200000, 0x02000000, 0x200000 do
  local ok = pcall(emu.memory.cart0.readRange, emu.memory.cart0, testSize - 4, 4)
  if not ok then actualROMSize = testSize - 0x200000; break end
end
log(string.format("ROM size: %d MB", actualROMSize / (1024*1024)))

-- Step 1: Find CB2_InitBattleInternal
log("--- Step 1: CB2_HandleStartBattle refs ---")
local handleStartRefs = findLiteralPoolRefs(CB2_HANDLE_START, actualROMSize)
log(string.format("Found %d refs", #handleStartRefs))

local ibIntCandidates = {}
for _, litOff in ipairs(handleStartRefs) do
  local funcStart = findContainingFunction(litOff)
  if funcStart then
    local info = analyzeFunction(funcStart)
    if info and info.hasEnd and info.addr ~= CB2_HANDLE_START and info.size >= 100 and info.size <= 2000 then
      local dup = false
      for _, c in ipairs(ibIntCandidates) do if c.addr == info.addr then dup = true; break end end
      if not dup then table.insert(ibIntCandidates, info) end
    end
  end
end
table.sort(ibIntCandidates, function(a, b) return a.size > b.size end)

local cb2IntAddr = nil
if #ibIntCandidates > 0 then
  cb2IntAddr = ibIntCandidates[1].addr
  log(string.format("BEST CB2_InitBattleInternal = 0x%08X (%d bytes, %d BLs)",
    cb2IntAddr, ibIntCandidates[1].size, ibIntCandidates[1].blCount))
  for i, c in ipairs(ibIntCandidates) do
    log(string.format("  Candidate %d: 0x%08X (%d bytes)", i, c.addr, c.size))
  end
end

-- Step 2: Find CB2_InitBattle
log("--- Step 2: CB2_InitBattle ---")
local ibCandidates = {}
if cb2IntAddr then
  -- Literal pool refs
  local intRefs = findLiteralPoolRefs(cb2IntAddr, actualROMSize)
  log(string.format("Found %d literal pool refs to CB2_InitBattleInternal", #intRefs))

  for _, litOff in ipairs(intRefs) do
    local funcStart = findContainingFunction(litOff)
    if funcStart then
      local info = analyzeFunction(funcStart, 512)
      if info and info.hasEnd and info.addr ~= cb2IntAddr and info.size >= 30 and info.size <= 500 then
        local dup = false
        for _, c in ipairs(ibCandidates) do if c.addr == info.addr then dup = true; break end end
        if not dup then table.insert(ibCandidates, info) end
      end
    end
  end

  -- BL scan in nearby ROM
  local targetPC = cb2IntAddr & 0xFFFFFFFE
  local intRomOff = ibIntCandidates[1].romOff
  local scanStart = math.max(0, intRomOff - 0x10000)
  local scanEnd = math.min(actualROMSize, intRomOff + 0x10000)
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
              if info and info.hasEnd and info.addr ~= cb2IntAddr and info.size >= 30 and info.size <= 500 then
                local dup = false
                for _, c in ipairs(ibCandidates) do if c.addr == info.addr then dup = true; break end end
                if not dup then table.insert(ibCandidates, info) end
              end
            end
          end
        end
      end
    end
  end

  table.sort(ibCandidates, function(a, b)
    if a.blCount ~= b.blCount then return a.blCount > b.blCount end
    return a.size > b.size
  end)

  for i, c in ipairs(ibCandidates) do
    log(string.format("  Candidate %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
    for j, bl in ipairs(c.blTargets) do
      log(string.format("    BL%d -> 0x%08X", j, bl.target))
    end
  end
end

local cb2InitBattle = nil
if #ibCandidates > 0 then
  cb2InitBattle = string.format("0x%08X", ibCandidates[1].addr)
  log(string.format("BEST CB2_InitBattle = %s", cb2InitBattle))
end

-- Step 3: CB2_ReturnToField
log("--- Step 3: CB2_ReturnToField ---")
local cb2Overworld = 0x080A89A5
local owRefs = findLiteralPoolRefs(cb2Overworld, actualROMSize)
log(string.format("Found %d refs to CB2_Overworld", #owRefs))

local retCandidates = {}
for _, litOff in ipairs(owRefs) do
  local funcStart = findContainingFunction(litOff)
  if funcStart then
    local info = analyzeFunction(funcStart, 256)
    if info and info.hasEnd and info.size >= 10 and info.size <= 200 then
      local dup = false
      for _, c in ipairs(retCandidates) do if c.addr == info.addr then dup = true; break end end
      if not dup then table.insert(retCandidates, info) end
    end
  end
end
table.sort(retCandidates, function(a, b) return a.size < b.size end)
for i, c in ipairs(retCandidates) do
  if i <= 10 then log(string.format("  %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount)) end
end

-- Step 4: gMain savedCallback check
log("--- Step 4: gMain struct ---")
local gMainBase = 0x02020648
local savedCbEntries = {}
for off = 0x00, 0x20, 0x04 do
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
  if ok then
    local isROM = val >= 0x08000000 and val < 0x0A000000
    local entry = string.format("gMain+0x%02X = 0x%08X%s", off, val, isROM and " (ROM ptr)" or "")
    table.insert(savedCbEntries, entry)
    log(entry)
  end
end

-- Write JSON results
writeFile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt", "writing")

local json = '{\n'
json = json .. '  "status": "complete",\n'
json = json .. '  "CB2_HandleStartBattle": "' .. string.format("0x%08X", CB2_HANDLE_START) .. '",\n'
json = json .. '  "CB2_InitBattleInternal": ' .. (cb2IntAddr and ('"' .. string.format("0x%08X", cb2IntAddr) .. '"') or 'null') .. ',\n'
json = json .. '  "CB2_InitBattle": ' .. (cb2InitBattle and ('"' .. cb2InitBattle .. '"') or 'null') .. ',\n'

-- ReturnToField candidates
json = json .. '  "CB2_ReturnToField_candidates": [\n'
for i, c in ipairs(retCandidates) do
  if i <= 10 then
    json = json .. string.format('    {"addr": "0x%08X", "size": %d, "blCount": %d}', c.addr, c.size, c.blCount)
    if i < math.min(#retCandidates, 10) then json = json .. ',' end
    json = json .. '\n'
  end
end
json = json .. '  ],\n'

-- savedCallback
json = json .. '  "savedCallback_check": [\n'
for i, e in ipairs(savedCbEntries) do
  json = json .. '    "' .. e:gsub('"', '\\"') .. '"'
  if i < #savedCbEntries then json = json .. ',' end
  json = json .. '\n'
end
json = json .. '  ],\n'

-- All candidates details
json = json .. '  "initBattleInternal_candidates": [\n'
for i, c in ipairs(ibIntCandidates) do
  json = json .. string.format('    {"addr": "0x%08X", "size": %d, "blCount": %d}', c.addr, c.size, c.blCount)
  if i < #ibIntCandidates then json = json .. ',' end
  json = json .. '\n'
end
json = json .. '  ],\n'

json = json .. '  "initBattle_candidates": [\n'
for i, c in ipairs(ibCandidates) do
  json = json .. string.format('    {"addr": "0x%08X", "size": %d, "blCount": %d, "BLs": [', c.addr, c.size, c.blCount)
  for j, bl in ipairs(c.blTargets) do
    json = json .. string.format('"0x%08X"', bl.target)
    if j < #c.blTargets then json = json .. ',' end
  end
  json = json .. ']}'
  if i < #ibCandidates then json = json .. ',' end
  json = json .. '\n'
end
json = json .. '  ]\n'

json = json .. '}\n'

writeFile(OUTPUT, json)
writeFile("C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt", "done")
log("=== Scanner complete ===")
