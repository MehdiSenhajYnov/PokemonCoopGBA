--[[
  Phase 0.6 - Validate Found Offsets

  After finding offsets, use this script to validate them

  EDIT THE OFFSETS BELOW with your discovered values
]]

-- ============================================
-- EDIT THESE WITH YOUR DISCOVERED OFFSETS
-- ============================================
local OFFSETS = {
  playerX = 0x02024844,      -- Replace with actual address
  playerY = 0x02024846,      -- Replace with actual address
  mapId = 0x02024842,        -- Replace with actual address
  mapGroup = 0x02024843,     -- Replace with actual address
  facing = 0x02024848,       -- Replace with actual address
}

-- Set to true if using dynamic pointers (SaveBlock mode)
local USE_DYNAMIC = false

-- If USE_DYNAMIC = true, configure these:
local SAVEBLOCK1_PTR = 0x03005D8C  -- Pointer address in IWRAM
local OFFSETS_DYNAMIC = {
  playerX = 0x0000,          -- Offset from SaveBlock1 base
  playerY = 0x0002,          -- Offset from SaveBlock1 base
  mapId = 0x0004,            -- Offset from SaveBlock1 base
  mapGroup = 0x0005,         -- Offset from SaveBlock1 base
  facing = 0x0008,           -- Offset from SaveBlock1 base
}
-- ============================================

print("=== Validating Offsets for Run & Bun ===")
print("")

-- Helper to read with dynamic pointers
local function readDynamic(baseOffset, size)
  local success, ptrBase = pcall(function()
    return memory.read32(SAVEBLOCK1_PTR)
  end)

  if not success or not ptrBase then
    return nil
  end

  local addr = ptrBase + baseOffset

  local success2, value = pcall(function()
    if size == 1 then
      return memory.readByte(addr)
    elseif size == 2 then
      return memory.read16(addr)
    elseif size == 4 then
      return memory.read32(addr)
    end
  end)

  if success2 then
    return value
  end
  return nil
end

-- Helper to read with static offsets
local function readStatic(addr, size)
  local success, value = pcall(function()
    if size == 1 then
      return memory.readByte(addr)
    elseif size == 2 then
      return memory.read16(addr)
    elseif size == 4 then
      return memory.read32(addr)
    end
  end)

  if success then
    return value
  end
  return nil
end

-- Read all values
local x, y, mapId, mapGroup, facing

if USE_DYNAMIC then
  print("Mode: DYNAMIC (via SaveBlock pointers)")
  print(string.format("SaveBlock1 pointer at: 0x%08X", SAVEBLOCK1_PTR))
  print("")

  x = readDynamic(OFFSETS_DYNAMIC.playerX, 2)
  y = readDynamic(OFFSETS_DYNAMIC.playerY, 2)
  mapId = readDynamic(OFFSETS_DYNAMIC.mapId, 1)
  mapGroup = readDynamic(OFFSETS_DYNAMIC.mapGroup, 1)
  facing = readDynamic(OFFSETS_DYNAMIC.facing, 1)
else
  print("Mode: STATIC (direct WRAM addresses)")
  print("")

  x = readStatic(OFFSETS.playerX, 2)
  y = readStatic(OFFSETS.playerY, 2)
  mapId = readStatic(OFFSETS.mapId, 1)
  mapGroup = readStatic(OFFSETS.mapGroup, 1)
  facing = readStatic(OFFSETS.facing, 1)
end

-- Display results
print("Current Values:")
print(string.format("  PlayerX:     %s", x and x or "FAILED"))
print(string.format("  PlayerY:     %s", y and y or "FAILED"))
print(string.format("  MapID:       %s", mapId and mapId or "FAILED"))
print(string.format("  MapGroup:    %s", mapGroup and mapGroup or "FAILED"))
print(string.format("  Facing:      %s", facing and facing or "FAILED"))
print("")

-- Validation checks
local issues = {}

if not x or not y then
  table.insert(issues, "Failed to read X or Y coordinates")
elseif x > 2048 or y > 2048 then
  table.insert(issues, string.format("Coordinates suspiciously high (X=%d Y=%d)", x, y))
end

if not mapId or not mapGroup then
  table.insert(issues, "Failed to read Map ID or Group")
elseif mapGroup > 50 then
  table.insert(issues, string.format("MapGroup suspiciously high (%d)", mapGroup))
end

if not facing then
  table.insert(issues, "Failed to read Facing direction")
elseif facing > 4 then
  table.insert(issues, string.format("Facing value out of range (%d, expected 0-4)", facing))
end

-- Display validation result
if #issues == 0 then
  print("✅ All offsets appear valid!")
  print("")
  print("Next steps:")
  print("1. Walk around and re-run this script")
  print("2. Verify X/Y change correctly:")
  print("   - UP    → Y decreases")
  print("   - DOWN  → Y increases")
  print("   - LEFT  → X decreases")
  print("   - RIGHT → X increases")
  print("3. Enter a building to verify MapID/MapGroup change")
  print("4. Turn around to verify Facing changes (1=Down, 2=Up, 3=Left, 4=Right)")
else
  print("❌ Issues found:")
  for i, issue in ipairs(issues) do
    print("  " .. i .. ". " .. issue)
  end
  print("")
  print("Some offsets may be incorrect. Review your scan results.")
end

-- Create real-time monitor callback
print("")
print("To monitor in real-time, run: startMonitor()")
print("")

function startMonitor()
  print("Starting real-time monitor...")
  print("Values will display in top-left corner")
  print("Run stopMonitor() to stop")
  print("")

  _monitorCallback = callbacks.add("frame", function()
    local x, y, mapId, mapGroup, facing

    if USE_DYNAMIC then
      x = readDynamic(OFFSETS_DYNAMIC.playerX, 2)
      y = readDynamic(OFFSETS_DYNAMIC.playerY, 2)
      mapId = readDynamic(OFFSETS_DYNAMIC.mapId, 1)
      mapGroup = readDynamic(OFFSETS_DYNAMIC.mapGroup, 1)
      facing = readDynamic(OFFSETS_DYNAMIC.facing, 1)
    else
      x = readStatic(OFFSETS.playerX, 2)
      y = readStatic(OFFSETS.playerY, 2)
      mapId = readStatic(OFFSETS.mapId, 1)
      mapGroup = readStatic(OFFSETS.mapGroup, 1)
      facing = readStatic(OFFSETS.facing, 1)
    end

    if x and y then
      gui.drawText(5, 5, string.format("Position: X=%d Y=%d", x, y), 0xFFFFFF, 0x000000)
    else
      gui.drawText(5, 5, "Position: ERROR", 0xFF0000, 0x000000)
    end

    if mapId and mapGroup then
      gui.drawText(5, 15, string.format("Map: %d:%d", mapGroup, mapId), 0xFFFFFF, 0x000000)
    else
      gui.drawText(5, 15, "Map: ERROR", 0xFF0000, 0x000000)
    end

    if facing then
      local facingStr = {"None", "Down", "Up", "Left", "Right"}
      gui.drawText(5, 25, string.format("Facing: %s (%d)", facingStr[facing + 1] or "?", facing), 0xFFFFFF, 0x000000)
    else
      gui.drawText(5, 25, "Facing: ERROR", 0xFF0000, 0x000000)
    end
  end)
end

function stopMonitor()
  if _monitorCallback then
    callbacks.remove(_monitorCallback)
    _monitorCallback = nil
    print("Monitor stopped")
  else
    print("No monitor running")
  end
end
