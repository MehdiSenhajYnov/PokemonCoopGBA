--[[
  BattleResources Struct Layout Dumper

  Reads the gBattleResources pointer at 0x02023A18, dereferences it,
  and dumps the first 256 bytes to determine where the pointer fields
  end and bufferA begins.

  Also checks 0x810 offset for bufferB, and tries to find the command
  byte pattern that identifies bufferA[0].

  USAGE: Enter battle, wait for menu, press SELECT.
]]

console:log("=== BATTLE STRUCT DUMPER ===")
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

local function isPtr(val)
  if not val or val == 0 then return false end
  -- EWRAM pointer
  if val >= 0x02000100 and val <= 0x0203FFFF then return true end
  -- ROM pointer
  if val >= 0x08000000 and val <= 0x09FFFFFF then return true end
  return false
end

local function hexLine(addr, count)
  local parts = {}
  for i = 0, count - 1 do
    local b = readU8(addr + i)
    table.insert(parts, b and string.format("%02X", b) or "??")
  end
  return table.concat(parts, " ")
end

local function doScan()
  console:log("")
  console:log("--- DUMPING gBattleResources STRUCT ---")

  -- Read pointer
  local ptr = readU32(0x02023A18)
  if not ptr or ptr == 0 then
    console:log("  gBattleResources (0x02023A18) = NULL — not in battle!")
    return
  end

  console:log(string.format("  gBattleResources (0x02023A18) = 0x%08X", ptr))
  console:log("")

  -- Dump first 128 bytes as u32 values, identify pointers vs data
  console:log("  STRUCT HEADER (first 128 bytes as u32):")
  console:log("  Offset  Value       Type")
  console:log("  ------  ----------  ----")

  local lastPtrOffset = -1
  for off = 0, 124, 4 do
    local val = readU32(ptr + off)
    local valStr = val and string.format("0x%08X", val) or "????????"
    local typeStr = ""

    if val then
      if val >= 0x02000100 and val <= 0x0203FFFF then
        typeStr = "EWRAM PTR"
        lastPtrOffset = off
      elseif val >= 0x08000000 and val <= 0x09FFFFFF then
        typeStr = "ROM PTR"
        lastPtrOffset = off
      elseif val == 0 then
        typeStr = "zero"
      elseif val <= 0xFF then
        typeStr = string.format("small (%d)", val)
      elseif val <= 0xFFFF then
        typeStr = string.format("u16? (%d)", val)
      else
        typeStr = "data"
      end
    end

    console:log(string.format("  +0x%03X  %s  %s", off, valStr, typeStr))
  end

  console:log("")
  console:log(string.format("  Last pointer field at offset: +0x%03X", lastPtrOffset))
  console:log(string.format("  => bufferA likely starts at: +0x%03X", lastPtrOffset + 4))
  console:log("")

  -- Check candidate bufferA locations
  local bufferAStart = lastPtrOffset + 4
  console:log(string.format("  Candidate bufferA[0] at +0x%03X:", bufferAStart))
  console:log(string.format("    %s", hexLine(ptr + bufferAStart, 32)))
  console:log("")

  -- Check vanilla offset (+0x10) just in case
  if bufferAStart ~= 0x10 then
    console:log("  Vanilla bufferA offset (+0x10) for comparison:")
    console:log(string.format("    %s", hexLine(ptr + 0x10, 32)))
    console:log("")
  end

  -- Try to find bufferB relative to bufferA
  -- bufferB should be at bufferA + 4*512 = bufferA + 0x800
  local bufferBStart = bufferAStart + 0x800
  console:log(string.format("  Candidate bufferB[0] at +0x%03X (bufferA + 0x800):", bufferBStart))
  if ptr + bufferBStart <= 0x0203FFFF then
    console:log(string.format("    %s", hexLine(ptr + bufferBStart, 32)))
  else
    console:log("    OUT OF EWRAM RANGE")
  end
  console:log("")

  -- Also check +0x810 (vanilla offset)
  if bufferBStart ~= 0x810 then
    console:log("  Vanilla bufferB offset (+0x810) for comparison:")
    if ptr + 0x810 <= 0x0203FFFF then
      console:log(string.format("    %s", hexLine(ptr + 0x810, 32)))
    else
      console:log("    OUT OF EWRAM RANGE")
    end
    console:log("")
  end

  -- Count total struct size (last non-zero byte)
  local structEnd = 0
  for off = 0, 0x1200, 4 do
    if ptr + off > 0x0203FFFC then break end
    local val = readU32(ptr + off)
    if val and val ~= 0 then
      structEnd = off + 4
    end
  end
  console:log(string.format("  Estimated struct size: 0x%04X (%d bytes)", structEnd, structEnd))
  console:log(string.format("  (Vanilla size: 0x1110 = 4368 bytes)"))
  console:log("")

  -- Summary
  console:log("  === SUMMARY ===")
  console:log(string.format("  gBattleResources variable:  0x02023A18"))
  console:log(string.format("  gBattleResources pointer:   0x%08X", ptr))
  console:log(string.format("  bufferA[0] offset:          +0x%03X (absolute: 0x%08X)", bufferAStart, ptr + bufferAStart))
  console:log(string.format("  bufferB[0] offset:          +0x%03X (absolute: 0x%08X)", bufferBStart, ptr + bufferBStart))
  console:log(string.format("  struct size:                ~0x%04X bytes", structEnd))
  console:log("")

  -- Also dump the pointer table for reference
  console:log("  POINTER TABLE:")
  for off = 0, lastPtrOffset, 4 do
    local val = readU32(ptr + off)
    if val and isPtr(val) then
      console:log(string.format("    [%d] +0x%02X = 0x%08X", off / 4, off, val))
    end
  end

  console:log("")
  console:log("=== DUMP COMPLETE ===")
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
console:log("  1. Enter battle, wait for Fight/Bag/Pokemon/Run")
console:log("  2. Press SELECT to dump struct layout")
console:log("")
console:log("=== READY ===")
