-- Verify CB2_InitBattle at 0x080363C1 (cart0 offset 0x363C0)
console:log("[VERIFY] Checking CB2_InitBattle address")

local f = io.open("C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\verify_cb2_result.txt", "w")

-- Read the first 16 bytes of CB2_InitBattle
local offset = 0x363C0
f:write("CB2_InitBattle at cart0 offset 0x363C0:\n")
for i = 0, 15, 2 do
  local instr = emu.memory.cart0:read16(offset + i)
  f:write(string.format("  +%02X: 0x%04X\n", i, instr))
end

-- Check if it starts with PUSH (B5xx)
local first = emu.memory.cart0:read16(offset)
f:write(string.format("\nFirst instruction: 0x%04X\n", first))
f:write(string.format("Is PUSH? %s\n", tostring((first & 0xFF00) == 0xB500)))

-- Also check CB2_HandleStartBattle at 0x08037B45 (cart0 offset 0x37B44)
local offset2 = 0x37B44
f:write("\nCB2_HandleStartBattle at cart0 offset 0x37B44:\n")
for i = 0, 15, 2 do
  local instr = emu.memory.cart0:read16(offset2 + i)
  f:write(string.format("  +%02X: 0x%04X\n", i, instr))
end

-- Check BattleMainCB2 at 0x0803816D (cart0 offset 0x3816C)
local offset3 = 0x3816C
f:write("\nBattleMainCB2 at cart0 offset 0x3816C:\n")
for i = 0, 15, 2 do
  local instr = emu.memory.cart0:read16(offset3 + i)
  f:write(string.format("  +%02X: 0x%04X\n", i, instr))
end

-- Check current callback2 value
local cb2 = emu.memory.iwram:read32(0x22C4)
f:write(string.format("\nCurrent callback2: 0x%08X\n", cb2))

-- Check gMain base
local cb1 = emu.memory.iwram:read32(0x22C0)
f:write(string.format("Current callback1: 0x%08X\n", cb1))

-- Check CB2_Overworld (0x080A89A5 → cart0 0x0A89A4)
local offset4 = 0x0A89A4
f:write(string.format("\nCB2_Overworld at cart0 0x0A89A4:\n"))
for i = 0, 7, 2 do
  local instr = emu.memory.cart0:read16(offset4 + i)
  f:write(string.format("  +%02X: 0x%04X\n", i, instr))
end

-- What is at the current callback2 address?
if cb2 >= 0x08000000 and cb2 < 0x09000000 then
  local cbOff = (cb2 & 0xFFFFFFFE) - 0x08000000
  f:write(string.format("\nInstructions at current cb2 (0x%08X, cart0 0x%06X):\n", cb2, cbOff))
  for i = 0, 15, 2 do
    local ok, instr = pcall(function() return emu.memory.cart0:read16(cbOff + i) end)
    if ok then
      f:write(string.format("  +%02X: 0x%04X\n", i, instr))
    end
  end
end

f:write("\nDONE\n")
f:close()
console:log("[VERIFY] Done - check verify_cb2_result.txt")
