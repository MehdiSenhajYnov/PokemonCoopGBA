--[[
  Scanner v8: Find CB2_InitBattle via B (tail call) scan + savedCallback discovery.

  CB2_InitBattleInternal = 0x08036491 (found by v7)
  CB2_InitBattle tail-calls CB2_InitBattleInternal via B (not BL).

  Strategy:
  1. Scan ±4KB around CB2_InitBattleInternal for THUMB B instructions targeting it
  2. For each B instruction found, find the containing function
  3. CB2_InitBattle should have 4-7 BLs + 1 B (tail call) and be 40-200 bytes

  Also: scan for savedCallback by checking gMain+0x08 during overworld (after game loads)
  and searching expansion source patterns.
]]

local OUTPUT = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_results.json"
local PROGRESS = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA/_scan_progress.txt"
local CHUNK = 4096

local CB2_INT_INTERNAL = 0x08036491
local CB2_INT_INTERNAL_PC = 0x08036490  -- without THUMB bit
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

-- Decode THUMB B (unconditional, encoding T2: 11100 imm11)
local function decodeB(instr, pc)
  if (instr & 0xF800) ~= 0xE000 then return nil end
  local imm11 = instr & 0x07FF
  -- Sign extend 11-bit
  if imm11 >= 0x400 then imm11 = imm11 - 0x800 end
  return pc + 4 + imm11 * 2
end

local function findContainingFunction(romOff)
  local searchStart = math.max(0, romOff - 1024)
  local readLen = romOff - searchStart
  if readLen < 2 then return nil end
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, math.min(readLen, CHUNK))
  if not ok or not data then return nil end
  for pos = #data - 1, 1, -2 do
    if pos >= 1 and pos + 1 <= #data then
      local instr = strU16(data, pos)
      if instr and ((instr & 0xFF00) == 0xB500 or (instr & 0xFF00) == 0xB400
                 or (instr & 0xFF00) == 0xB580 or (instr & 0xFF00) == 0xB5F0
                 or (instr & 0xFF80) == 0xB500) then
        return searchStart + pos - 1
      end
    end
  end
  return nil
end

local function analyzeFunction(funcRomOff, maxSize)
  maxSize = maxSize or 512
  local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, funcRomOff, math.min(maxSize, CHUNK))
  if not ok or not data then return nil end
  local firstInstr = strU16(data, 1)
  if not firstInstr then return nil end
  -- Must start with PUSH containing LR
  if (firstInstr & 0xFF00) ~= 0xB500 and (firstInstr & 0xFF00) ~= 0xB400
     and (firstInstr & 0xFF00) ~= 0xB580 and (firstInstr & 0xFE00) ~= 0xB400
     and (firstInstr & 0xFF00) ~= 0xB5F0 then
    -- Check more broadly: any PUSH {... LR}
    if not ((firstInstr & 0xFE00) == 0xB400 or (firstInstr & 0xFE00) == 0xB500) then
      return nil
    end
  end

  local funcEnd = nil
  local blTargets = {}
  local bTargets = {}
  local ldrLiterals = {}
  local pos = 1
  while pos <= #data - 1 do
    local instr = strU16(data, pos)
    if not instr then break end
    -- POP {PC} or BX LR
    if pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
      funcEnd = pos + 2; break
    end
    -- Unconditional B
    if (instr & 0xF800) == 0xE000 then
      local bPC = 0x08000000 + funcRomOff + (pos - 1)
      local target = decodeB(instr, bPC)
      if target then
        bTargets[#bTargets + 1] = { offset = pos - 1, target = target }
      end
    end
    -- LDR Rd, [PC, #imm]
    if (instr & 0xF800) == 0x4800 then
      local imm8 = (instr & 0xFF) * 4
      local pcAligned = ((funcRomOff + pos - 1 + 4) & (~3))
      local litAddr = pcAligned + imm8
      local litLocalPos = litAddr - funcRomOff + 1
      if litLocalPos >= 1 and litLocalPos + 3 <= #data then
        local b0, b1, b2, b3 = string.byte(data, litLocalPos, litLocalPos + 3)
        if b0 and b1 and b2 and b3 then
          local litVal = b0 + b1*256 + b2*65536 + b3*16777216
          ldrLiterals[#ldrLiterals + 1] = { offset = pos-1, value = litVal }
        end
      end
    end
    -- BL
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
    bTargets = bTargets,
    ldrLiterals = ldrLiterals,
    blCount = #blTargets,
    hasEnd = funcEnd ~= nil
  }
end

writeFile(PROGRESS, "init_v8")

local S = {
  phase = "wait", frameCount = 0,
  bCandidates = {},
  ibCandidates = {},
  logs = {},
  savedCb = {},
  gmainDump = {},
}

local function log(msg) S.logs[#S.logs + 1] = msg; pcall(function() console:log(msg) end) end

callbacks:add("frame", function()
  S.frameCount = S.frameCount + 1
  if S.phase == "done" then return end

  local ok, err = pcall(function()

    if S.phase == "wait" then
      if S.frameCount >= 10 then S.phase = "scan_b" end
      return
    end

    -- Scan for B instructions targeting CB2_InitBattleInternal
    if S.phase == "scan_b" then
      writeFile(PROGRESS, "scanning B instructions")
      local intRomOff = CB2_INT_INTERNAL_PC - 0x08000000  -- 0x036490

      -- Search 8KB before and 2KB after
      local scanStart = math.max(0, intRomOff - 8192)
      local scanEnd = math.min(intRomOff + 2048, 0x02000000)

      for base = scanStart, scanEnd - 1, CHUNK do
        local readLen = math.min(CHUNK, scanEnd - base)
        local ok2, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, readLen)
        if ok2 and data then
          for pos = 1, #data - 1, 2 do
            local instr = strU16(data, pos)
            if instr and (instr & 0xF800) == 0xE000 then
              local pc = 0x08000000 + base + (pos - 1)
              local target = decodeB(instr, pc)
              if target and (target == CB2_INT_INTERNAL_PC or target == CB2_INT_INTERNAL) then
                local romPos = base + pos - 1
                S.bCandidates[#S.bCandidates + 1] = { romOff = romPos, pc = pc, instr = instr }
                log(string.format("  B to InitBattleInternal at ROM 0x%06X (PC 0x%08X, instr 0x%04X)", romPos, pc, instr))
              end
            end
          end
        end
      end

      log("Found " .. #S.bCandidates .. " B instructions to CB2_InitBattleInternal")
      S.phase = "analyze_b"
      return
    end

    -- Analyze containing functions for each B candidate
    if S.phase == "analyze_b" then
      writeFile(PROGRESS, "analyzing B callers")
      for _, bc in ipairs(S.bCandidates) do
        local funcStart = findContainingFunction(bc.romOff)
        if funcStart then
          local info = analyzeFunction(funcStart, 512)
          if info and info.hasEnd then
            local dup = false
            for _, c in ipairs(S.ibCandidates) do if c.addr == info.addr then dup = true; break end end
            if not dup then
              -- Check: should have a few BLs (4-10) and the B to InitBattleInternal
              local hasTailCall = false
              for _, bt in ipairs(info.bTargets) do
                if bt.target == CB2_INT_INTERNAL_PC or bt.target == CB2_INT_INTERNAL then
                  hasTailCall = true; break
                end
              end
              if hasTailCall then
                S.ibCandidates[#S.ibCandidates + 1] = info
                log(string.format("  CB2_InitBattle candidate: 0x%08X (%d bytes, %d BLs, %d Bs, end=%s)",
                  info.addr, info.size, info.blCount, #info.bTargets, tostring(info.hasEnd)))
                for j, bl in ipairs(info.blTargets) do
                  log(string.format("    BL%d -> 0x%08X", j, bl.target))
                end
                for j, bt in ipairs(info.bTargets) do
                  log(string.format("    B%d -> 0x%08X", j, bt.target))
                end
                for j, ldr in ipairs(info.ldrLiterals) do
                  log(string.format("    LDR =0x%08X at +0x%X", ldr.value, ldr.offset))
                end
              end
            end
          else
            log(string.format("  B at ROM 0x%06X -> func at 0x%06X: no end found or no valid prologue", bc.romOff, funcStart))
          end
        else
          log(string.format("  B at ROM 0x%06X -> no containing function", bc.romOff))
        end
      end

      -- Sort: prefer functions with more BLs (CB2_InitBattle has 5-7 calls)
      table.sort(S.ibCandidates, function(a, b)
        return a.blCount > b.blCount
      end)

      S.phase = "gmain_dump"
      return
    end

    -- Dump full gMain struct (extended range)
    if S.phase == "gmain_dump" then
      writeFile(PROGRESS, "dumping gMain")
      local gMainBase = 0x02020648
      local wramBase = gMainBase - 0x02000000

      -- Dump 128 bytes of gMain
      for off = 0x00, 0x7F, 0x04 do
        local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, wramBase + off)
        if ok2 then
          local isROM = val >= 0x08000000 and val < 0x0A000000
          local isEWRAM = val >= 0x02000000 and val < 0x02040000
          local tag = ""
          if isROM then tag = " ROM" elseif isEWRAM then tag = " EWRAM" end
          S.gmainDump[#S.gmainDump + 1] = string.format("gMain+0x%02X=0x%08X%s", off, val, tag)
        end
      end

      S.phase = "write"
      return
    end

    -- Write results
    if S.phase == "write" then
      writeFile(PROGRESS, "writing")

      local best = nil
      if #S.ibCandidates > 0 then best = S.ibCandidates[1].addr end

      local lines = {}
      lines[#lines + 1] = '{'
      lines[#lines + 1] = '  "status": "complete",'
      lines[#lines + 1] = '  "CB2_InitBattleInternal": "0x08036491",'
      lines[#lines + 1] = '  "CB2_InitBattle": ' .. (best and string.format('"0x%08X"', best) or 'null') .. ','

      lines[#lines + 1] = '  "b_instructions_found": ' .. #S.bCandidates .. ','

      lines[#lines + 1] = '  "initBattle_candidates": ['
      for i, c in ipairs(S.ibCandidates) do
        local blStr = ''
        for j, bl in ipairs(c.blTargets) do
          blStr = blStr .. string.format('"0x%08X"', bl.target)
          if j < #c.blTargets then blStr = blStr .. ',' end
        end
        local bStr = ''
        for j, bt in ipairs(c.bTargets) do
          bStr = bStr .. string.format('"0x%08X"', bt.target)
          if j < #c.bTargets then bStr = bStr .. ',' end
        end
        lines[#lines + 1] = string.format('    {"addr":"0x%08X","size":%d,"BLs":%d,"Bs":%d,"blTargets":[%s],"bTargets":[%s]}%s',
          c.addr, c.size, c.blCount, #c.bTargets, blStr, bStr, i < #S.ibCandidates and ',' or '')
      end
      lines[#lines + 1] = '  ],'

      lines[#lines + 1] = '  "gMain_dump": ['
      for i, e in ipairs(S.gmainDump) do
        lines[#lines + 1] = '    "' .. e .. '"' .. (i < #S.gmainDump and ',' or '')
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
    end
  end)

  if not ok then
    writeFile(OUTPUT, '{"status":"error","error":"' .. tostring(err):gsub('"', '\\"'):gsub('\n', ' ') .. '","phase":"' .. S.phase .. '"}')
    writeFile(PROGRESS, "error: " .. tostring(err))
    S.phase = "done"
  end
end)
