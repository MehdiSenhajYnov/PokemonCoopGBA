--[[
  Phase 0.2 - WRAM Memory Scanner for Run & Bun

  Copy-paste this entire script into mGBA Scripting Console

  Usage:
    1. Note your current X coordinate (count tiles from a reference point)
    2. Estimate value: tiles × 16 (e.g., tile 10 → X ≈ 160)
    3. Run: candidatesX = scanWRAM(160, 2)
    4. Move horizontally (5+ tiles)
    5. Run: candidatesX = rescan(candidatesX, newValue, 2)
    6. Repeat until you have 1-5 candidates
]]

-- Global storage for scan results
_scanResults = _scanResults or {}

--[[
  Scan entire WRAM for a specific value
  @param value Value to search for
  @param size 1=byte, 2=word, 4=dword
  @return table of addresses that match
]]
function scanWRAM(value, size)
  local start = 0x02000000
  local end_addr = 0x0203FFFF
  local results = {}

  print(string.format("=== Scanning WRAM for value: %d (0x%04X) ===", value, value))
  print(string.format("Range: 0x%08X - 0x%08X", start, end_addr))
  print(string.format("Size: %d bytes", size))
  print("")

  local count = 0
  for addr = start, end_addr, size do
    local success, read_value = pcall(function()
      if size == 1 then
        return memory.readByte(addr)
      elseif size == 2 then
        return memory.read16(addr)
      elseif size == 4 then
        return memory.read32(addr)
      end
    end)

    if success and read_value == value then
      table.insert(results, addr)
      count = count + 1
    end
  end

  print(string.format("Found %d matches:", #results))

  -- Display first 50 matches
  for i, addr in ipairs(results) do
    if i <= 50 then
      print(string.format("  [%3d] 0x%08X", i, addr))
    end
  end

  if #results > 50 then
    print(string.format("  ... and %d more (not shown)", #results - 50))
  end

  print("")
  print("Next steps:")
  print("1. Move your character to change the value")
  print("2. Run: results = rescan(results, newValue, " .. size .. ")")
  print("3. Repeat until you have 1-5 candidates")

  return results
end

--[[
  Rescan previous results with new value
  @param previousResults Results from previous scan
  @param newValue New value to search for
  @param size 1=byte, 2=word, 4=dword
  @return filtered table of addresses
]]
function rescan(previousResults, newValue, size)
  if not previousResults or #previousResults == 0 then
    print("ERROR: No previous results to rescan")
    return {}
  end

  print(string.format("=== Rescanning %d addresses for new value: %d (0x%04X) ===",
    #previousResults, newValue, newValue))
  print("")

  local results = {}

  for _, addr in ipairs(previousResults) do
    local success, read_value = pcall(function()
      if size == 1 then
        return memory.readByte(addr)
      elseif size == 2 then
        return memory.read16(addr)
      elseif size == 4 then
        return memory.read32(addr)
      end
    end)

    if success and read_value == newValue then
      table.insert(results, addr)
    end
  end

  print(string.format("Matches: %d → %d", #previousResults, #results))
  print("")

  for i, addr in ipairs(results) do
    print(string.format("  [%3d] 0x%08X", i, addr))
  end

  if #results == 0 then
    print("")
    print("⚠️  No matches found!")
    print("Possible reasons:")
    print("  - Value didn't change as expected")
    print("  - Value is stored differently (different size?)")
    print("  - Need to start a new scan")
  elseif #results <= 5 then
    print("")
    print("✅ Good! Down to " .. #results .. " candidates.")
    print("Next: Test each candidate with watchAddress()")
  else
    print("")
    print("Keep narrowing down. Move again and rescan.")
  end

  return results
end

--[[
  Watch an address in real-time
  @param address Address to monitor
  @param size 1=byte, 2=word, 4=dword
]]
function watchAddress(address, size)
  print(string.format("=== Watching 0x%08X (press Ctrl+C to stop) ===", address))
  print("Move your character around and observe the value.")
  print("")

  -- Note: This creates a frame callback
  -- In mGBA console, you'll need to manually remove it with callbacks.remove()
  local callbackId = callbacks.add("frame", function()
    local success, value = pcall(function()
      if size == 1 then
        return memory.readByte(address)
      elseif size == 2 then
        return memory.read16(address)
      elseif size == 4 then
        return memory.read32(address)
      end
    end)

    if success then
      gui.drawText(5, 5, string.format("Watch: 0x%08X = %d", address, value), 0xFFFFFF, 0x000000)
    else
      gui.drawText(5, 5, string.format("Watch: 0x%08X = ERROR", address), 0xFF0000, 0x000000)
    end
  end)

  print("Callback ID: " .. tostring(callbackId))
  print("To stop watching, run: callbacks.remove(" .. tostring(callbackId) .. ")")
end

print("=== WRAM Scanner Loaded ===")
print("")
print("Commands:")
print("  scanWRAM(value, size)           - Initial scan")
print("  rescan(results, newValue, size) - Narrow down results")
print("  watchAddress(addr, size)        - Monitor address in real-time")
print("")
print("Example workflow:")
print("  1. results = scanWRAM(160, 2)        -- scan for X=160")
print("  2. -- move right 5 tiles --")
print("  3. results = rescan(results, 240, 2) -- rescan for X=240")
print("  4. watchAddress(0x02024844, 2)       -- test a candidate")
print("")
print("Sizes: 1=byte (MapID, Facing), 2=word (X, Y), 4=dword (pointers)")
