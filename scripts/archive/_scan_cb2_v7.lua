--[[
  Scanner v7: Find CB2_InitBattle via BL scan (not literal pool).

  The compiler in pokeemerald-expansion uses BL (relative branch) to call
  SetMainCallback2, not literal pool LDR. So CB2_HandleStartBattle's address
  is passed as an argument via LDR to SetMainCallback2, and the literal pool
  ref IS there. But the containing function analysis was too strict.

  New approach:
  1. Find ALL literal pool refs to CB2_HandleStartBattle (even just 1)
  2. The containing function IS CB2_InitBattleInternal — relax size filter
  3. For CB2_InitBattle: search for BL instructions targeting CB2_InitBattleInternal
  4. Also find gMain.savedCallback by looking for functions that store to gMain+offset

  Additionally: check the 1 ref found and analyze its containing function WITHOUT size filter.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local PROGRESS = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt"
local CHUNK = 4096
local CHUNKS_PER_FRAME = 128
local CB2_HANDLE_START = 0x08037B45

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

local function findContainingFunction(litOff)
  local searchStart = math.max(0, litOff - 2048)
  local readLen = litOff - searchStart
  if readLen < 2 then return nil end
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, math.min(readLen, CHUNK))
  if not ok or not data then return nil end
  -- Try reading more if needed
  if readLen > CHUNK then
    local chunks = {data}
    for base = searchStart + CHUNK, searchStart + readLen - 1, CHUNK do
      local ok2, d2 = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, math.min(CHUNK, searchStart + readLen - base))
      if ok2 and d2 then chunks[#chunks+1] = d2 end
    end
    data = table.concat(chunks)
  end
  for pos = #data - 1, 1, -2 do
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
  maxSize = maxSize or 4096
  local readLen = math.min(maxSize, 8192)
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
  local ldrLiterals = {}
  local pos = 1
  while pos <= #data - 1 do
    local instr = strU16(data, pos)
    if not instr then break end
    if pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
      funcEnd = pos + 2; break
    end
    -- LDR Rd, [PC, #imm] (encoding T1: 0100 1xxx)
    if (instr & 0xF800) == 0x4800 then
      local rd = (instr >> 8) & 0x07
      local imm8 = (instr & 0xFF) * 4
      local pcAligned = ((funcRomOff + pos - 1 + 4) & (~3))
      local litAddr = pcAligned + imm8
      local litLocalPos = litAddr - funcRomOff + 1
      if litLocalPos >= 1 and litLocalPos + 3 <= #data then
        local b0, b1, b2, b3 = string.byte(data, litLocalPos, litLocalPos + 3)
        if b0 and b1 and b2 and b3 then
          local litVal = b0 + b1*256 + b2*65536 + b3*16777216
          ldrLiterals[#ldrLiterals+1] = { offset = pos-1, rd = rd, value = litVal, litAddr = litAddr }
        end
      end
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
    ldrLiterals = ldrLiterals,
    hasEnd = funcEnd ~= nil
  }
end

-- State machine
local S = {
  phase = "wait", frameCount = 0, romSize = 0,
  scan1Base = 0, scan1Refs = {},
  allAnalyzed = {},
  cb2IntAddr = nil, cb2IntInfo = nil,
  blScanBase = 0, blScanEnd = 0,
  ibCandidates = {},
  scan3Base = 0, scan3Refs = {},
  retCandidates = {},
  savedCb = {},
  logs = {},
}

local function log(msg) S.logs[#S.logs + 1] = msg; pcall(function() console:log(msg) end) end

writeFile(PROGRESS, "init_v7")

local frameCb
frameCb = callbacks:add("frame", function()
  S.frameCount = S.frameCount + 1

  local ok, err = pcall(function()

    if S.phase == "wait" then
      if S.frameCount >= 10 then S.phase = "detect_size" end
      return
    end

    if S.phase == "detect_size" then
      writeFile(PROGRESS, "detecting_rom")
      S.romSize = 0x02000000
      for ts = 0x200000, 0x02000000, 0x200000 do
        local ok2 = pcall(emu.memory.cart0.readRange, emu.memory.cart0, ts - 4, 4)
        if not ok2 then S.romSize = ts - 0x200000; break end
      end
      log("ROM size: " .. math.floor(S.romSize/(1024*1024)) .. "MB")
      S.phase = "scan1"
      S.scan1Base = 0
      return
    end

    -- Step 1: Find literal pool refs to CB2_HandleStartBattle
    if S.phase == "scan1" then
      writeFile(PROGRESS, "step1 " .. math.floor(S.scan1Base/(1024*1024)) .. "/" .. math.floor(S.romSize/(1024*1024)) .. "MB")
      local b0 = CB2_HANDLE_START & 0xFF
      local b1 = (CB2_HANDLE_START >> 8) & 0xFF
      local b2 = (CB2_HANDLE_START >> 16) & 0xFF
      local b3 = (CB2_HANDLE_START >> 24) & 0xFF
      local endBase = math.min(S.scan1Base + CHUNKS_PER_FRAME * CHUNK, S.romSize)
      for base = S.scan1Base, endBase - CHUNK, CHUNK do
        local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
        if ok2 and data then
          for i = 1, #data - 3, 4 do
            local d0, d1, d2, d3 = string.byte(data, i, i + 3)
            if d0 == b0 and d1 == b1 and d2 == b2 and d3 == b3 then
              S.scan1Refs[#S.scan1Refs + 1] = base + i - 1
            end
          end
        end
      end
      S.scan1Base = endBase
      if S.scan1Base >= S.romSize then
        log("Step 1: " .. #S.scan1Refs .. " literal pool refs to CB2_HandleStartBattle")
        S.phase = "analyze1"
      end
      return
    end

    -- Analyze ALL refs (no size filter this time)
    if S.phase == "analyze1" then
      writeFile(PROGRESS, "analyzing refs")
      for _, litOff in ipairs(S.scan1Refs) do
        local funcStart = findContainingFunction(litOff)
        if funcStart then
          local info = analyzeFunction(funcStart, 4096)
          if info then
            log(string.format("  Ref at ROM 0x%06X -> func 0x%08X (%d bytes, %d BLs, %d LDRs, end=%s)",
              litOff, info.addr, info.size, info.blCount, #info.ldrLiterals, tostring(info.hasEnd)))
            -- List the LDR literals that reference CB2_HandleStartBattle
            for _, ldr in ipairs(info.ldrLiterals) do
              if ldr.value == CB2_HANDLE_START then
                log(string.format("    LDR R%d, =0x%08X at +0x%X", ldr.rd, ldr.value, ldr.offset))
              end
            end
            -- List first 10 BL targets
            for j = 1, math.min(10, #info.blTargets) do
              log(string.format("    BL%d -> 0x%08X", j, info.blTargets[j].target))
            end
            S.allAnalyzed[#S.allAnalyzed + 1] = info

            -- If this is NOT CB2_HandleStartBattle itself, it's likely CB2_InitBattleInternal
            if info.addr ~= CB2_HANDLE_START then
              if not S.cb2IntAddr or info.size > (S.cb2IntInfo and S.cb2IntInfo.size or 0) then
                S.cb2IntAddr = info.addr
                S.cb2IntInfo = info
              end
            end
          else
            log(string.format("  Ref at ROM 0x%06X -> no valid function found", litOff))
          end
        else
          log(string.format("  Ref at ROM 0x%06X -> no containing function", litOff))
        end
      end

      if S.cb2IntAddr then
        log("CB2_InitBattleInternal = " .. string.format("0x%08X", S.cb2IntAddr))
        -- Setup BL scan for functions that BL to this address
        local intRomOff = S.cb2IntInfo.romOff
        S.blScanBase = math.max(0, intRomOff - 0x20000)
        S.blScanEnd = math.min(S.romSize, intRomOff + 0x20000)
        S.phase = "bl_scan"
      else
        log("WARNING: No CB2_InitBattleInternal found")
        -- Try wider: maybe the ref IS in CB2_HandleStartBattle itself (it stores its own address)
        -- Or try scanning for BL to CB2_HandleStartBattle
        S.blScanBase = 0
        S.blScanEnd = S.romSize
        S.cb2IntAddr = CB2_HANDLE_START  -- Use CB2_HandleStartBattle as the target for BL scan
        S.phase = "bl_scan"
      end
      return
    end

    -- BL scan: find functions that BL to CB2_InitBattleInternal (or CB2_HandleStartBattle)
    if S.phase == "bl_scan" then
      writeFile(PROGRESS, "BL_scan " .. math.floor((S.blScanBase - math.max(0, S.blScanBase))/1024) .. "KB")
      local targetPC = S.cb2IntAddr & 0xFFFFFFFE
      local endBase = math.min(S.blScanBase + CHUNKS_PER_FRAME * CHUNK, S.blScanEnd)

      for base = S.blScanBase, endBase - CHUNK, CHUNK do
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
                  local info = analyzeFunction(funcStart, 1024)
                  if info and info.hasEnd and info.addr ~= S.cb2IntAddr and info.addr ~= CB2_HANDLE_START then
                    local dup = false
                    for _, c in ipairs(S.ibCandidates) do if c.addr == info.addr then dup = true; break end end
                    if not dup then
                      S.ibCandidates[#S.ibCandidates + 1] = info
                      log(string.format("  BL caller: 0x%08X (%d bytes, %d BLs)", info.addr, info.size, info.blCount))
                    end
                  end
                end
              end
            end
          end
        end
      end

      S.blScanBase = endBase
      if S.blScanBase >= S.blScanEnd then
        table.sort(S.ibCandidates, function(a, b)
          if a.blCount ~= b.blCount then return a.blCount > b.blCount end
          return a.size > b.size
        end)
        log("CB2_InitBattle candidates: " .. #S.ibCandidates)
        for i, c in ipairs(S.ibCandidates) do
          if i <= 5 then
            log(string.format("  %d: 0x%08X (%d bytes, %d BLs)", i, c.addr, c.size, c.blCount))
            for j, bl in ipairs(c.blTargets) do
              log(string.format("    BL%d -> 0x%08X", j, bl.target))
            end
          end
        end
        S.phase = "scan3"
        S.scan3Base = 0
      end
      return
    end

    -- Step 3: CB2_ReturnToField via CB2_Overworld refs
    if S.phase == "scan3" then
      writeFile(PROGRESS, "step3 " .. math.floor(S.scan3Base/(1024*1024)) .. "/" .. math.floor(S.romSize/(1024*1024)) .. "MB")
      local CB2_OW = 0x080A89A5
      local b0 = CB2_OW & 0xFF
      local b1 = (CB2_OW >> 8) & 0xFF
      local b2 = (CB2_OW >> 16) & 0xFF
      local b3 = (CB2_OW >> 24) & 0xFF
      local endBase = math.min(S.scan3Base + CHUNKS_PER_FRAME * CHUNK, S.romSize)
      for base = S.scan3Base, endBase - CHUNK, CHUNK do
        local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
        if ok2 and data then
          for i = 1, #data - 3, 4 do
            local d0, d1, d2, d3 = string.byte(data, i, i + 3)
            if d0 == b0 and d1 == b1 and d2 == b2 and d3 == b3 then
              S.scan3Refs[#S.scan3Refs + 1] = base + i - 1
            end
          end
        end
      end
      S.scan3Base = endBase
      if S.scan3Base >= S.romSize then
        log("Step 3: " .. #S.scan3Refs .. " refs to CB2_Overworld")
        S.phase = "analyze3"
      end
      return
    end

    if S.phase == "analyze3" then
      writeFile(PROGRESS, "step3 analyze")
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
      log("ReturnToField candidates: " .. #S.retCandidates)
      for i, c in ipairs(S.retCandidates) do
        if i <= 5 then log(string.format("  %d: 0x%08X (%d bytes)", i, c.addr, c.size)) end
      end
      S.phase = "gmain"
      return
    end

    if S.phase == "gmain" then
      writeFile(PROGRESS, "gmain")
      local gMainBase = 0x02020648
      for off = 0x00, 0x30, 0x04 do
        local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBase - 0x02000000 + off)
        if ok2 then
          local isROM = val >= 0x08000000 and val < 0x0A000000
          S.savedCb[#S.savedCb + 1] = string.format("gMain+0x%02X=0x%08X%s", off, val, isROM and " ROM" or "")
        end
      end
      S.phase = "write"
      return
    end

    if S.phase == "write" then
      writeFile(PROGRESS, "writing")

      local cb2IB = nil
      if #S.ibCandidates > 0 then cb2IB = S.ibCandidates[1].addr end

      local lines = {}
      lines[#lines + 1] = '{'
      lines[#lines + 1] = '  "status": "complete",'
      lines[#lines + 1] = '  "romSize_MB": ' .. math.floor(S.romSize/(1024*1024)) .. ','
      lines[#lines + 1] = '  "CB2_InitBattleInternal": ' .. (S.cb2IntAddr and S.cb2IntAddr ~= CB2_HANDLE_START and string.format('"0x%08X"', S.cb2IntAddr) or 'null') .. ','
      lines[#lines + 1] = '  "CB2_InitBattle": ' .. (cb2IB and string.format('"0x%08X"', cb2IB) or 'null') .. ','

      lines[#lines + 1] = '  "allRefs": ['
      for i, c in ipairs(S.allAnalyzed) do
        lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"hasEnd":%s}%s',
          c.addr, c.size, c.blCount, tostring(c.hasEnd), i<#S.allAnalyzed and ',' or '')
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "initBattle_candidates": ['
      for i, c in ipairs(S.ibCandidates) do
        if i <= 10 then
          local blStr = ''
          for j, bl in ipairs(c.blTargets) do
            blStr = blStr .. string.format('"0x%08X"', bl.target)
            if j < #c.blTargets then blStr = blStr .. ',' end
          end
          lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"targets":[%s]}%s',
            c.addr, c.size, c.blCount, blStr, i < math.min(#S.ibCandidates, 10) and ',' or '')
        end
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "returnToField_candidates": ['
      for i, c in ipairs(S.retCandidates) do
        if i <= 10 then
          lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d}%s',
            c.addr, c.size, c.blCount, i < math.min(#S.retCandidates, 10) and ',' or '')
        end
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "savedCallback_check": ['
      for i, e in ipairs(S.savedCb) do
        lines[#lines + 1] = '    "' .. e .. '"' .. (i < #S.savedCb and ',' or '')
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "logs": ['
      for i, l in ipairs(S.logs) do
        lines[#lines + 1] = '    "' .. l:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"' .. (i < #S.logs and ',' or '')
      end
      lines[#lines + 1] = '  ]'
      lines[#lines + 1] = '}'

      writeFile(OUTPUT, table.concat(lines, '\n'))
      writeFile(PROGRESS, "done")
      S.phase = "done"
      -- Don't try to remove cb, just set done flag
    end

  end)

  if not ok then
    writeFile(OUTPUT, '{"status":"error","error":"' .. tostring(err):gsub('"', '\\"'):gsub('\n', ' ') .. '","phase":"' .. S.phase .. '"}')
    writeFile(PROGRESS, "error: " .. tostring(err))
    S.phase = "done"
  end

  if S.phase == "done" then
    -- Just keep the callback running doing nothing, it's cheaper than trying to remove it
  end
end)
