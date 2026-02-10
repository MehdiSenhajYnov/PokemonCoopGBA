-- Verify battler context variable addresses during a live PvP battle
-- Predicted addresses based on BSS layout near gBattlescriptCurrInstr (0x02023594)
-- Run with: mGBA.exe -t ss1 --script scripts/ToUse/verify_battler_context_vars.lua "rom/Pokemon RunBun.gba"

-- Predicted addresses (u8 unless noted)
local vars = {
  { name = "gBattlerAttacker",              addr = 0x0202358C, size = 1 },
  { name = "gBattlerTarget",                addr = 0x0202358D, size = 1 },
  { name = "gBattlerFainted",               addr = 0x0202358E, size = 1 },
  { name = "gEffectBattler",                addr = 0x0202358F, size = 1 },
  { name = "gPotentialItemEffectBattler",   addr = 0x02023590, size = 1 },
  { name = "gAbsentBattlerFlags",           addr = 0x02023591, size = 1 },
  { name = "gMultiHitCounter",              addr = 0x02023592, size = 1 },
  -- Cross-check anchors
  { name = "gBattlescriptCurrInstr",        addr = 0x02023594, size = 4 },
  { name = "gChosenActionByBattler[0]",     addr = 0x02023598, size = 1 },
  { name = "gChosenActionByBattler[1]",     addr = 0x02023599, size = 1 },
  { name = "gChosenActionByBattler[2]",     addr = 0x0202359A, size = 1 },
  { name = "gChosenActionByBattler[3]",     addr = 0x0202359B, size = 1 },
}

local gBattleTypeFlags = 0x02023364

local function toWRAM(addr) return addr - 0x02000000 end

local function readW8(addr)  return emu.memory.wram:read8(toWRAM(addr)) end
local function readW32(addr) return emu.memory.wram:read32(toWRAM(addr)) end

local frame = 0
local prevValues = {}
local changeLog = {}

callbacks:add("frame", function()
  frame = frame + 1

  -- Only run when in battle (gBattleTypeFlags nonzero)
  local ok, btf = pcall(readW32, gBattleTypeFlags)
  if not ok or btf == 0 then return end

  -- Every 60 frames: read and log all values
  if frame % 60 == 0 then
    console:log(string.format("=== BATTLER CONTEXT VARS (frame %d, btf=0x%08X) ===", frame, btf))

    local allPass = true

    for _, v in ipairs(vars) do
      local rok, val
      if v.size == 4 then
        rok, val = pcall(readW32, v.addr)
      else
        rok, val = pcall(readW8, v.addr)
      end

      if not rok then
        console:log(string.format("  ERR:  %s @ 0x%08X -- read failed", v.name, v.addr))
        allPass = false
      else
        local fmt = v.size == 4 and "0x%08X" or "%d"
        local valStr = string.format(fmt, val)

        -- Detect changes from previous read
        local changed = ""
        if prevValues[v.name] ~= nil and prevValues[v.name] ~= val then
          local prevFmt = v.size == 4 and "0x%08X" or "%d"
          changed = string.format(" (was %s)", string.format(prevFmt, prevValues[v.name]))
          table.insert(changeLog, string.format("f%d: %s %s->%s", frame, v.name,
            string.format(prevFmt, prevValues[v.name]), valStr))
        end
        prevValues[v.name] = val

        console:log(string.format("  %s @ 0x%08X = %s%s", v.name, v.addr, valStr, changed))

        -- Validation checks
        if v.name == "gBattlerAttacker" or v.name == "gBattlerTarget" or v.name == "gEffectBattler" then
          if val > 3 then
            console:log(string.format("    WARN: %s = %d (expected 0-3)", v.name, val))
            allPass = false
          end
        end

        if v.name == "gBattlescriptCurrInstr" then
          -- Should be a ROM pointer (0x08xxxxxx) when battle script is active
          local top = math.floor(val / 0x01000000)
          if top ~= 0x08 and val ~= 0 then
            console:log(string.format("    WARN: gBattlescriptCurrInstr = 0x%08X (not ROM ptr)", val))
            allPass = false
          end
        end
      end
    end

    if allPass then
      console:log("  PASS: all values in expected ranges")
    else
      console:log("  WARN: some values outside expected ranges")
    end
  end

  -- Between periodic logs, detect and log changes to key battler vars immediately
  if frame % 60 ~= 0 then
    local keyVars = { "gBattlerAttacker", "gBattlerTarget", "gEffectBattler", "gAbsentBattlerFlags" }
    for _, name in ipairs(keyVars) do
      for _, v in ipairs(vars) do
        if v.name == name then
          local rok, val = pcall(readW8, v.addr)
          if rok and prevValues[name] ~= nil and prevValues[name] ~= val then
            console:log(string.format("  CHANGE f%d: %s %d -> %d", frame, name, prevValues[name], val))
            table.insert(changeLog, string.format("f%d: %s %d->%d", frame, name, prevValues[name], val))
            prevValues[name] = val
          elseif rok and prevValues[name] == nil then
            prevValues[name] = val
          end
          break
        end
      end
    end
  end
end)

console:log("[verify_battler_context_vars] Loaded. Will log every 60 frames during battle.")
console:log("[verify_battler_context_vars] Monitoring: gBattlerAttacker(0x0202358C), gBattlerTarget(0x0202358D),")
console:log("  gEffectBattler(0x0202358F), gAbsentBattlerFlags(0x02023591)")
console:log("  Cross-check: gBattlescriptCurrInstr(0x02023594), gChosenActionByBattler(0x02023598)")
