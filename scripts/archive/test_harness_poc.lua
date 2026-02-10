-- test_harness_poc.lua — Proof of Concept: autonomous test harness for mGBA
-- Launched via: mGBA.exe --script scripts/test_harness_poc.lua rom/Pokemon\ RunBun.gba

local RESULTS_FILE = script.dir .. "/../test_results.json"
local SAVE_STATE_SLOT = 1
local WAIT_FRAMES = 30  -- wait N frames after save state load for game to stabilize

-- Simple JSON encoder (enough for test results)
local function jsonEncode(val, indent)
    indent = indent or 0
    local t = type(val)
    if t == "nil" then return "null"
    elseif t == "boolean" then return tostring(val)
    elseif t == "number" then return tostring(val)
    elseif t == "string" then
        return '"' .. val:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n') .. '"'
    elseif t == "table" then
        -- Check if array
        local isArray = (#val > 0)
        if isArray then
            local parts = {}
            for _, v in ipairs(val) do
                parts[#parts+1] = jsonEncode(v, indent+1)
            end
            return "[" .. table.concat(parts, ",") .. "]"
        else
            local parts = {}
            for k, v in pairs(val) do
                parts[#parts+1] = '"' .. tostring(k) .. '":' .. jsonEncode(v, indent+1)
            end
            return "{" .. table.concat(parts, ",") .. "}"
        end
    end
    return '"??"'
end

-- Test results accumulator
local results = {
    timestamp = os.date("%Y-%m-%d %H:%M:%S"),
    tests = {},
    summary = { passed = 0, failed = 0, total = 0 }
}

local function addResult(name, passed, details)
    results.summary.total = results.summary.total + 1
    if passed then
        results.summary.passed = results.summary.passed + 1
    else
        results.summary.failed = results.summary.failed + 1
    end
    results.tests[#results.tests+1] = {
        name = name,
        passed = passed,
        details = details or ""
    }
end

-- Write results to file and exit
local function finish()
    local f = io.open(RESULTS_FILE, "w")
    if f then
        f:write(jsonEncode(results))
        f:close()
        console:log("=== TEST RESULTS WRITTEN TO: " .. RESULTS_FILE .. " ===")
        console:log("Passed: " .. results.summary.passed .. "/" .. results.summary.total)
    else
        console:log("ERROR: Could not write results file!")
    end
    -- Give a few frames for file to flush, then exit
    local exitFrames = 5
    local exitCb
    exitCb = callbacks:add("frame", function()
        exitFrames = exitFrames - 1
        if exitFrames <= 0 then
            exitCb:remove()
            os.exit(0)
        end
    end)
end

-- ========== TEST DEFINITIONS ==========

local function runTests()
    console:log("=== RUNNING TESTS ===")

    -- Test 1: EWRAM readable (player position)
    local ok, playerX = pcall(function() return emu.memory.ewram:read16(0x24CBC) end)
    addResult("ewram_read_playerX", ok and playerX ~= nil,
        ok and ("playerX=" .. tostring(playerX)) or "EWRAM read failed")

    -- Test 2: Player Y
    local ok2, playerY = pcall(function() return emu.memory.ewram:read16(0x24CBE) end)
    addResult("ewram_read_playerY", ok2 and playerY ~= nil,
        ok2 and ("playerY=" .. tostring(playerY)) or "EWRAM read failed")

    -- Test 3: Map group/id
    local ok3, mapGroup = pcall(function() return emu.memory.ewram:read8(0x24CC0) end)
    local ok4, mapId = pcall(function() return emu.memory.ewram:read8(0x24CC1) end)
    addResult("ewram_read_map", ok3 and ok4,
        "mapGroup=" .. tostring(mapGroup) .. " mapId=" .. tostring(mapId))

    -- Test 4: gPlayerParty readable (first pokemon species)
    local ok5, species = pcall(function() return emu.memory.ewram:read16(0x23A98) end)
    addResult("ewram_read_party_species", ok5 and species ~= nil and species > 0,
        ok5 and ("species_raw=" .. tostring(species) .. " (encrypted)") or "Party read failed")

    -- Test 5: gPlayerPartyCount
    local ok6, partyCount = pcall(function() return emu.memory.ewram:read8(0x23A95) end)
    addResult("ewram_read_party_count", ok6 and partyCount ~= nil and partyCount >= 1 and partyCount <= 6,
        ok6 and ("partyCount=" .. tostring(partyCount)) or "Party count read failed")

    -- Test 6: IWRAM readable (camera offsets)
    local ok7, camX = pcall(function() return emu.memory.iwram:read16(0x5DFC) end)
    addResult("iwram_read_cameraX", ok7 and camX ~= nil,
        ok7 and ("cameraX=" .. tostring(camX)) or "IWRAM read failed")

    -- Test 7: ROM readable (cart0)
    local ok8, romByte = pcall(function() return emu.memory.cart0:read8(0) end)
    addResult("cart0_read", ok8 and romByte ~= nil,
        ok8 and ("rom[0]=" .. string.format("0x%02X", romByte)) or "cart0 read failed")

    -- Test 8: cart0 write test (write + readback, then restore)
    local testAddr = 0x00A4B0  -- GetMultiplayerId ROM offset
    local ok9, original = pcall(function() return emu.memory.cart0:read8(testAddr) end)
    local writeOk = false
    if ok9 then
        local okW = pcall(function() emu.memory.cart0:write8(testAddr, 0xAA) end)
        if okW then
            local readback = emu.memory.cart0:read8(testAddr)
            writeOk = (readback == 0xAA)
            -- Restore original
            emu.memory.cart0:write8(testAddr, original)
        end
    end
    addResult("cart0_write_readback", writeOk,
        writeOk and "cart0 write+readback OK" or "cart0 write FAILED")

    -- Test 9: gMain.callback2 readable
    local ok10, cb2 = pcall(function() return emu.memory.ewram:read32(0x064C) end)
    addResult("ewram_read_callback2", ok10 and cb2 ~= nil,
        ok10 and string.format("callback2=0x%08X", cb2) or "callback2 read failed")

    -- Test 10: gBattleTypeFlags readable
    local ok11, btf = pcall(function() return emu.memory.ewram:read32(0x90E8) end)
    addResult("ewram_read_battleTypeFlags", ok11 and btf ~= nil,
        ok11 and string.format("battleTypeFlags=0x%08X", btf) or "battleTypeFlags read failed")

    -- Test 11: io.open works (can we write files?)
    local testFile = script.dir .. "/../test_io_check.tmp"
    local fOk = pcall(function()
        local f = io.open(testFile, "w")
        f:write("test")
        f:close()
        os.remove(testFile)
    end)
    addResult("io_open_write", fOk, fOk and "File I/O works" or "File I/O BROKEN")

    -- Test 12: os.clock available
    local clockOk, clockVal = pcall(os.clock)
    addResult("os_clock", clockOk, clockOk and ("os.clock()=" .. tostring(clockVal)) or "os.clock failed")

    console:log("=== ALL TESTS DONE ===")
    finish()
end

-- ========== MAIN: Load save state then run tests ==========
console:log("=== TEST HARNESS POC ===")
console:log("Loading save state slot " .. SAVE_STATE_SLOT .. "...")

local loadOk = pcall(function() emu:loadStateSlot(SAVE_STATE_SLOT) end)
if not loadOk then
    addResult("load_save_state", false, "Failed to load save state slot " .. SAVE_STATE_SLOT)
    finish()
else
    addResult("load_save_state", true, "Save state loaded OK")
    -- Wait N frames for game to stabilize
    local frameCount = 0
    local waitCb
    waitCb = callbacks:add("frame", function()
        frameCount = frameCount + 1
        if frameCount >= WAIT_FRAMES then
            waitCb:remove()
            runTests()
        end
    end)
end
