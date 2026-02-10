--[[
  Cart0 (ROM) Write Test Script

  Tests whether emu.memory.cart0:write8/write16/write32() work on the
  current mGBA build. This is critical for the Link Battle Emulation
  approach — ROM patching requires writable cart0.

  Load in mGBA → check console for "CART0 WRITE: SUCCESS" or "CART0 WRITE: FAILED"

  Safe: reads originals first, writes test values, verifies, restores originals.
  Tests ROM header area (0xA0-0xAB = game title, known readable values).
]]

console:log("=== CART0 WRITE TEST ===")
console:log("Testing if ROM memory is writable via emu.memory.cart0...")

local results = { write8 = false, write16 = false, write32 = false }
local errors = {}

-- Test area: ROM offset 0xA0 (game title in header — 12 bytes, known values)
-- We'll use offsets near the end of the title area to minimize risk

-- === Test write8 ===
do
  local offset = 0xA0
  local ok_r, original = pcall(emu.memory.cart0.read8, emu.memory.cart0, offset)
  if not ok_r then
    table.insert(errors, "write8: cannot read cart0 at 0xA0")
  else
    local testVal = (original ~ 0xFF) & 0xFF  -- bitwise NOT to guarantee different value
    local ok_w = pcall(emu.memory.cart0.write8, emu.memory.cart0, offset, testVal)
    if not ok_w then
      table.insert(errors, "write8: pcall failed (function may not exist)")
    else
      local ok_v, readback = pcall(emu.memory.cart0.read8, emu.memory.cart0, offset)
      if ok_v and readback == testVal then
        results.write8 = true
        console:log(string.format("  write8:  PASS (wrote 0x%02X, read 0x%02X)", testVal, readback))
      else
        table.insert(errors, string.format("write8: wrote 0x%02X, read 0x%02X (unchanged)", testVal, readback or -1))
      end
      -- Restore original
      pcall(emu.memory.cart0.write8, emu.memory.cart0, offset, original)
    end
  end
end

-- === Test write16 ===
do
  local offset = 0xA2
  local ok_r, original = pcall(emu.memory.cart0.read16, emu.memory.cart0, offset)
  if not ok_r then
    table.insert(errors, "write16: cannot read cart0 at 0xA2")
  else
    local testVal = (original ~ 0xFFFF) & 0xFFFF
    local ok_w = pcall(emu.memory.cart0.write16, emu.memory.cart0, offset, testVal)
    if not ok_w then
      table.insert(errors, "write16: pcall failed (function may not exist)")
    else
      local ok_v, readback = pcall(emu.memory.cart0.read16, emu.memory.cart0, offset)
      if ok_v and readback == testVal then
        results.write16 = true
        console:log(string.format("  write16: PASS (wrote 0x%04X, read 0x%04X)", testVal, readback))
      else
        table.insert(errors, string.format("write16: wrote 0x%04X, read 0x%04X (unchanged)", testVal, readback or -1))
      end
      pcall(emu.memory.cart0.write16, emu.memory.cart0, offset, original)
    end
  end
end

-- === Test write32 ===
do
  local offset = 0xA4
  local ok_r, original = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
  if not ok_r then
    table.insert(errors, "write32: cannot read cart0 at 0xA4")
  else
    local testVal = (original ~ 0xFFFFFFFF) & 0xFFFFFFFF
    local ok_w = pcall(emu.memory.cart0.write32, emu.memory.cart0, offset, testVal)
    if not ok_w then
      table.insert(errors, "write32: pcall failed (function may not exist)")
    else
      local ok_v, readback = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
      if ok_v and readback == testVal then
        results.write32 = true
        console:log(string.format("  write32: PASS (wrote 0x%08X, read 0x%08X)", testVal, readback))
      else
        table.insert(errors, string.format("write32: wrote 0x%08X, read 0x%08X (unchanged)", testVal, readback or -1))
      end
      pcall(emu.memory.cart0.write32, emu.memory.cart0, offset, original)
    end
  end
end

-- === Verify restoration ===
do
  local ok, title = pcall(function()
    local t = ""
    for i = 0, 11 do
      local b = emu.memory.cart0:read8(0xA0 + i)
      if b and b ~= 0 then t = t .. string.char(b) end
    end
    return t
  end)
  if ok then
    console:log("  ROM title after restore: " .. title)
  end
end

-- === Summary ===
console:log("")
console:log("--- RESULTS ---")
console:log(string.format("  write8:  %s", results.write8 and "WORKS" or "FAILED"))
console:log(string.format("  write16: %s", results.write16 and "WORKS" or "FAILED"))
console:log(string.format("  write32: %s", results.write32 and "WORKS" or "FAILED"))

if #errors > 0 then
  console:log("")
  console:log("Errors:")
  for _, e in ipairs(errors) do
    console:log("  " .. e)
  end
end

console:log("")
if results.write8 and results.write16 and results.write32 then
  console:log("CART0 WRITE: SUCCESS — ROM patching is possible!")
  console:log("The Link Battle Emulation approach can use full ROM patching.")
else
  console:log("CART0 WRITE: FAILED — ROM is read-only in this mGBA build.")
  console:log("Fallback: use breakpoints + register writes, EWRAM-only patches.")
  console:log("Buffer relay (EWRAM) still works. Discovery scripts still valuable.")
end
console:log("=== END CART0 WRITE TEST ===")
