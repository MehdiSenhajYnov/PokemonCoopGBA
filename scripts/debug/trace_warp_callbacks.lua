--[[
  trace_warp_callbacks.lua

  Traces callback2 values during a natural door warp.
  Walk through a door while this script is running to see the
  exact callback chain that Run & Bun uses.

  Also dumps gMain.state each frame to verify the state offset.
]]

local CB2_ADDR = 0x0202064C  -- gMain.callback2 (confirmed)
local GMIN_BASE = 0x02020648 -- gMain base (callback2 - 4)

-- Track callback2 changes
local lastCb2 = nil
local frameCount = 0
local tracing = false
local traceLog = {}

-- Known addresses
local CB2_OVERWORLD = 0x080A89A5
local CB2_LOADMAP = 0x08007441  -- What we THINK is CB2_LoadMap

console:log("=== Warp Callback Tracer ===")
console:log("Walk through a door to trace the callback chain.")
console:log(string.format("Watching callback2 at 0x%08X", CB2_ADDR))
console:log(string.format("gMain base at 0x%08X", GMIN_BASE))
console:log("")

-- Read various gMain fields for debugging
local function dumpGMainState()
  local base = GMIN_BASE - 0x02000000
  local cb1 = emu.memory.wram:read32(base + 0x00)
  local cb2 = emu.memory.wram:read32(base + 0x04)
  local saved = emu.memory.wram:read32(base + 0x08)

  -- Try multiple state offset candidates
  local state_35 = emu.memory.wram:read8(base + 0x35)  -- vanilla
  local state_36 = emu.memory.wram:read8(base + 0x36)  -- vanilla alt
  local state_37 = emu.memory.wram:read8(base + 0x37)  -- vanilla inBattle
  local state_65 = emu.memory.wram:read8(base + 0x65)  -- R&B estimated
  local state_66 = emu.memory.wram:read8(base + 0x66)  -- R&B inBattle (confirmed)

  return string.format(
    "cb1=0x%08X cb2=0x%08X saved=0x%08X | state candidates: +0x35=%d +0x36=%d +0x37=%d +0x65=%d +0x66=%d",
    cb1, cb2, saved, state_35, state_36, state_37, state_65, state_66)
end

callbacks:add("frame", function()
  frameCount = frameCount + 1

  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, CB2_ADDR - 0x02000000)
  if not ok then return end

  -- Detect callback2 change
  if cb2 ~= lastCb2 then
    if lastCb2 == CB2_OVERWORLD and cb2 ~= CB2_OVERWORLD then
      -- Leaving overworld — start tracing
      tracing = true
      traceLog = {}
      console:log(string.format("\n=== WARP STARTED at frame %d ===", frameCount))
    end

    local stateInfo = dumpGMainState()
    local entry = string.format("  Frame %d: callback2 = 0x%08X  %s", frameCount, cb2, stateInfo)
    console:log(entry)
    table.insert(traceLog, entry)

    if tracing and cb2 == CB2_OVERWORLD then
      -- Returned to overworld — warp complete
      console:log(string.format("=== WARP COMPLETE at frame %d (%d frames) ===", frameCount, #traceLog))
      console:log("\nFull callback chain:")
      for _, line in ipairs(traceLog) do
        console:log(line)
      end
      tracing = false
    end

    lastCb2 = cb2
  end

  -- During tracing, also log state progression every 5 frames
  if tracing and frameCount % 5 == 0 then
    local stateInfo = dumpGMainState()
    console:log(string.format("  [tick %d] %s", frameCount, stateInfo))
  end
end)

console:log("Tracer active. Walk through a door now.")
