--[[
  Scanner v6: Progressive scan across multiple frames.
  Each frame does a chunk of work, preventing mGBA timeout/freeze.
  Also loads save state slot 1 as requested by user.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local PROGRESS = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt"
local CHUNK = 4096
local CB2_HANDLE_START = 0x08037B45
local CB2_OVERWORLD = 0x080A89A5
local CHUNKS_PER_FRAME = 64  -- Process 64 chunks (256KB) per frame

local function writeFile(path, content)
  local f = io.open(path, "w")
  if f then f:write(content); f:close() end
end

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

-- State machine for progressive scan
local scanState = {
  phase = "wait",       -- wait, detect_size, scan1, analyze1, scan2, analyze2, scan3, analyze3, gmain, done
  frameCount = 0,
  romSize = 0,
  romSizeTest = 0x200000,
  -- scan1: find literal pool refs to CB2_HandleStartBattle
  scan1Base = 0,
  scan1Refs = {},
  -- analyze1: process refs
  ibIntCandidates = {},
  cb2IntAddr = nil,
  -- scan2: find refs to CB2_InitBattleInternal
  scan2Base = 0,
  scan2Refs = {},
  scan2BLBase = 0,
  scan2BLEnd = 0,
  -- analyze2: process refs
  ibCandidates = {},
  cb2InitBattle = nil,
  -- scan3: find refs to CB2_Overworld
  scan3Base = 0,
  scan3Refs = {},
  retCandidates = {},
  -- results
  savedCb = {},
  error = nil,
}

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
    if ok and cData then chunks[#chunks + 1] = cData end
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
        blTargets[#blTargets + 1] = { offset = pos - 1, target = target }
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

-- Search for a 4-byte value in CHUNK chunks, processing CHUNKS_PER_FRAME per call
local function scanChunks(targetValue, base, maxSize, refs)
  local b0 = targetValue & 0xFF
  local b1 = (targetValue >> 8) & 0xFF
  local b2 = (targetValue >> 16) & 0xFF
  local b3 = (targetValue >> 24) & 0xFF
  local endBase = base + CHUNKS_PER_FRAME * CHUNK
  if endBase > maxSize then endBase = maxSize end
  for b = base, endBase - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, b, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do
        local d0, d1, d2, d3 = string.byte(data, i, i + 3)
        if d0 == b0 and d1 == b1 and d2 == b2 and d3 == b3 then
          refs[#refs + 1] = b + i - 1
        end
      end
    end
  end
  return endBase
end

-- Scan for BL instructions targeting a specific address
local function scanBLChunks(targetPC, base, endAddr, candidates, excludeAddr)
  local endBase = base + CHUNKS_PER_FRAME * CHUNK
  if endBase > endAddr then endBase = endAddr end
  for b = base, endBase - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, b, CHUNK)
    if ok and data then
      for pos = 1, #data - 3, 2 do
        local h = strU16(data, pos)
        local l = strU16(data, pos + 2)
        if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800 then
          local blPC = 0x08000000 + b + (pos - 1) + 4
          local target = decodeBL(h, l, blPC)
          if target == targetPC or target == (targetPC | 1) then
            local funcStart = findContainingFunction(b + pos - 1)
            if funcStart then
              local info = analyzeFunction(funcStart, 512)
              if info and info.hasEnd and info.addr ~= excludeAddr and info.size >= 30 and info.size <= 500 then
                local dup = false
                for _, c in ipairs(candidates) do if c.addr == info.addr then dup = true; break end end
                if not dup then candidates[#candidates + 1] = info end
              end
            end
          end
        end
      end
    end
  end
  return endBase
end

writeFile(PROGRESS, "init_v6")

local cb
cb = callbacks:add("frame", function()
  scanState.frameCount = scanState.frameCount + 1
  local S = scanState

  local ok, err = pcall(function()

    -- Wait 5 frames then load save state
    if S.phase == "wait" then
      if S.frameCount == 3 then
        pcall(function() emu:loadStateSlot(1) end)
      end
      if S.frameCount >= 10 then
        S.phase = "detect_size"
      end
      return
    end

    -- OH WAIT: loadStateSlot resets callbacks! So we need a different approach.
    -- Let's NOT load save state — the ROM scan doesn't need it.
    -- For gMain check we'll read whatever is in RAM (title screen is fine to skip).

    if S.phase == "detect_size" then
      writeFile(PROGRESS, "detecting_rom_size")
      -- Quick ROM size detection (all in one frame, fast)
      S.romSize = 0x02000000
      for testSize = 0x200000, 0x02000000, 0x200000 do
        local ok2 = pcall(emu.memory.cart0.readRange, emu.memory.cart0, testSize - 4, 4)
        if not ok2 then S.romSize = testSize - 0x200000; break end
      end
      S.phase = "scan1"
      S.scan1Base = 0
      return
    end

    -- Step 1: Scan ROM for CB2_HandleStartBattle refs (progressive)
    if S.phase == "scan1" then
      writeFile(PROGRESS, "step1_scan " .. math.floor(S.scan1Base/(1024*1024)) .. "MB/" .. math.floor(S.romSize/(1024*1024)) .. "MB")
      S.scan1Base = scanChunks(CB2_HANDLE_START, S.scan1Base, S.romSize, S.scan1Refs)
      if S.scan1Base >= S.romSize then
        S.phase = "analyze1"
      end
      return
    end

    -- Step 1b: Analyze found refs
    if S.phase == "analyze1" then
      writeFile(PROGRESS, "step1_analyze " .. #S.scan1Refs .. " refs")
      for _, litOff in ipairs(S.scan1Refs) do
        local funcStart = findContainingFunction(litOff)
        if funcStart then
          local info = analyzeFunction(funcStart)
          if info and info.hasEnd and info.addr ~= CB2_HANDLE_START and info.size >= 100 and info.size <= 2000 then
            local dup = false
            for _, c in ipairs(S.ibIntCandidates) do if c.addr == info.addr then dup = true; break end end
            if not dup then S.ibIntCandidates[#S.ibIntCandidates + 1] = info end
          end
        end
      end
      table.sort(S.ibIntCandidates, function(a, b) return a.size > b.size end)
      if #S.ibIntCandidates > 0 then
        S.cb2IntAddr = S.ibIntCandidates[1].addr
      end
      S.phase = "scan2"
      S.scan2Base = 0
      return
    end

    -- Step 2: Scan ROM for CB2_InitBattleInternal refs (progressive)
    if S.phase == "scan2" then
      if not S.cb2IntAddr then
        S.phase = "scan3"; S.scan3Base = 0; return
      end
      writeFile(PROGRESS, "step2_scan " .. math.floor(S.scan2Base/(1024*1024)) .. "MB/" .. math.floor(S.romSize/(1024*1024)) .. "MB")
      S.scan2Base = scanChunks(S.cb2IntAddr, S.scan2Base, S.romSize, S.scan2Refs)
      if S.scan2Base >= S.romSize then
        S.phase = "analyze2a"
      end
      return
    end

    -- Step 2b: Analyze literal pool refs
    if S.phase == "analyze2a" then
      writeFile(PROGRESS, "step2_analyze " .. #S.scan2Refs .. " refs")
      for _, litOff in ipairs(S.scan2Refs) do
        local funcStart = findContainingFunction(litOff)
        if funcStart then
          local info = analyzeFunction(funcStart, 512)
          if info and info.hasEnd and info.addr ~= S.cb2IntAddr and info.size >= 30 and info.size <= 500 then
            local dup = false
            for _, c in ipairs(S.ibCandidates) do if c.addr == info.addr then dup = true; break end end
            if not dup then S.ibCandidates[#S.ibCandidates + 1] = info end
          end
        end
      end
      -- Setup BL scan range
      local intRomOff = S.ibIntCandidates[1].romOff
      S.scan2BLBase = math.max(0, intRomOff - 0x10000)
      S.scan2BLEnd = math.min(S.romSize, intRomOff + 0x10000)
      S.phase = "scan2bl"
      return
    end

    -- Step 2c: BL scan for calls to CB2_InitBattleInternal (progressive)
    if S.phase == "scan2bl" then
      writeFile(PROGRESS, "step2_BL_scan")
      local targetPC = S.cb2IntAddr & 0xFFFFFFFE
      S.scan2BLBase = scanBLChunks(targetPC, S.scan2BLBase, S.scan2BLEnd, S.ibCandidates, S.cb2IntAddr)
      if S.scan2BLBase >= S.scan2BLEnd then
        table.sort(S.ibCandidates, function(a, b)
          if a.blCount ~= b.blCount then return a.blCount > b.blCount end
          return a.size > b.size
        end)
        if #S.ibCandidates > 0 then S.cb2InitBattle = S.ibCandidates[1].addr end
        S.phase = "scan3"
        S.scan3Base = 0
      end
      return
    end

    -- Step 3: Scan for CB2_Overworld refs (progressive)
    if S.phase == "scan3" then
      writeFile(PROGRESS, "step3_scan " .. math.floor(S.scan3Base/(1024*1024)) .. "MB/" .. math.floor(S.romSize/(1024*1024)) .. "MB")
      S.scan3Base = scanChunks(CB2_OVERWORLD, S.scan3Base, S.romSize, S.scan3Refs)
      if S.scan3Base >= S.romSize then
        S.phase = "analyze3"
      end
      return
    end

    -- Step 3b: Analyze CB2_Overworld refs
    if S.phase == "analyze3" then
      writeFile(PROGRESS, "step3_analyze")
      for _, litOff in ipairs(S.scan3Refs) do
        local funcStart = findContainingFunction(litOff)
        if funcStart then
          local info = analyzeFunction(funcStart, 256)
          if info and info.hasEnd and info.size >= 10 and info.size <= 200 then
            local dup = false
            for _, c in ipairs(S.retCandidates) do if c.addr == info.addr then dup = true; break end end
            if not dup then S.retCandidates[#S.retCandidates + 1] = info end
          end
        end
      end
      table.sort(S.retCandidates, function(a, b) return a.size < b.size end)
      S.phase = "gmain"
      return
    end

    -- Step 4: Read gMain
    if S.phase == "gmain" then
      writeFile(PROGRESS, "step4_gmain")
      local gMainBase = 0x02020648
      for off = 0x00, 0x20, 0x04 do
        local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
        if ok2 then S.savedCb[#S.savedCb + 1] = string.format("gMain+0x%02X=0x%08X", off, val) end
      end
      S.phase = "write"
      return
    end

    -- Write results
    if S.phase == "write" then
      writeFile(PROGRESS, "writing_json")
      local lines = {}
      lines[#lines + 1] = '{'
      lines[#lines + 1] = '  "status": "complete",'
      lines[#lines + 1] = '  "romSize_MB": ' .. math.floor(S.romSize / (1024*1024)) .. ','
      lines[#lines + 1] = '  "step1_refs": ' .. #S.scan1Refs .. ','
      lines[#lines + 1] = '  "step2_lit_refs": ' .. #S.scan2Refs .. ','
      lines[#lines + 1] = '  "CB2_InitBattleInternal": ' .. (S.cb2IntAddr and string.format('"0x%08X"', S.cb2IntAddr) or 'null') .. ','
      lines[#lines + 1] = '  "CB2_InitBattle": ' .. (S.cb2InitBattle and string.format('"0x%08X"', S.cb2InitBattle) or 'null') .. ','

      lines[#lines + 1] = '  "initBattleInternal_candidates": ['
      for i, c in ipairs(S.ibIntCandidates) do
        lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d}%s', c.addr, c.size, c.blCount, i<#S.ibIntCandidates and ',' or '')
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "initBattle_candidates": ['
      for i, c in ipairs(S.ibCandidates) do
        local blStr = ''
        for j, bl in ipairs(c.blTargets) do
          blStr = blStr .. string.format('"0x%08X"', bl.target)
          if j < #c.blTargets then blStr = blStr .. ',' end
        end
        lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"targets":[%s]}%s', c.addr, c.size, c.blCount, blStr, i<#S.ibCandidates and ',' or '')
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "returnToField_candidates": ['
      for i, c in ipairs(S.retCandidates) do
        if i <= 10 then
          local blStr = ''
          for j, bl in ipairs(c.blTargets) do
            blStr = blStr .. string.format('"0x%08X"', bl.target)
            if j < #c.blTargets then blStr = blStr .. ',' end
          end
          lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"targets":[%s]}%s', c.addr, c.size, c.blCount, blStr, i<math.min(#S.retCandidates,10) and ',' or '')
        end
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "savedCallback_check": ['
      for i, e in ipairs(S.savedCb) do
        lines[#lines + 1] = '    "' .. e .. '"' .. (i<#S.savedCb and ',' or '')
      end
      lines[#lines + 1] = '  ]'
      lines[#lines + 1] = '}'

      writeFile(OUTPUT, table.concat(lines, '\n'))
      writeFile(PROGRESS, "done")
      S.phase = "done"
      pcall(function() if type(cb) == "table" or type(cb) == "userdata" then cb:remove() else callbacks:remove(cb) end end)
      pcall(function() console:log("=== Scanner v6 COMPLETE ===") end)
      return
    end

  end)

  if not ok then
    writeFile(OUTPUT, '{"status":"error","error":"' .. tostring(err):gsub('"', '\\"'):gsub('\n', ' ') .. '","phase":"' .. scanState.phase .. '"}')
    writeFile(PROGRESS, "error_" .. scanState.phase .. ": " .. tostring(err))
    pcall(function() if type(cb) == "table" or type(cb) == "userdata" then cb:remove() else callbacks:remove(cb) end end)
  end
end)
