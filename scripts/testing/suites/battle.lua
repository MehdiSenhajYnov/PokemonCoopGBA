--[[
  battle.lua — Test suite: battle system validation
  Tests party read/write, ROM+EWRAM patches, and battle trigger.
  Includes both sync tests and an async multi-frame test.
]]

local Runner = require("runner")

-- === Sync tests: party data and patches ===

Runner.suite("battle_system", function(t)
  -- Test 1: Initial state (overworld, not in battle)
  -- gMain.inBattle is at 0x03002AF9 (IWRAM), bit 1
  t.test("initial_not_in_battle", function()
    local val = emu.memory.iwram:read8(0x2AF9)
    local inBattle = (val & 0x02) ~= 0 and 1 or 0
    t.assertEqual(inBattle, 0, "inBattle_is_zero")
  end)

  -- gBattleTypeFlags at 0x02023364 (EWRAM offset 0x23364)
  t.test("initial_battleTypeFlags_zero", function()
    local btf = emu.memory.wram:read32(0x23364)
    t.assertEqual(btf, 0, "battleTypeFlags_zero")
  end)

  -- Test 2: Read local party (600 bytes)
  t.test("read_local_party", function()
    local partyData = emu.memory.wram:readRange(0x23A98, 600)
    t.assertBytes(partyData, 600, "local_party_600bytes")

    -- First pokemon should have non-zero data (at least personality != 0)
    local personality = emu.memory.wram:read32(0x23A98)
    t.assertTrue(personality ~= 0, "first_pokemon_has_data")
  end)

  -- Test 3: Party count matches actual data
  t.test("party_count_consistency", function()
    local count = emu.memory.wram:read8(0x23A95)
    t.assertRange(count, 1, 6, "party_count_range")

    -- Check that slot at count+1 has zero personality (empty slot)
    if count < 6 then
      local emptySlotAddr = 0x23A98 + count * 100
      local emptyPersonality = emu.memory.wram:read32(emptySlotAddr)
      t.assertEqual(emptyPersonality, 0, "empty_slot_zeroed")
    end
  end)

  -- Test 4: Write to gEnemyParty and readback
  t.test("inject_enemy_party", function()
    -- Read current local party
    local localParty = emu.memory.wram:readRange(0x23A98, 600)
    t.assertBytes(localParty, 600, "read_local_for_inject")

    -- Save original enemy party
    local origEnemy = emu.memory.wram:readRange(0x23CF0, 600)

    -- Write local party to enemy party
    for i = 0, 599 do
      emu.memory.wram:write8(0x23CF0 + i, localParty:byte(i + 1))
    end

    -- Readback and verify first 4 bytes match
    local injected = emu.memory.wram:readRange(0x23CF0, 4)
    local expected = localParty:sub(1, 4)
    t.assertTrue(injected == expected, "enemy_party_injected_matches")

    -- Restore original enemy party
    for i = 0, 599 do
      emu.memory.wram:write8(0x23CF0 + i, origEnemy:byte(i + 1))
    end
  end)

  -- Test 5: EWRAM patch test (gWirelessCommType + gReceivedRemoteLinkPlayers)
  t.test("ewram_patches", function()
    -- Save originals
    local origWireless = emu.memory.iwram:read8(0x30FC)
    local origRemote = emu.memory.iwram:read8(0x3124)

    -- Patch
    emu.memory.iwram:write8(0x30FC, 0)   -- gWirelessCommType = 0
    emu.memory.iwram:write8(0x3124, 1)   -- gReceivedRemoteLinkPlayers = 1

    -- Verify
    t.assertEqual(emu.memory.iwram:read8(0x30FC), 0, "gWirelessCommType_patched")
    t.assertEqual(emu.memory.iwram:read8(0x3124), 1, "gReceivedRemoteLinkPlayers_patched")

    -- Restore
    emu.memory.iwram:write8(0x30FC, origWireless)
    emu.memory.iwram:write8(0x3124, origRemote)
  end)

  -- Test 6: gActiveBattler readable (0x020233DC → offset 0x233DC)
  t.test("gActiveBattler_readable", function()
    local val = emu.memory.wram:read8(0x233DC)
    t.assertNotNil(val, "gActiveBattler_readable")
  end)

  -- Test 7: gBattleControllerExecFlags readable (0x020233E0 → offset 0x233E0)
  t.test("gBattleControllerExecFlags_readable", function()
    local val = emu.memory.wram:read32(0x233E0)
    t.assertNotNil(val, "gBattleControllerExecFlags_readable")
  end)

  -- Test 8: gChosenActionByBattler readable (0x02023598 → offset 0x23598)
  t.test("gChosenActionByBattler_readable", function()
    local val = emu.memory.wram:read8(0x23598)
    t.assertNotNil(val, "gChosenActionByBattler_readable")
  end)

  -- Test 9: gChosenMoveByBattler readable (0x020235FA → offset 0x235FA)
  t.test("gChosenMoveByBattler_readable", function()
    local val = emu.memory.wram:read16(0x235FA)
    t.assertNotNil(val, "gChosenMoveByBattler_readable")
  end)

  -- Test 10: GetBlockReceivedStatus ROM patchable (dynamic 0→0x0F toggle)
  t.test("GetBlockReceivedStatus_dynamic_patch", function()
    local offset = 0x0A598
    local orig = emu.memory.cart0:read16(offset)
    -- Patch to MOV R0,#0 (0x2000) — block engine
    emu.memory.cart0:write16(offset, 0x2000)
    local blocked = emu.memory.cart0:read16(offset)
    t.assertEqual(blocked, 0x2000, "GBRS_blocked_to_0")
    -- Patch to MOV R0,#0x0F (0x200F) — unblock engine
    emu.memory.cart0:write16(offset, 0x200F)
    local unblocked = emu.memory.cart0:read16(offset)
    t.assertEqual(unblocked, 0x200F, "GBRS_unblocked_to_0F")
    -- Restore
    emu.memory.cart0:write16(offset, orig)
  end)

  t.screenshot("battle_sync_tests_done")
end)

-- === Async test: trigger battle and verify state change ===
-- NOTE: This test actually modifies game state. It sets callback2 to
-- CB2_HandleStartBattle and watches for inBattle to change.
-- Only run this if you want to test the full battle trigger flow.

Runner.asyncSuite("battle_trigger", function(t)
  -- CORRECTED addresses: gMain is in IWRAM at 0x030022C0
  -- callback2 = gMain+0x04 = 0x030022C4 → IWRAM offset 0x22C4
  -- gMain.state = gMain+0x438 = 0x030026F8 → IWRAM offset 0x26F8
  -- gBattleTypeFlags = 0x02023364 → EWRAM offset 0x23364

  -- Save state for restoration
  local origCb2 = emu.memory.iwram:read32(0x22C4)
  local origState = emu.memory.iwram:read16(0x26F8)
  local origBtf = emu.memory.wram:read32(0x23364)
  local origWireless = emu.memory.iwram:read8(0x30FC)
  local origRemote = emu.memory.iwram:read8(0x3124)
  local origCb1 = emu.memory.iwram:read32(0x22C0)

  -- Save GetMultiplayerId original bytes
  local origGMPI = emu.memory.cart0:read32(0x00A4B0)

  t.screenshot("before_battle_trigger")

  -- Apply link battle patches
  -- 1. IWRAM patches
  emu.memory.iwram:write8(0x30FC, 0)   -- gWirelessCommType = 0
  emu.memory.iwram:write8(0x3124, 1)   -- gReceivedRemoteLinkPlayers = 1

  -- 2. ROM patches
  emu.memory.cart0:write32(0x00A4B0, 0x47700020)  -- GetMultiplayerId: MOV R0,#0; BX LR

  -- 3. Set battle type (LINK + TRAINER + IS_MASTER — v7 approach keeps LINK!)
  emu.memory.wram:write32(0x23364, 0x0000000E)  -- LINK(2) + IS_MASTER(4) + TRAINER(8)

  -- 4. Inject a copy of local party as enemy
  local localParty = emu.memory.wram:readRange(0x23A98, 600)
  for i = 0, 599 do
    emu.memory.wram:write8(0x23CF0 + i, localParty:byte(i + 1))
  end

  -- 5. Set callback2 = CB2_InitBattle (proper entry point)
  emu.memory.iwram:write32(0x22C0, 0)               -- NULL callback1
  emu.memory.iwram:write16(0x26F8, 0)                -- zero gMain.state
  emu.memory.iwram:write32(0x22C4, 0x080363C1)       -- callback2 = CB2_InitBattle

  t.test("patches_applied", function()
    t.assertEqual(emu.memory.iwram:read32(0x22C4), 0x080363C1, "callback2_set")
    t.assertEqual(emu.memory.wram:read32(0x23364), 0x0000000E, "battleTypeFlags_set")
  end)

  -- Wait 180 frames (~3 sec) for battle to start
  t.waitFrames(180, function()
    t.screenshot("after_battle_wait")

    local inBattle = emu.memory.iwram:read8(0x2AF9)
    local cb2 = emu.memory.iwram:read32(0x22C4)

    t.test("battle_started_or_progressed", function()
      -- Either inBattle bit 1 changed to 1, or callback2 changed from our initial set
      local isBattle = (inBattle & 0x02) ~= 0
      local progressed = isBattle or (cb2 ~= 0x080363C1)
      t.assertTrue(progressed, "battle_progressed")
    end)

    -- Restore everything
    emu.memory.cart0:write32(0x00A4B0, origGMPI)
    emu.memory.iwram:write8(0x30FC, origWireless)
    emu.memory.iwram:write8(0x3124, origRemote)

    -- NOTE: We can't easily restore overworld state after triggering battle.
    -- The save state reload at the start of the next test run handles this.

    t.done()
  end)
end)
