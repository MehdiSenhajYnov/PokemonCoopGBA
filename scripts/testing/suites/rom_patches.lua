--[[
  rom_patches.lua — Test suite: ROM patching (cart0 write + readback)
  Validates that all battle system ROM patches can be applied and reverted.
]]

local Runner = require("runner")

Runner.suite("rom_patches", function(t)
  -- Helper: patch ROM, verify, restore
  local function testROMPatch(name, romOffset, patchValue, patchSize)
    t.test(name, function()
      -- Read original
      local original
      if patchSize == 2 then
        original = emu.memory.cart0:read16(romOffset)
      elseif patchSize == 4 then
        original = emu.memory.cart0:read32(romOffset)
      else
        original = emu.memory.cart0:read8(romOffset)
      end
      t.assertNotNil(original, name .. "_read_original")

      -- Write patch
      if patchSize == 2 then
        emu.memory.cart0:write16(romOffset, patchValue)
      elseif patchSize == 4 then
        emu.memory.cart0:write32(romOffset, patchValue)
      else
        emu.memory.cart0:write8(romOffset, patchValue)
      end

      -- Readback verify
      local readback
      if patchSize == 2 then
        readback = emu.memory.cart0:read16(romOffset)
      elseif patchSize == 4 then
        readback = emu.memory.cart0:read32(romOffset)
      else
        readback = emu.memory.cart0:read8(romOffset)
      end
      t.assertEqual(readback, patchValue, name .. "_readback")

      -- Restore original
      if patchSize == 2 then
        emu.memory.cart0:write16(romOffset, original)
      elseif patchSize == 4 then
        emu.memory.cart0:write32(romOffset, original)
      else
        emu.memory.cart0:write8(romOffset, original)
      end

      -- Verify restore
      local restored
      if patchSize == 2 then
        restored = emu.memory.cart0:read16(romOffset)
      elseif patchSize == 4 then
        restored = emu.memory.cart0:read32(romOffset)
      else
        restored = emu.memory.cart0:read8(romOffset)
      end
      t.assertEqual(restored, original, name .. "_restored")
    end)
  end

  -- GetMultiplayerId: host patch (MOV R0,#0; BX LR = 0x47700020)
  testROMPatch("GetMultiplayerId_host_patch",
    0x00A4B0,       -- cart0 offset
    0x47700020,     -- MOV R0,#0 + BX LR (little-endian u32)
    4)

  -- GetMultiplayerId: client patch (MOV R0,#1; BX LR = 0x47700120)
  testROMPatch("GetMultiplayerId_client_patch",
    0x00A4B0,
    0x47700120,     -- MOV R0,#1 + BX LR
    4)

  -- PlayerBufferExecCompleted +0x1C: BEQ → B unconditional
  testROMPatch("PlayerBufExecCompleted_skip",
    0x06F0D4 + 0x1C,  -- romOffset + patch offset
    0xE01C,            -- B +0x1C (unconditional)
    2)

  -- LinkOpponentBufferExecCompleted +0x1C: BEQ → B unconditional
  testROMPatch("LinkOpponentBufExecCompleted_skip",
    0x078788 + 0x1C,
    0xE01C,
    2)

  -- PrepareBufferDataTransferLink +0x18: BEQ → B unconditional
  testROMPatch("PrepBufTransferLink_skip",
    0x032FA8 + 0x18,
    0xE008,
    2)

  -- Verify single byte write+readback at a known safe location
  t.test("cart0_byte_write_readback", function()
    local addr = 0x00A4B0
    local orig = emu.memory.cart0:read8(addr)
    emu.memory.cart0:write8(addr, 0xAA)
    local rb = emu.memory.cart0:read8(addr)
    t.assertEqual(rb, 0xAA, "cart0_byte_readback")
    -- Restore
    emu.memory.cart0:write8(addr, orig)
  end)

  t.screenshot("rom_patches_done")
end)
