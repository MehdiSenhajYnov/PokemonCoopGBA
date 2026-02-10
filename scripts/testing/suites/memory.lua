--[[
  memory.lua — Test suite: validate all known memory addresses
  Reads EWRAM, IWRAM, and cart0 addresses from config/run_and_bun.lua
]]

local Runner = require("runner")

Runner.suite("memory_addresses", function(t)
  -- === EWRAM reads (via emu.memory.wram, offsets from 0x02000000) ===

  t.test("playerX_readable", function()
    local val = emu.memory.wram:read16(0x24CBC)
    t.assertRange(val, 0, 2048, "playerX_readable")
  end)

  t.test("playerY_readable", function()
    local val = emu.memory.wram:read16(0x24CBE)
    t.assertRange(val, 0, 2048, "playerY_readable")
  end)

  t.test("mapGroup_readable", function()
    local val = emu.memory.wram:read8(0x24CC0)
    t.assertRange(val, 0, 50, "mapGroup_readable")
  end)

  t.test("mapId_readable", function()
    local val = emu.memory.wram:read8(0x24CC1)
    t.assertRange(val, 0, 255, "mapId_readable")
  end)

  t.test("facing_readable", function()
    local val = emu.memory.wram:read8(0x36934)
    t.assertRange(val, 0, 4, "facing_readable")
  end)

  t.test("partyCount_valid", function()
    local val = emu.memory.wram:read8(0x23A95)
    t.assertRange(val, 1, 6, "partyCount_valid")
  end)

  t.test("gPlayerParty_readable", function()
    local data = emu.memory.wram:readRange(0x23A98, 600)
    t.assertBytes(data, 600, "gPlayerParty_readable")
  end)

  t.test("gEnemyParty_readable", function()
    local data = emu.memory.wram:readRange(0x23CF0, 100)
    t.assertBytes(data, 100, "gEnemyParty_readable")
  end)

  t.test("gBattleTypeFlags_readable", function()
    local val = emu.memory.wram:read32(0x90E8)
    t.assertNotNil(val, "gBattleTypeFlags_readable")
  end)

  t.test("gMainInBattle_overworld", function()
    local val = emu.memory.wram:read8(0x0206AE)
    t.assertEqual(val, 0, "gMainInBattle_overworld")
  end)

  t.test("callback2_nonzero", function()
    local val = emu.memory.wram:read32(0x2064C)
    t.assertTrue(val ~= nil and val ~= 0, "callback2_nonzero")
  end)

  t.test("gBattleResources_readable", function()
    local val = emu.memory.wram:read32(0x23A18)
    t.assertNotNil(val, "gBattleResources_readable")
  end)

  -- === IWRAM reads (via emu.memory.iwram, offsets from 0x03000000) ===

  t.test("cameraX_readable", function()
    local val = emu.memory.iwram:read16(0x5DFC)
    t.assertNotNil(val, "cameraX_readable")
  end)

  t.test("cameraY_readable", function()
    local val = emu.memory.iwram:read16(0x5DF8)
    t.assertNotNil(val, "cameraY_readable")
  end)

  t.test("gWirelessCommType_readable", function()
    local val = emu.memory.iwram:read8(0x30FC)
    t.assertNotNil(val, "gWirelessCommType_readable")
  end)

  t.test("gReceivedRemoteLinkPlayers_readable", function()
    local val = emu.memory.iwram:read8(0x3124)
    t.assertNotNil(val, "gReceivedRemoteLinkPlayers_readable")
  end)

  t.test("gRngValue_readable", function()
    local val = emu.memory.iwram:read32(0x5D90)
    t.assertNotNil(val, "gRngValue_readable")
  end)

  -- === cart0 (ROM) read ===

  t.test("cart0_read_header", function()
    local val = emu.memory.cart0:read8(0)
    t.assertNotNil(val, "cart0_read_header")
  end)

  t.test("cart0_GetMultiplayerId_readable", function()
    local val = emu.memory.cart0:read32(0x00A4B0)
    t.assertNotNil(val, "cart0_GetMultiplayerId_readable")
  end)

  t.screenshot("memory_tests_done")
end)
