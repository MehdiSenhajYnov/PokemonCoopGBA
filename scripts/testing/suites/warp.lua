--[[
  warp.lua — Test suite: warp system validation
  Tests sWarpDestination write/readback and warp-related addresses.
]]

local Runner = require("runner")

Runner.suite("warp_system", function(t)
  -- sWarpDestination = 0x020318A8 (EWRAM offset: 0x0318A8)
  local SWARP_OFF = 0x0318A8

  -- Test 1: Read current position from overworld
  t.test("read_current_position", function()
    local x = emu.memory.wram:read16(0x24CBC)
    local y = emu.memory.wram:read16(0x24CBE)
    local mg = emu.memory.wram:read8(0x24CC0)
    local mi = emu.memory.wram:read8(0x24CC1)
    t.assertRange(x, 0, 2048, "current_playerX")
    t.assertRange(y, 0, 2048, "current_playerY")
    t.assertRange(mg, 0, 50, "current_mapGroup")
    t.assertRange(mi, 0, 255, "current_mapId")
  end)

  -- Test 2: Read sWarpDestination
  t.test("sWarpDest_readable", function()
    local mg = emu.memory.wram:read8(SWARP_OFF)
    local mi = emu.memory.wram:read8(SWARP_OFF + 1)
    t.assertNotNil(mg, "sWarpDest_mapGroup_readable")
    t.assertNotNil(mi, "sWarpDest_mapId_readable")
  end)

  -- Test 3: Write sWarpDestination with duel room coords, readback, restore
  t.test("sWarpDest_write_readback", function()
    -- Save original
    local origData = emu.memory.wram:readRange(SWARP_OFF, 8)

    -- Write duel room coords: mapGroup=28, mapId=24, warpId=0xFF, pad=0, x=3, y=5
    emu.memory.wram:write8(SWARP_OFF, 28)       -- mapGroup
    emu.memory.wram:write8(SWARP_OFF + 1, 24)   -- mapId
    emu.memory.wram:write8(SWARP_OFF + 2, 0xFF) -- warpId
    emu.memory.wram:write8(SWARP_OFF + 3, 0)    -- pad
    emu.memory.wram:write16(SWARP_OFF + 4, 3)   -- x
    emu.memory.wram:write16(SWARP_OFF + 6, 5)   -- y

    -- Readback
    t.assertEqual(emu.memory.wram:read8(SWARP_OFF), 28, "sWarpDest_mapGroup_written")
    t.assertEqual(emu.memory.wram:read8(SWARP_OFF + 1), 24, "sWarpDest_mapId_written")
    t.assertEqual(emu.memory.wram:read16(SWARP_OFF + 4), 3, "sWarpDest_x_written")
    t.assertEqual(emu.memory.wram:read16(SWARP_OFF + 6), 5, "sWarpDest_y_written")

    -- Restore
    for i = 0, 7 do
      emu.memory.wram:write8(SWARP_OFF + i, origData:byte(i + 1))
    end
  end)

  -- Test 4: gLastUsedWarp readable (8 bytes before sWarpDestination)
  t.test("gLastUsedWarp_readable", function()
    local lastWarpOff = SWARP_OFF - 8
    local mg = emu.memory.wram:read8(lastWarpOff)
    t.assertNotNil(mg, "gLastUsedWarp_readable")
  end)

  -- Test 5: Callback2 related addresses
  t.test("callback2_warp_related", function()
    local cb2 = emu.memory.wram:read32(0x2064C)
    t.assertNotNil(cb2, "callback2_readable")
    -- In overworld, should be CB2_Overworld (0x080A89A5) or similar
    t.assertTrue(cb2 >= 0x08000000 and cb2 < 0x0A000000, "callback2_in_ROM_range")
  end)

  -- Test 6: CB2_LoadMap readable from ROM
  t.test("CB2_LoadMap_rom", function()
    -- CB2_LoadMap = 0x08007441, cart0 offset 0x7440
    local firstInstr = emu.memory.cart0:read16(0x7440)
    t.assertNotNil(firstInstr, "CB2_LoadMap_first_instruction")
    -- PUSH instruction is typical function start (B5xx)
    local isPush = (firstInstr & 0xFF00) == 0xB500
    t.assertTrue(isPush, "CB2_LoadMap_starts_with_PUSH")
  end)

  t.screenshot("warp_tests_done")
end)
