--[[
  find_warp_functions.lua

  Scans the ROM to find warp-related function addresses:
  - SetCB2WarpAndLoadMap (calls WarpIntoMap + SetMainCallback2(CB2_LoadMap))
  - DoWarp / Task_WarpAndLoadMap
  - WarpIntoMap
  - SetMainCallback2

  Strategy: Search ROM for literal pool entries containing CB2_LoadMap (0x08007441).
  Each reference points to code that uses CB2_LoadMap as an argument to SetMainCallback2.
  Among these, SetCB2WarpAndLoadMap is a very small function (~8-16 bytes).
]]

local CB2_LOADMAP = 0x08007441    -- Known CB2_LoadMap address (THUMB)
local CB2_OVERWORLD = 0x080A89A5  -- Known CB2_Overworld address (THUMB)
local ROM_SIZE = 0x02000000       -- 32MB max ROM size (scan in chunks)

console:log("=== ROM Warp Function Scanner ===")
console:log(string.format("Searching ROM for references to CB2_LoadMap (0x%08X)...", CB2_LOADMAP))

-- Step 1: Find all 4-byte-aligned occurrences of CB2_LOADMAP in ROM
local refs = {}
local scanEnd = ROM_SIZE

-- First, determine actual ROM size (check for FF padding)
local testVal = 0
for checkAddr = 0x01000000, 0x02000000, 0x100000 do
  local ok, v = pcall(emu.memory.cart0.read32, emu.memory.cart0, checkAddr)
  if ok and v ~= 0xFFFFFFFF and v ~= 0 then
    scanEnd = checkAddr + 0x100000
  end
end
console:log(string.format("ROM scan range: 0x08000000 - 0x%08X", 0x08000000 + scanEnd))

-- Scan for literal pool entries
for offset = 0, scanEnd - 4, 4 do
  local ok, val = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
  if ok and val == CB2_LOADMAP then
    table.insert(refs, offset)
  end
end

console:log(string.format("\nFound %d literal pool references to CB2_LoadMap:", #refs))

-- Step 2: For each reference, analyze surrounding code
-- Literal pool entries are usually just AFTER the function code.
-- Look backwards for PUSH instruction (function prologue).
-- In THUMB mode: PUSH {regs} = 0xB4xx or 0xB5xx
-- PUSH {r4,lr} = 0xB510, PUSH {lr} = 0xB500

local candidates = {}

for _, litOffset in ipairs(refs) do
  local romAddr = 0x08000000 + litOffset

  -- Look backwards from the literal for a function prologue (max 64 bytes back)
  local funcStart = nil
  local funcSize = nil

  for back = 2, 64, 2 do
    local codeOffset = litOffset - back
    if codeOffset >= 0 then
      local ok, instr = pcall(emu.memory.cart0.read16, emu.memory.cart0, codeOffset)
      if ok then
        -- PUSH {regs[, lr]} = 0xB4xx or 0xB5xx
        local isPush = (instr & 0xFF00) == 0xB400 or (instr & 0xFF00) == 0xB500
        if isPush then
          funcStart = codeOffset
          funcSize = litOffset - codeOffset
          break
        end
      end
    end
  end

  if funcStart then
    local funcAddr = 0x08000000 + funcStart + 1  -- +1 for THUMB

    -- Read the function code
    local codeBytes = {}
    local blCount = 0
    local popCount = 0

    for i = 0, funcSize - 2, 2 do
      local ok, instr = pcall(emu.memory.cart0.read16, emu.memory.cart0, funcStart + i)
      if ok then
        table.insert(codeBytes, instr)
        -- Count BL instructions (upper half: 0xF000-0xF7FF, lower half: 0xF800-0xFFFF)
        if (instr & 0xF800) == 0xF000 then blCount = blCount + 0.5 end  -- BL upper
        if (instr & 0xF800) == 0xF800 then blCount = blCount + 0.5 end  -- BL lower
        -- Count POP {pc} (return)
        if (instr & 0xFF00) == 0xBD00 then popCount = popCount + 1 end
        -- BX LR
        if instr == 0x4770 then popCount = popCount + 1 end
      end
    end

    local info = {
      litAddr = romAddr,
      funcAddr = funcAddr,
      funcStart = funcStart,
      funcSize = funcSize,
      blCount = math.floor(blCount),
      popCount = popCount,
      codeBytes = codeBytes,
    }

    -- Classify the candidate
    -- SetCB2WarpAndLoadMap: very small (6-16 bytes), 2 BL calls (WarpIntoMap + SetMainCallback2)
    -- DoWarp/Task_WarpAndLoadMap: larger, more BL calls
    if funcSize <= 20 and info.blCount >= 2 then
      info.likely = "SetCB2WarpAndLoadMap"
    elseif funcSize <= 40 and info.blCount >= 3 then
      info.likely = "DoWarp (or similar)"
    else
      info.likely = "other"
    end

    table.insert(candidates, info)
  end
end

-- Step 3: Report findings
console:log(string.format("\n=== CANDIDATES (found %d functions referencing CB2_LoadMap) ===\n", #candidates))

-- Sort by likelihood (SetCB2WarpAndLoadMap first)
table.sort(candidates, function(a, b)
  if a.likely == "SetCB2WarpAndLoadMap" and b.likely ~= "SetCB2WarpAndLoadMap" then return true end
  if a.likely ~= "SetCB2WarpAndLoadMap" and b.likely == "SetCB2WarpAndLoadMap" then return false end
  return a.funcSize < b.funcSize
end)

for i, c in ipairs(candidates) do
  console:log(string.format("--- Candidate %d: %s ---", i, c.likely))
  console:log(string.format("  Function at: 0x%08X (THUMB)", c.funcAddr))
  console:log(string.format("  Literal at:  0x%08X", c.litAddr))
  console:log(string.format("  Code size:   %d bytes, %d BL calls", c.funcSize, c.blCount))

  -- Dump code bytes as hex
  local hexStr = ""
  for j, instr in ipairs(c.codeBytes) do
    hexStr = hexStr .. string.format("%04X ", instr)
    if j % 8 == 0 then
      console:log(string.format("  Code: %s", hexStr))
      hexStr = ""
    end
  end
  if #hexStr > 0 then
    console:log(string.format("  Code: %s", hexStr))
  end

  -- Also decode BL targets
  for j = 1, #c.codeBytes - 1 do
    local hi = c.codeBytes[j]
    local lo = c.codeBytes[j + 1]
    if (hi & 0xF800) == 0xF000 and (lo & 0xF800) == 0xF800 then
      -- BL instruction: decode target
      local offset11_hi = hi & 0x07FF
      local offset11_lo = lo & 0x07FF
      local fullOffset = (offset11_hi << 12) | (offset11_lo << 1)
      -- Sign extend from 23 bits
      if fullOffset >= 0x400000 then
        fullOffset = fullOffset - 0x800000
      end
      local blPC = 0x08000000 + c.funcStart + (j - 1) * 2 + 4
      local target = blPC + fullOffset
      console:log(string.format("  BL target: 0x%08X (from PC=0x%08X)", target, blPC - 4))
    end
  end

  console:log("")
end

-- Step 4: Highlight best candidate
local best = nil
for _, c in ipairs(candidates) do
  if c.likely == "SetCB2WarpAndLoadMap" then
    best = c
    break
  end
end

if best then
  console:log("=== BEST CANDIDATE FOR SetCB2WarpAndLoadMap ===")
  console:log(string.format("  Address: 0x%08X", best.funcAddr))
  console:log(string.format("  Size: %d bytes, %d BL calls", best.funcSize, best.blCount))
  console:log("")
  console:log("To test: set callback2 to this address instead of CB2_LoadMap directly.")
  console:log("This function calls WarpIntoMap() internally before setting CB2_LoadMap.")
else
  console:log("=== NO CLEAR SetCB2WarpAndLoadMap CANDIDATE FOUND ===")
  console:log("Try the candidates marked 'DoWarp' or check manually.")
end

-- Step 5: Also find SetMainCallback2 by looking at BL targets from ALL functions
-- that write to gMain.callback2 offset
console:log("\n=== Additional: Searching for references to CB2_Overworld (0x080A89A5) ===")
local owRefs = 0
for offset = 0, scanEnd - 4, 4 do
  local ok, val = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
  if ok and val == CB2_OVERWORLD then
    owRefs = owRefs + 1
  end
end
console:log(string.format("Found %d references to CB2_Overworld (for context)", owRefs))

console:log("\n=== SCAN COMPLETE ===")
