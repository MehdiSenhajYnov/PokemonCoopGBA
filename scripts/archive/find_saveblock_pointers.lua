--[[
  Phase 0.3 - Find SaveBlock Pointers (Dynamic Memory Mode)

  Copy-paste this into mGBA console if offsets are dynamic
  (i.e., addresses change between sessions)

  SaveBlock pointers are usually in IWRAM (0x03000000 - 0x03007FFF)
  and point to structures in WRAM (0x02000000 - 0x0203FFFF)
]]

print("=== Searching for SaveBlock Pointers ===")
print("")

local iwram_start = 0x03000000
local iwram_end = 0x03007FFF
local candidates = {}

print(string.format("Scanning IWRAM range: 0x%08X - 0x%08X", iwram_start, iwram_end))
print("Looking for 4-byte pointers that point to WRAM...")
print("")

-- Scan IWRAM for potential pointers
for addr = iwram_start, iwram_end, 4 do
  local success, ptr = pcall(function()
    return memory.read32(addr)
  end)

  if success and ptr then
    -- Check if pointer is valid WRAM address
    if ptr >= 0x02000000 and ptr <= 0x0203FFFF then
      table.insert(candidates, {
        ptrAddr = addr,
        target = ptr
      })
    end
  end
end

print(string.format("Found %d potential SaveBlock pointers:", #candidates))
print("")

-- Display all candidates
for i, candidate in ipairs(candidates) do
  print(string.format("[%3d] Pointer at 0x%08X → 0x%08X",
    i, candidate.ptrAddr, candidate.target))
end

print("")
print("Known vanilla Emerald pointers (for reference):")
print("  SaveBlock1: 0x03005D8C → WRAM")
print("  SaveBlock2: 0x03005D90 → WRAM")
print("")
print("Next steps:")
print("1. Test candidate pointers with dumpStructure()")
print("2. Look for your player coordinates in the dumped data")
print("")

--[[
  Dump the structure pointed to by a pointer
  @param ptrAddr Address of the pointer (in IWRAM)
  @param length Number of bytes to dump (default 256)
]]
function dumpStructure(ptrAddr, length)
  length = length or 256

  local success, baseAddr = pcall(function()
    return memory.read32(ptrAddr)
  end)

  if not success or not baseAddr then
    print("ERROR: Failed to read pointer at 0x" .. string.format("%08X", ptrAddr))
    return
  end

  print(string.format("=== Dumping structure at 0x%08X ===", baseAddr))
  print(string.format("(Pointed to by 0x%08X)", ptrAddr))
  print("")
  print("Offset      Hex                              Dec       ASCII")
  print("------      ---                              ---       -----")

  for offset = 0, length - 1, 16 do
    local line_hex = ""
    local line_dec = ""
    local line_ascii = ""

    for i = 0, 15 do
      if offset + i < length then
        local success, byte = pcall(function()
          return memory.readByte(baseAddr + offset + i)
        end)

        if success and byte then
          line_hex = line_hex .. string.format("%02X ", byte)

          -- ASCII representation
          if byte >= 32 and byte <= 126 then
            line_ascii = line_ascii .. string.char(byte)
          else
            line_ascii = line_ascii .. "."
          end
        else
          line_hex = line_hex .. "?? "
          line_ascii = line_ascii .. "?"
        end
      end
    end

    print(string.format("+0x%04X   %-48s  %s", offset, line_hex, line_ascii))
  end

  print("")
  print("Look for your player coordinates in this dump.")
  print("X and Y are typically 2-byte (word) values.")
  print("")
  print("Example: If you see your X coordinate (e.g., 160 = 0x00A0)")
  print("at offset +0x0014, then:")
  print("  playerX offset = 0x0014")
end

print("Use: dumpStructure(0x03005D8C, 256)")
print("     dumpStructure(ptrAddr, length)")
