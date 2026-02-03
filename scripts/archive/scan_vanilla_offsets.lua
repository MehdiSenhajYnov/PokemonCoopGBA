--[[
  Phase 0.1 - Test Emerald Vanilla Offsets on Run & Bun

  Copy-paste this entire script into mGBA Scripting Console
  (Tools → Scripting in mGBA)

  Purpose: Quick test to see if Emerald vanilla offsets work on Run & Bun
]]

print("=== Testing Emerald Vanilla Offsets on Run & Bun ===")
print("")

-- Emerald vanilla offsets
local offsets = {
  {addr = 0x02024844, name = "PlayerX", size = 2},
  {addr = 0x02024846, name = "PlayerY", size = 2},
  {addr = 0x02024842, name = "MapID", size = 1},
  {addr = 0x02024843, name = "MapGroup", size = 1},
  {addr = 0x02024848, name = "Facing", size = 1},
}

-- Test each offset
for _, offset in ipairs(offsets) do
  local success, value = pcall(function()
    if offset.size == 1 then
      return memory.readByte(offset.addr)
    elseif offset.size == 2 then
      return memory.read16(offset.addr)
    elseif offset.size == 4 then
      return memory.read32(offset.addr)
    end
  end)

  if success and value then
    print(string.format("%-12s @ 0x%08X = %5d (0x%04X)",
      offset.name, offset.addr, value, value))
  else
    print(string.format("%-12s @ 0x%08X = READ FAILED",
      offset.name, offset.addr))
  end
end

print("")
print("Instructions:")
print("1. Move your character around (up/down/left/right)")
print("2. Re-run this script")
print("3. Check if X and Y values change logically:")
print("   - Moving UP    → Y decreases")
print("   - Moving DOWN  → Y increases")
print("   - Moving LEFT  → X decreases")
print("   - Moving RIGHT → X increases")
print("")
print("If values change correctly:")
print("  ✅ Vanilla offsets WORK! Proceed to section 0.4")
print("")
print("If values are random/garbage or don't change:")
print("  ❌ Vanilla offsets DON'T WORK. Use scan_wram.lua next")
