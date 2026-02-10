--[[
  Battle Setup Verification Script
  Run in mGBA via --script. Waits 120 frames for game load, then runs checks.
  Results written to verify_results.txt AND mGBA console.
]]

local OUTPUT_FILE = "verify_results.txt"
local frameCount = 0
local hasRun = false

local results = {}
local passCount = 0
local failCount = 0
local allOutput = {}

local function log(msg)
  allOutput[#allOutput + 1] = msg
  console:log(msg)
end

local function check(name, condition, detail)
  if condition then
    passCount = passCount + 1
    results[#results + 1] = string.format("  PASS: %s %s", name, detail or "")
  else
    failCount = failCount + 1
    results[#results + 1] = string.format("  FAIL: %s %s", name, detail or "")
  end
  log(results[#results])
end

local function readEWRAM8(addr)
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, addr - 0x02000000)
  if ok then return val end return nil
end

local function readEWRAM16(addr)
  local ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, addr - 0x02000000)
  if ok then return val end return nil
end

local function readEWRAM32(addr)
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, addr - 0x02000000)
  if ok then return val end return nil
end

local function readIWRAM8(addr)
  local ok, val = pcall(emu.memory.iwram.read8, emu.memory.iwram, addr - 0x03000000)
  if ok then return val end return nil
end

local function readROM16(offset)
  local ok, val = pcall(emu.memory.cart0.read16, emu.memory.cart0, offset)
  if ok then return val end return nil
end

local function readROM32(offset)
  local ok, val = pcall(emu.memory.cart0.read32, emu.memory.cart0, offset)
  if ok then return val end return nil
end

local function writeFile()
  local f = io.open(OUTPUT_FILE, "w")
  if f then
    for _, line in ipairs(allOutput) do
      f:write(line .. "\n")
    end
    f:close()
    console:log("[verify] Results written to " .. OUTPUT_FILE)
  else
    console:log("[verify] WARNING: Could not write to " .. OUTPUT_FILE)
  end
end

local function runChecks()
  log("=== Battle Setup Verification ===")
  log("")

  -- 1. gMain struct
  log("[1] gMain struct layout (base=0x02020648)")
  local gMainBase = 0x02020648
  local cb1 = readEWRAM32(gMainBase + 0x00)
  local cb2 = readEWRAM32(gMainBase + 0x04)
  local savedCb = readEWRAM32(gMainBase + 0x08)
  local inBattle = readEWRAM8(gMainBase + 0x66)

  check("callback1 (gMain+0x00)", cb1 and cb1 >= 0x08000000 and cb1 < 0x0A000000,
    string.format("= 0x%08X", cb1 or 0))
  check("callback2 (gMain+0x04)", cb2 and cb2 >= 0x08000000 and cb2 < 0x0A000000,
    string.format("= 0x%08X", cb2 or 0))

  local CB2_OVERWORLD = 0x080A89A5
  check("callback2 = CB2_Overworld?", cb2 == CB2_OVERWORLD,
    string.format("0x%08X vs 0x%08X", cb2 or 0, CB2_OVERWORLD))

  check("savedCallback (gMain+0x08) readable", savedCb ~= nil,
    string.format("= 0x%08X", savedCb or 0))
  check("inBattle (gMain+0x66) = 0", inBattle == 0,
    string.format("= %d", inBattle or -1))
  log("")

  -- 2. gBattleTypeFlags
  log("[2] gBattleTypeFlags")
  local flags = readEWRAM32(0x02023364)
  check("NEW addr (0x02023364) readable", flags ~= nil, string.format("= 0x%08X", flags or 0))
  check("gBattleTypeFlags = 0 in overworld", flags == 0, string.format("= 0x%08X", flags or -1))
  local oldFlags = readEWRAM32(0x020090E8)
  log(string.format("  INFO: OLD addr 0x020090E8 = 0x%08X (was wrongly used before)", oldFlags or 0))
  log("")

  -- 3. CB2_InitBattle ROM
  log("[3] CB2_InitBattle (ROM 0x0363C0)")
  local cb2ib = readROM16(0x0363C0)
  check("PUSH prologue", cb2ib and ((cb2ib >> 8) == 0xB5),
    string.format("0x%04X %s", cb2ib or 0, (cb2ib and (cb2ib >> 8) == 0xB5) and "= PUSH{..LR}" or "NOT PUSH"))

  -- 4. CB2_InitBattleInternal ROM
  log("[4] CB2_InitBattleInternal (ROM 0x03648C)")
  local cb2ibi = readROM16(0x03648C)
  check("PUSH prologue", cb2ibi and ((cb2ibi >> 8) == 0xB5),
    string.format("0x%04X %s", cb2ibi or 0, (cb2ibi and (cb2ibi >> 8) == 0xB5) and "= PUSH{..LR}" or "NOT PUSH"))
  log("")

  -- 5. GetMultiplayerId
  log("[5] GetMultiplayerId (ROM 0x00A4B0)")
  local gmid = readROM16(0x00A4B0)
  check("readable", gmid ~= nil, string.format("= 0x%04X", gmid or 0))
  -- Test ROM write
  local okW = pcall(emu.memory.cart0.write16, emu.memory.cart0, 0x00A4B0, 0x2000)
  local rb = readROM16(0x00A4B0)
  check("ROM write+readback", okW and rb == 0x2000, string.format("wrote=0x2000 read=0x%04X", rb or 0))
  -- Restore
  if gmid then pcall(emu.memory.cart0.write16, emu.memory.cart0, 0x00A4B0, gmid) end
  log("")

  -- 6. BEQ→B patch targets
  log("[6] BEQ->B patch targets")
  local patches = {
    { name = "PlayerBufExec+0x1C",       offset = 0x06F0D4 + 0x1C, expect = 0xD01C },
    { name = "LinkOpponentBufExec+0x1C", offset = 0x078788 + 0x1C, expect = 0xD01C },
    { name = "PrepBufTransfer+0x18",     offset = 0x032FA8 + 0x18, expect = 0xD008 },
  }
  for _, p in ipairs(patches) do
    local instr = readROM16(p.offset)
    local status = "UNKNOWN"
    if instr == p.expect then status = "BEQ (correct)"
    elseif instr == (p.expect + 0x1000) then status = "ALREADY PATCHED"
    end
    check(p.name, instr == p.expect,
      string.format("0x%06X: 0x%04X (%s)", p.offset, instr or 0, status))
  end
  log("")

  -- 7. gBattleResources
  log("[7] gBattleResources (0x02023A18)")
  local resPtr = readEWRAM32(0x02023A18)
  if resPtr and resPtr == 0 then
    check("gBattleResources = NULL", true, "(normal in overworld)")
  elseif resPtr and resPtr >= 0x02000000 and resPtr < 0x02040000 then
    check("gBattleResources in EWRAM", true, string.format("= 0x%08X", resPtr))
  else
    check("gBattleResources", resPtr ~= nil, string.format("= 0x%08X", resPtr or 0))
  end
  log("")

  -- 8. IWRAM variables
  log("[8] IWRAM link variables")
  local gwct = readIWRAM8(0x030030FC)
  local grlp = readIWRAM8(0x03003124)
  local gbrs = readIWRAM8(0x0300307C)
  check("gWirelessCommType", gwct ~= nil, string.format("= %d", gwct or -1))
  check("gReceivedRemoteLinkPlayers", grlp ~= nil, string.format("= %d", grlp or -1))
  check("gBlockReceivedStatus", gbrs ~= nil, string.format("= %d", gbrs or -1))
  log("")

  -- 9. Party data
  log("[9] Party data")
  local ppCount = readEWRAM8(0x02023A95)
  check("gPlayerPartyCount (1-6)", ppCount and ppCount > 0 and ppCount <= 6,
    string.format("= %d", ppCount or 0))
  local hp = readEWRAM16(0x02023A98 + 86)
  local maxHp = readEWRAM16(0x02023A98 + 88)
  check("Pokemon[0] HP valid", hp and maxHp and hp > 0 and hp <= maxHp and maxHp < 1000,
    string.format("HP=%d/%d", hp or 0, maxHp or 0))
  log("")

  -- 10. gBattleCommunication
  log("[10] gBattleCommunication (0x0202370E)")
  local bcomm = readEWRAM8(0x0202370E)
  check("accessible", bcomm ~= nil, string.format("= %d", bcomm or -1))
  log("")

  -- Summary
  log("=== SUMMARY ===")
  log(string.format("  %d PASS, %d FAIL", passCount, failCount))
  if failCount == 0 then
    log("  All checks passed! Battle system ready for testing.")
  else
    log(string.format("  WARNING: %d checks failed.", failCount))
  end

  writeFile()
end

-- Frame callback: wait for game to load, then run
callbacks:add("frame", function()
  frameCount = frameCount + 1
  if not hasRun and frameCount >= 120 then
    hasRun = true
    runChecks()
  end
end)

console:log("[verify] Waiting 120 frames for game to load...")
