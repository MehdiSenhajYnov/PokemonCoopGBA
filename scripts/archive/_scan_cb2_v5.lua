--[[
  Scanner v5: Entire scan wrapped in pcall for error capture.
  Runs on frame 30 to ensure ROM is loaded.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local PROGRESS = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt"

local function writeFile(path, content)
  local f = io.open(path, "w")
  if f then f:write(content); f:close() end
end

writeFile(PROGRESS, "init_v5")

local frameCount = 0
local scanDone = false
local cb

cb = callbacks:add("frame", function()
  frameCount = frameCount + 1
  if frameCount == 2 then writeFile(PROGRESS, "frames_running") end
  if frameCount < 30 then return end
  if scanDone then return end
  scanDone = true
  cb:remove()

  writeFile(PROGRESS, "scan_starting")

  -- Wrap EVERYTHING in pcall
  local ok, err = pcall(function()
    local CHUNK = 4096
    local CB2_HANDLE_START = 0x08037B45

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
        local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
        if ok2 and data then
          for i = 1, #data - 3, 4 do
            local d0, d1, d2, d3 = string.byte(data, i, i + 3)
            if d0 == b0 and d1 == b1 and d2 == b2 and d3 == b3 then
              refs[#refs + 1] = base + i - 1
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
      local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
      if not ok2 or not data then return nil end
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
        local ok2, cData = pcall(emu.memory.cart0.readRange, emu.memory.cart0, chunkBase, chunkLen)
        if ok2 and cData then chunks[#chunks + 1] = cData end
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

    -- ROM size
    writeFile(PROGRESS, "detecting_rom_size")
    local actualROMSize = 0x02000000
    for testSize = 0x200000, 0x02000000, 0x200000 do
      local ok2 = pcall(emu.memory.cart0.readRange, emu.memory.cart0, testSize - 4, 4)
      if not ok2 then actualROMSize = testSize - 0x200000; break end
    end

    -- Step 1
    writeFile(PROGRESS, "step1_literal_scan")
    local handleStartRefs = findLiteralPoolRefs(CB2_HANDLE_START, actualROMSize)

    local ibIntCandidates = {}
    for _, litOff in ipairs(handleStartRefs) do
      local funcStart = findContainingFunction(litOff)
      if funcStart then
        local info = analyzeFunction(funcStart)
        if info and info.hasEnd and info.addr ~= CB2_HANDLE_START and info.size >= 100 and info.size <= 2000 then
          local dup = false
          for _, c in ipairs(ibIntCandidates) do if c.addr == info.addr then dup = true; break end end
          if not dup then ibIntCandidates[#ibIntCandidates + 1] = info end
        end
      end
    end
    table.sort(ibIntCandidates, function(a, b) return a.size > b.size end)

    local cb2IntAddr = nil
    if #ibIntCandidates > 0 then cb2IntAddr = ibIntCandidates[1].addr end

    -- Step 2
    writeFile(PROGRESS, "step2_initbattle")
    local ibCandidates = {}
    if cb2IntAddr then
      local intRefs = findLiteralPoolRefs(cb2IntAddr, actualROMSize)
      for _, litOff in ipairs(intRefs) do
        local funcStart = findContainingFunction(litOff)
        if funcStart then
          local info = analyzeFunction(funcStart, 512)
          if info and info.hasEnd and info.addr ~= cb2IntAddr and info.size >= 30 and info.size <= 500 then
            local dup = false
            for _, c in ipairs(ibCandidates) do if c.addr == info.addr then dup = true; break end end
            if not dup then ibCandidates[#ibCandidates + 1] = info end
          end
        end
      end

      -- BL scan
      local targetPC = cb2IntAddr & 0xFFFFFFFE
      local intRomOff = ibIntCandidates[1].romOff
      local scanStart = math.max(0, intRomOff - 0x10000)
      local scanEnd = math.min(actualROMSize, intRomOff + 0x10000)
      for base = scanStart, scanEnd - CHUNK, CHUNK do
        local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
        if ok2 and data then
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
                    if not dup then ibCandidates[#ibCandidates + 1] = info end
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
    end

    local cb2InitBattle = nil
    if #ibCandidates > 0 then cb2InitBattle = ibCandidates[1].addr end

    -- Step 3
    writeFile(PROGRESS, "step3_returntofield")
    local owRefs = findLiteralPoolRefs(0x080A89A5, actualROMSize)
    local retCandidates = {}
    for _, litOff in ipairs(owRefs) do
      local funcStart = findContainingFunction(litOff)
      if funcStart then
        local info = analyzeFunction(funcStart, 256)
        if info and info.hasEnd and info.size >= 10 and info.size <= 200 then
          local dup = false
          for _, c in ipairs(retCandidates) do if c.addr == info.addr then dup = true; break end end
          if not dup then retCandidates[#retCandidates + 1] = info end
        end
      end
    end
    table.sort(retCandidates, function(a, b) return a.size < b.size end)

    -- Step 4: gMain
    writeFile(PROGRESS, "step4_gmain")
    local gMainBase = 0x02020648
    local savedCb = {}
    for off = 0x00, 0x20, 0x04 do
      local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
      if ok2 then
        savedCb[#savedCb + 1] = string.format("gMain+0x%02X=0x%08X", off, val)
      end
    end

    -- Build JSON
    writeFile(PROGRESS, "writing_json")
    local lines = {}
    lines[#lines + 1] = '{'
    lines[#lines + 1] = '  "status": "complete",'
    lines[#lines + 1] = '  "romSize_MB": ' .. (actualROMSize / (1024*1024)) .. ','
    lines[#lines + 1] = '  "step1_refs": ' .. #handleStartRefs .. ','
    lines[#lines + 1] = '  "CB2_InitBattleInternal": ' .. (cb2IntAddr and string.format('"0x%08X"', cb2IntAddr) or 'null') .. ','
    lines[#lines + 1] = '  "CB2_InitBattle": ' .. (cb2InitBattle and string.format('"0x%08X"', cb2InitBattle) or 'null') .. ','

    lines[#lines + 1] = '  "initBattleInternal_candidates": ['
    for i, c in ipairs(ibIntCandidates) do
      lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d}%s', c.addr, c.size, c.blCount, i<#ibIntCandidates and ',' or '')
    end
    lines[#lines + 1] = '  ],'

    lines[#lines + 1] = '  "initBattle_candidates": ['
    for i, c in ipairs(ibCandidates) do
      local blStr = ''
      for j, bl in ipairs(c.blTargets) do
        blStr = blStr .. string.format('"0x%08X"', bl.target)
        if j < #c.blTargets then blStr = blStr .. ',' end
      end
      lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"targets":[%s]}%s', c.addr, c.size, c.blCount, blStr, i<#ibCandidates and ',' or '')
    end
    lines[#lines + 1] = '  ],'

    lines[#lines + 1] = '  "returnToField_candidates": ['
    for i, c in ipairs(retCandidates) do
      if i <= 10 then
        local blStr = ''
        for j, bl in ipairs(c.blTargets) do
          blStr = blStr .. string.format('"0x%08X"', bl.target)
          if j < #c.blTargets then blStr = blStr .. ',' end
        end
        lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"targets":[%s]}%s', c.addr, c.size, c.blCount, blStr, i<math.min(#retCandidates,10) and ',' or '')
      end
    end
    lines[#lines + 1] = '  ],'

    lines[#lines + 1] = '  "savedCallback_check": ['
    for i, e in ipairs(savedCb) do
      lines[#lines + 1] = '    "' .. e .. '"' .. (i<#savedCb and ',' or '')
    end
    lines[#lines + 1] = '  ]'

    lines[#lines + 1] = '}'

    writeFile(OUTPUT, table.concat(lines, '\n'))
    writeFile(PROGRESS, "done")
    pcall(function() console:log("=== Scanner v5 COMPLETE ===") end)
  end)

  if not ok then
    writeFile(OUTPUT, '{"status":"error","error":"' .. tostring(err):gsub('"', '\\"'):gsub('\n', ' ') .. '"}')
    writeFile(PROGRESS, "error: " .. tostring(err))
  end
end)
