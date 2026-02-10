-- Verify the BEQ patch at 0x032ACE (InitBtlControllersInternal)
-- Expected: 0xD01D (BEQ +0x3A) in unpatched ROM

console:log("=== Verifying BEQ patch target ===")

-- Read the instruction at 0x032ACE
local ok, val = pcall(function()
  return emu.memory.cart0:read16(0x032ACE)
end)

if ok then
  console:log(string.format("ROM[0x032ACE] = 0x%04X", val))
  if val == 0xD01D then
    console:log("MATCH: D01D = BEQ +0x3A (correct patch target)")
  elseif val == 0x46C0 then
    console:log("Already patched: 46C0 = NOP (MOV R8,R8)")
  else
    console:log("MISMATCH: expected D01D or 46C0")
  end
else
  console:log("ERROR reading ROM")
end

-- Also scan nearby for context (look for IS_MASTER check pattern)
console:log("\n=== Nearby ROM context ===")
for off = 0x032AC0, 0x032AE0, 2 do
  local ok2, v = pcall(function() return emu.memory.cart0:read16(off) end)
  if ok2 then
    console:log(string.format("  0x%06X: 0x%04X", off, v))
  end
end

-- Write result file
local f = io.open("verify_beq_result.txt", "w")
if f then
  if ok then
    f:write(string.format("0x032ACE = 0x%04X (%s)\n", val,
      val == 0xD01D and "CORRECT: BEQ" or (val == 0x46C0 and "PATCHED: NOP" or "UNKNOWN")))
  else
    f:write("ERROR\n")
  end
  f:close()
end
