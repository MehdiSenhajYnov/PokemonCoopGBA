--[[
  gBattleResources Pointer Finder v2

  STRATEGY: The BattleResources struct (from pokeemerald-expansion) is:
    +0x00: secretBase ptr (EWRAM)
    +0x04: battleScriptsStack ptr (EWRAM)
    +0x08: battleCallbackStack ptr (EWRAM)
    +0x0C: beforeLvlUp ptr (EWRAM)
    +0x10: bufferA[0][512] (embedded, 2048 bytes total for 4 battlers)
    +0x810: bufferB[0][512] (embedded, 2048 bytes total for 4 battlers)
    +0x1010: transferBuffer[256]
    TOTAL: 0x1110 bytes (4368)

  SCAN 1: Search ALL of EWRAM for 4 consecutive EWRAM pointers.
          This is the START of the allocated BattleResources struct.

  SCAN 2: Once found, search ALL of EWRAM for a 4-byte value pointing
          to that struct address. That's gBattleResources (the variable).

  USAGE: Enter battle, wait for menu, press SELECT.
]]

console:log("=== gBattleResources FINDER v2 ===")
console:log("")

local frameCount = 0
local selectPrev = false

local function readU32(addr)
  if addr < 0x02000000 or addr > 0x0203FFFC then return nil end
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, addr - 0x02000000)
  if ok then return val else return nil end
end

local function readU8(addr)
  if addr < 0x02000000 or addr > 0x0203FFFF then return nil end
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, addr - 0x02000000)
  if ok then return val else return nil end
end

local function isEwramPtr(val)
  return val and val >= 0x02000100 and val <= 0x0203FFFF
end

local function hexDump(addr, len)
  local parts = {}
  for i = 0, math.min(len, 16) - 1 do
    local b = readU8(addr + i)
    if b then table.insert(parts, string.format("%02X", b)) end
  end
  return table.concat(parts, " ")
end

local function countNonZero(addr, len)
  local count = 0
  for i = 0, len - 1 do
    local b = readU8(addr + i)
    if b and b ~= 0 then count = count + 1 end
  end
  return count
end

local function doScan()
  console:log("")
  console:log("--- SCANNING ---")

  -- Verify battle state
  local btf = readU32(0x020090E8)
  console:log(string.format("  gBattleTypeFlags = 0x%08X %s",
    btf or 0, (btf and btf ~= 0) and "(IN BATTLE)" or "(NOT IN BATTLE!)"))
  if not btf or btf == 0 then
    console:log("  ERROR: Not in battle!")
    return
  end

  -- SCAN 1: Find 4 consecutive EWRAM pointers anywhere in EWRAM
  -- This is the allocated BattleResources struct
  console:log("")
  console:log("  SCAN 1: Looking for 4 consecutive EWRAM pointers (struct signature)...")

  local structCandidates = {}

  -- Read EWRAM in chunks for performance
  local CHUNK = 4096
  for base = 0, 0x3FFFC, CHUNK do
    local ok, data = pcall(emu.memory.wram.readRange, emu.memory.wram, base, CHUNK)
    if ok and data then
      -- Check every 4-byte aligned position
      for i = 1, #data - 15, 4 do
        local b = function(pos)
          return string.byte(data, pos) or 0
        end

        -- Read 4 u32 values
        local v0 = b(i) + b(i+1)*256 + b(i+2)*65536 + b(i+3)*16777216
        local v1 = b(i+4) + b(i+5)*256 + b(i+6)*65536 + b(i+7)*16777216
        local v2 = b(i+8) + b(i+9)*256 + b(i+10)*65536 + b(i+11)*16777216
        local v3 = b(i+12) + b(i+13)*256 + b(i+14)*65536 + b(i+15)*16777216

        if isEwramPtr(v0) and isEwramPtr(v1) and isEwramPtr(v2) and isEwramPtr(v3) then
          local structAddr = 0x02000000 + base + (i - 1)

          -- Additional check: all 4 pointers should be DIFFERENT (they point to different sub-structs)
          if v0 ~= v1 and v0 ~= v2 and v0 ~= v3 and v1 ~= v2 and v1 ~= v3 and v2 ~= v3 then
            -- Check if bufferA area (+0x10) has some data
            local bufNZ = countNonZero(structAddr + 0x10, 64)

            table.insert(structCandidates, {
              structAddr = structAddr,
              ptrs = {v0, v1, v2, v3},
              bufNZ = bufNZ,
            })
          end
        end
      end
    end
  end

  console:log(string.format("  Found %d locations with 4 consecutive unique EWRAM pointers", #structCandidates))
  console:log("")

  -- Sort by buffer data presence (more non-zero = more likely to be BattleResources)
  table.sort(structCandidates, function(a, b) return a.bufNZ > b.bufNZ end)

  -- Print candidates
  for i, c in ipairs(structCandidates) do
    if i > 20 then
      console:log(string.format("  ... and %d more", #structCandidates - 20))
      break
    end

    console:log(string.format("  [%d] STRUCT at 0x%08X  (bufferA non-zero: %d/64)",
      i, c.structAddr, c.bufNZ))
    console:log(string.format("       ptrs: 0x%08X 0x%08X 0x%08X 0x%08X",
      c.ptrs[1], c.ptrs[2], c.ptrs[3], c.ptrs[4]))
    console:log(string.format("       +0x10 (bufferA[0]): %s", hexDump(c.structAddr + 0x10, 16)))
    console:log(string.format("       +0x810 (bufferB[0]): %s", hexDump(c.structAddr + 0x810, 16)))
    console:log("")
  end

  -- SCAN 2: For the best struct candidates, find who points to them
  if #structCandidates > 0 then
    console:log("  SCAN 2: Finding gBattleResources variable (pointer to best struct)...")
    console:log("")

    -- Check top 5 candidates
    for ci = 1, math.min(5, #structCandidates) do
      local targetAddr = structCandidates[ci].structAddr
      local targetBytes = {
        targetAddr & 0xFF,
        (targetAddr >> 8) & 0xFF,
        (targetAddr >> 16) & 0xFF,
        (targetAddr >> 24) & 0xFF,
      }

      -- Scan all EWRAM for this address
      local refs = {}
      for base = 0, 0x3FFFC, CHUNK do
        local ok, data = pcall(emu.memory.wram.readRange, emu.memory.wram, base, CHUNK)
        if ok and data then
          for i = 1, #data - 3, 4 do
            if string.byte(data, i) == targetBytes[1] and
               string.byte(data, i+1) == targetBytes[2] and
               string.byte(data, i+2) == targetBytes[3] and
               string.byte(data, i+3) == targetBytes[4] then
              local refAddr = 0x02000000 + base + (i - 1)
              -- Don't count the struct itself or addresses very close to it
              if refAddr < targetAddr - 16 or refAddr > targetAddr + 0x1110 then
                table.insert(refs, refAddr)
              end
            end
          end
        end
      end

      if #refs > 0 then
        console:log(string.format("  STRUCT 0x%08X is referenced by:", targetAddr))
        for _, ref in ipairs(refs) do
          console:log(string.format("    >>> gBattleResources = 0x%08X <<<", ref))
        end
        console:log("")
      end
    end
  end

  -- Also scan near gBattleTypeFlags for other battle variables
  console:log("--- NEARBY BATTLE GLOBALS (0x020090E0 - 0x02009200) ---")
  console:log("")
  for addr = 0x020090E0, 0x020091FC, 4 do
    local val = readU32(addr)
    if val and val ~= 0 then
      local label = ""
      if addr == 0x020090E8 then label = " <-- gBattleTypeFlags" end
      if isEwramPtr(val) then label = label .. " [EWRAM PTR]" end
      console:log(string.format("  0x%08X = 0x%08X%s", addr, val, label))
    end
  end

  console:log("")
  console:log("=== SCAN COMPLETE ===")
end

local function onFrame()
  frameCount = frameCount + 1
  local ok, keys = pcall(function() return emu.memory.io:read16(0x0130) end)
  if not ok then return end
  local pressed = (~keys) & 0x000F
  local selectNow = (pressed & 0x0004) ~= 0
  if selectNow and not selectPrev then doScan() end
  selectPrev = selectNow
end

callbacks:add("frame", onFrame)

console:log("Instructions:")
console:log("  1. Enter a trainer battle")
console:log("  2. Wait for Fight/Bag/Pokemon/Run menu")
console:log("  3. Press SELECT to scan")
console:log("")
console:log("=== READY ===")
