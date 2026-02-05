--[[
  gMain Structure Verifier

  Verifies that gMain.inBattle is at 0x0202067F (derived from callback2Addr)
  and NOT at 0x020233E0 (which falls inside gPlayerParty data).

  USAGE:
  1. Load this script in mGBA (Tools > Scripting > Load Script)
  2. Walk around OUTSIDE of battle → inBattle should be 0
  3. Enter a battle → inBattle should be 1
  4. The script prints gMain fields every 60 frames

  DERIVATION:
    gMain.callback2     = 0x0202064C  (known, from config)
    gMain base          = 0x0202064C - 0x04 = 0x02020648
    gMain.inBattle      = 0x02020648 + 0x37 = 0x0202067F

  WHY 0x020233E0 IS WRONG:
    gPlayerParty = 0x020233D0
    0x020233E0 - 0x020233D0 = 0x10 → offset +16 in first Pokemon struct (otId field)
    This byte is often 0, making isFinished() return true immediately.
]]

local EWRAM_START = 0x02000000

-- Known addresses
local CALLBACK2_ADDR = 0x0202064C   -- gMain.callback2 (from config)
local GMAIN_BASE     = CALLBACK2_ADDR - 0x04  -- 0x02020648
local FALSE_ADDR     = 0x020233E0   -- The incorrect address (falls in gPlayerParty)

-- gMain struct field offsets
local FIELDS = {
  { name = "callback1",     offset = 0x00, size = 4 },
  { name = "callback2",     offset = 0x04, size = 4 },
  { name = "savedCallback", offset = 0x08, size = 4 },
  { name = "state",         offset = 0x35, size = 1 },
  { name = "inBattle",      offset = 0x37, size = 1 },
}

-- Correct inBattle address
local CORRECT_INBATTLE = GMAIN_BASE + 0x37  -- 0x0202067F

local function readWRAM(addr, size)
  local offset = addr - EWRAM_START
  if offset < 0 or offset >= 0x40000 then return nil end
  local ok, val
  if size == 1 then
    ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  elseif size == 2 then
    ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
  else
    ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
  end
  if ok then return val end
  return nil
end

local frameCount = 0
local prevCorrect = nil
local prevFalse = nil

local function tick()
  frameCount = frameCount + 1
  if frameCount % 60 ~= 0 then return end

  local correctVal = readWRAM(CORRECT_INBATTLE, 1)
  local falseVal = readWRAM(FALSE_ADDR, 1)

  -- Only print when values change or on first read
  if correctVal ~= prevCorrect or falseVal ~= prevFalse then
    console:log("")
    console:log(string.format("=== gMain Verify (frame %d) ===", frameCount))
    console:log(string.format("  CORRECT  0x%08X (gMain+0x37): inBattle = %s",
      CORRECT_INBATTLE, correctVal and tostring(correctVal) or "ERR"))
    console:log(string.format("  FALSE    0x%08X (in gPlayerParty): value = %s",
      FALSE_ADDR, falseVal and tostring(falseVal) or "ERR"))

    if correctVal == 1 then
      console:log("  >> IN BATTLE (correct addr confirms)")
    elseif correctVal == 0 then
      console:log("  >> NOT in battle (correct addr confirms)")
    end

    if falseVal ~= correctVal then
      console:log("  >> MISMATCH! False addr disagrees — proves it's wrong")
    end

    prevCorrect = correctVal
    prevFalse = falseVal
  end
end

-- Dump full gMain struct on demand
function dumpGMain()
  console:log("")
  console:log(string.format("=== gMain struct dump (base 0x%08X) ===", GMAIN_BASE))
  for _, f in ipairs(FIELDS) do
    local addr = GMAIN_BASE + f.offset
    local val = readWRAM(addr, f.size)
    if f.size == 4 then
      console:log(string.format("  +0x%02X %-16s = 0x%08X  (addr 0x%08X)",
        f.offset, f.name, val or 0, addr))
    else
      console:log(string.format("  +0x%02X %-16s = %d  (addr 0x%08X)",
        f.offset, f.name, val or -1, addr))
    end
  end

  -- Verify callback2 matches known value
  local cb2 = readWRAM(GMAIN_BASE + 0x04, 4)
  if cb2 then
    local isROM = cb2 >= 0x08000000 and cb2 < 0x0A000000
    console:log(string.format("  callback2 is %s ROM address", isROM and "a valid" or "NOT a valid"))
  end
end

_G.dumpGMain = dumpGMain

-- Start
console:log("========================================")
console:log("gMain Structure Verifier")
console:log("========================================")
console:log("")
console:log(string.format("gMain base (derived):  0x%08X", GMAIN_BASE))
console:log(string.format("CORRECT inBattle addr: 0x%08X (gMain + 0x37)", CORRECT_INBATTLE))
console:log(string.format("FALSE   inBattle addr: 0x%08X (in gPlayerParty!)", FALSE_ADDR))
console:log("")
console:log("Monitoring... walk around, then enter a battle.")
console:log("Values printed when they change.")
console:log("")
console:log("Commands:")
console:log("  dumpGMain()  - Full gMain struct dump")
console:log("")

-- Initial dump
dumpGMain()

cbId = callbacks:add("frame", tick)
