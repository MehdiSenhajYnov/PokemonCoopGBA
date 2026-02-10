--[[
  quick_test.lua — Quick standalone test that doesn't rely on the runner framework
  Takes screenshots and writes results directly to a text file.
]]

local RESULTS_FILE = "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\quick_test_results.txt"
local SCREENSHOT_DIR = "C:\\Users\\mehdi\\Desktop\\Dev\\PokemonCoopGBA\\test_screenshots"

local results = {}
local screenshotCount = 0

local function log(msg)
  console:log("[QTEST] " .. msg)
end

local function addResult(name, pass, details)
  results[#results+1] = {name = name, pass = pass, details = details or ""}
  log((pass and "PASS" or "FAIL") .. ": " .. name .. (details and (" — " .. details) or ""))
end

local function screenshot(label)
  screenshotCount = screenshotCount + 1
  local filename = string.format("%s\\%03d_%s.png", SCREENSHOT_DIR, screenshotCount, label)
  -- Try method 1: emu:screenshot(path)
  local ok1, err1 = pcall(function() emu:screenshot(filename) end)
  if ok1 then
    log("Screenshot OK (method1): " .. filename)
    return
  end
  -- Try method 2: emu:screenshot() then savePNG
  local ok2, err2 = pcall(function()
    local img = emu:screenshot()
    if img then img:savePNG(filename) end
  end)
  if ok2 then
    log("Screenshot OK (method2): " .. filename)
  else
    log("Screenshot FAILED both methods: " .. tostring(err1) .. " / " .. tostring(err2))
  end
end

local function writeResults()
  local f = io.open(RESULTS_FILE, "w")
  if not f then
    log("ERROR: Cannot write results file")
    return
  end

  local passed, failed = 0, 0
  for _, r in ipairs(results) do
    if r.pass then passed = passed + 1 else failed = failed + 1 end
    f:write(string.format("%s: %s%s\n",
      r.pass and "PASS" or "FAIL",
      r.name,
      r.details ~= "" and (" — " .. r.details) or ""))
  end
  f:write(string.format("\nSUMMARY: %d/%d passed, %d failed\n", passed, passed + failed, failed))
  f:write("screenshots=" .. screenshotCount .. "\n")
  f:close()
  log(string.format("Results: %d/%d passed, %d failed", passed, passed + failed, failed))
end

-- ============================================================
log("Starting quick tests...")

local frameCount = 0
local phase = "stabilize"

callbacks:add("frame", function()
  frameCount = frameCount + 1

  if phase == "stabilize" then
    if frameCount < 60 then return end
    phase = "sync_tests"
    log("Stabilization complete, running sync tests...")
    screenshot("initial_state")

    -- === SYNC TESTS ===

    -- 1. Player position readable
    local ok3, px = pcall(function() return emu.memory.wram:read16(0x24CBC) end)
    local ok4, py = pcall(function() return emu.memory.wram:read16(0x24CBE) end)
    if ok3 and ok4 then
      addResult("player_position", px > 0 and py > 0, "x=" .. px .. " y=" .. py)
    else
      addResult("player_position", false, "read failed")
    end

    -- 2. BattleTypeFlags = 0 (or non-zero if already in battle)
    local ok2, btf = pcall(function() return emu.memory.wram:read32(0x23364) end)
    if ok2 then
      addResult("battleTypeFlags_readable", true, "btf=" .. string.format("0x%X", btf))
    else
      addResult("battleTypeFlags_readable", false, "read failed")
    end

    -- 3. Party count valid
    local ok5, count = pcall(function() return emu.memory.wram:read8(0x23A95) end)
    if ok5 then
      addResult("party_count", count >= 1 and count <= 6, "count=" .. count)
    else
      addResult("party_count", false, "read failed")
    end

    -- 4. First pokemon has data
    local ok6, pers = pcall(function() return emu.memory.wram:read32(0x23A98) end)
    if ok6 then
      addResult("first_pokemon_data", pers ~= 0, "personality=" .. string.format("0x%08X", pers))
    else
      addResult("first_pokemon_data", false, "read failed")
    end

    -- 5. gPlayerParty readable (600 bytes)
    local ok7, data = pcall(function() return emu.memory.wram:readRange(0x23A98, 600) end)
    if ok7 and data then
      addResult("party_600bytes", #data == 600, "len=" .. #data)
    else
      addResult("party_600bytes", false, "read failed")
    end

    -- 6. Enemy party writable
    local ok8, localData = pcall(function() return emu.memory.wram:readRange(0x23A98, 4) end)
    if ok8 and localData then
      local origEnemy = emu.memory.wram:readRange(0x23CF0, 4)
      for i = 0, 3 do emu.memory.wram:write8(0x23CF0 + i, localData:byte(i + 1)) end
      local injected = emu.memory.wram:readRange(0x23CF0, 4)
      addResult("enemy_party_writable", injected == localData, "matched=" .. tostring(injected == localData))
      for i = 0, 3 do emu.memory.wram:write8(0x23CF0 + i, origEnemy:byte(i + 1)) end
    else
      addResult("enemy_party_writable", false, "read failed")
    end

    -- 7. IWRAM patches work
    local origW = emu.memory.iwram:read8(0x30FC)
    local origR = emu.memory.iwram:read8(0x3124)
    emu.memory.iwram:write8(0x30FC, 0)
    emu.memory.iwram:write8(0x3124, 1)
    local w = emu.memory.iwram:read8(0x30FC)
    local r = emu.memory.iwram:read8(0x3124)
    addResult("iwram_patches", w == 0 and r == 1, "wireless=" .. w .. " remote=" .. r)
    emu.memory.iwram:write8(0x30FC, origW)
    emu.memory.iwram:write8(0x3124, origR)

    -- 8. GetBlockReceivedStatus dynamic patch
    local offset = 0x0A598
    local origGBRS = emu.memory.cart0:read16(offset)
    emu.memory.cart0:write16(offset, 0x2000)
    local blocked = emu.memory.cart0:read16(offset)
    emu.memory.cart0:write16(offset, 0x200F)
    local unblocked = emu.memory.cart0:read16(offset)
    emu.memory.cart0:write16(offset, origGBRS)
    addResult("GBRS_dynamic_patch", blocked == 0x2000 and unblocked == 0x200F,
      "blocked=" .. string.format("0x%X", blocked) .. " unblocked=" .. string.format("0x%X", unblocked))

    -- 9. gChosenAction/Move readable
    local okA, a = pcall(function() return emu.memory.wram:read8(0x23598) end)
    local okM, m = pcall(function() return emu.memory.wram:read16(0x235FA) end)
    addResult("gChosenAction_readable", okA, "val=" .. (okA and tostring(a) or "err"))
    addResult("gChosenMove_readable", okM, "val=" .. (okM and tostring(m) or "err"))

    -- 10. Callback2 in ROM range (IWRAM)
    local okCb, cb2 = pcall(function() return emu.memory.iwram:read32(0x22C4) end)
    if okCb then
      addResult("callback2_valid", cb2 >= 0x08000000 and cb2 < 0x0A000000,
        "cb2=" .. string.format("0x%08X", cb2))
    else
      addResult("callback2_valid", false, "read failed")
    end

    screenshot("sync_tests_done")

    -- Now trigger battle
    log("Triggering battle...")
    phase = "trigger_battle"

    -- Apply patches
    emu.memory.iwram:write8(0x30FC, 0)   -- gWirelessCommType = 0
    emu.memory.iwram:write8(0x3124, 1)   -- gReceivedRemoteLinkPlayers = 1
    emu.memory.cart0:write32(0x00A4B0, 0x47700020)  -- GetMultiplayerId → 0
    emu.memory.cart0:write32(0x0A568, 0x47702001)  -- IsLinkTaskFinished → 1
    emu.memory.cart0:write16(0x0A598, 0x200F)  -- GetBlockReceivedStatus → 0x0F

    -- BEQ→B patches
    emu.memory.cart0:write16(0x06F0F0, 0xE01C)
    emu.memory.cart0:write16(0x0787A4, 0xE01C)
    emu.memory.cart0:write16(0x032FC0, 0xE008)
    emu.memory.cart0:write16(0x040F50, 0xE007)
    emu.memory.cart0:write16(0x040EFC, 0xE009)
    emu.memory.cart0:write16(0x040E88, 0xE006)

    -- NOP HandleLinkBattleSetup (4 patches)
    emu.memory.cart0:write16(0x03CBEA, 0x46C0)
    emu.memory.cart0:write16(0x03CBEC, 0x46C0)
    emu.memory.cart0:write16(0x03CC76, 0x46C0)
    emu.memory.cart0:write16(0x03CC78, 0x46C0)

    -- NOP TryReceiveLinkBattleData (2 patches)
    emu.memory.cart0:write16(0x03CD48, 0x46C0)
    emu.memory.cart0:write16(0x03CD4A, 0x46C0)

    -- Set battle type: LINK(2) + IS_MASTER(4) + TRAINER(8) = 0xE
    emu.memory.wram:write32(0x23364, 0x0000000E)

    -- Inject local party as enemy
    local lp = emu.memory.wram:readRange(0x23A98, 600)
    for i = 0, 599 do emu.memory.wram:write8(0x23CF0 + i, lp:byte(i + 1)) end

    -- Set callback2 = CB2_InitBattle
    emu.memory.iwram:write32(0x22C0, 0)          -- NULL callback1
    emu.memory.iwram:write16(0x26F8, 0)           -- zero state
    emu.memory.iwram:write32(0x22C4, 0x080363C1)  -- CB2_InitBattle

    addResult("battle_trigger_set", true, "all patches applied, cb2=CB2_InitBattle")
    frameCount = 0

  elseif phase == "trigger_battle" then
    -- Press A every 15 frames to advance battle prompts
    if frameCount % 15 == 0 then
      pcall(function() emu:addKey(0) end)
    elseif frameCount % 15 == 2 then
      pcall(function() emu:clearKey(0) end)
    end

    -- Take screenshots at key points
    if frameCount == 30 then screenshot("battle_030f") end
    if frameCount == 60 then screenshot("battle_060f") end
    if frameCount == 120 then screenshot("battle_120f") end
    if frameCount == 180 then screenshot("battle_180f") end
    if frameCount == 240 then screenshot("battle_240f") end
    if frameCount == 300 then screenshot("battle_300f") end
    if frameCount == 360 then screenshot("battle_360f") end
    if frameCount == 450 then screenshot("battle_450f") end

    -- Log battle state every 60 frames
    if frameCount % 60 == 0 then
      local cb2 = emu.memory.iwram:read32(0x22C4)
      local btf = emu.memory.wram:read32(0x23364)
      local comm0 = emu.memory.wram:read8(0x2370E)
      local ef = emu.memory.wram:read32(0x233E0)
      log(string.format("f=%d cb2=0x%08X btf=0x%X comm0=%d ef=0x%X",
        frameCount, cb2, btf, comm0, ef))
    end

    -- After 480 frames (~8 sec), check result
    if frameCount >= 480 then
      phase = "done"

      local cb2 = emu.memory.iwram:read32(0x22C4)
      local inBattle = emu.memory.iwram:read8(0x2AF9)
      local isBattle = (inBattle & 0x02) ~= 0
      local btf = emu.memory.wram:read32(0x23364)
      local comm0 = emu.memory.wram:read8(0x2370E)
      local ef = emu.memory.wram:read32(0x233E0)

      addResult("battle_progressed", cb2 ~= 0x080363C1,
        string.format("cb2=0x%08X inBattle=%s btf=0x%X comm0=%d ef=0x%X", cb2, tostring(isBattle), btf, comm0, ef))

      screenshot("battle_final")
      writeResults()
      log("ALL TESTS DONE")
    end
  end
end)
