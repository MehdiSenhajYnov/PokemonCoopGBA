--[[
  find_gMain_state.lua — Find gMain.state offset for Run & Bun

  HOW TO USE:
  1. Load this script in mGBA
  2. Walk around normally in the overworld
  3. Enter a building through a door
  4. The script will detect the state machine cycling (0→1→2→3...) during map load
  5. It will print the offset of gMain.state

  KNOWN VALUES:
  - gMain.callback2 = 0x0202064C → gMain base = 0x02020648
  - gMain.inBattle  = 0x020206AE → offset +0x66
  - Expected: gMain.state is 1 byte before the inBattle byte → offset +0x65

  The script monitors bytes near inBattle to find which one cycles through
  values 0→1→2→3... during a door warp (CB2_LoadMap state machine).
]]

local gMainBase = 0x02020648  -- callback2Addr - 4
local gMainBaseWRAM = gMainBase - 0x02000000
local callback2Offset = 4
local CB2_LoadMap = 0x08007441
local CB2_Overworld = 0x080A89A5

-- Candidates to check (offsets from gMain base)
-- We check a range around the expected +0x65 area
local candidates = {}
for off = 0x34, 0x68 do
  candidates[#candidates + 1] = off
end

-- State tracking
local prevCb2 = 0
local inMapLoad = false
local snapshots = {}  -- {[offset] = {values seen during map load}}
local frameCount = 0
local found = false

console:log("=== gMain.state Scanner ===")
console:log(string.format("gMain base = 0x%08X", gMainBase))
console:log("Walk through a door to trigger map load detection...")
console:log("")

-- Take initial snapshot
local function takeSnapshot(label)
  local snap = {}
  for _, off in ipairs(candidates) do
    local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, gMainBaseWRAM + off)
    if ok then
      snap[off] = val
    end
  end
  return snap
end

local initialSnap = takeSnapshot("initial")

callbacks:add("frame", function()
  if found then return end
  frameCount = frameCount + 1

  -- Read callback2
  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBaseWRAM + callback2Offset)
  if not ok then return end

  -- Detect CB2_LoadMap start
  if cb2 == CB2_LoadMap and prevCb2 ~= CB2_LoadMap then
    inMapLoad = true
    snapshots = {}
    console:log("[Scanner] CB2_LoadMap detected! Monitoring state bytes...")
  end

  -- During map load, record all candidate byte values
  if inMapLoad then
    for _, off in ipairs(candidates) do
      local ok2, val = pcall(emu.memory.wram.read8, emu.memory.wram, gMainBaseWRAM + off)
      if ok2 then
        if not snapshots[off] then snapshots[off] = {} end
        snapshots[off][#snapshots[off] + 1] = val
      end
    end
  end

  -- Detect CB2_LoadMap end (callback2 changed to something else)
  if inMapLoad and cb2 ~= CB2_LoadMap and prevCb2 == CB2_LoadMap then
    inMapLoad = false
    console:log("[Scanner] Map load complete. Analyzing state candidates...")
    console:log("")

    -- Find which candidate showed a state-machine pattern (0, 1, 2, 3...)
    local bestOff = nil
    local bestMaxVal = 0

    for _, off in ipairs(candidates) do
      local values = snapshots[off]
      if values and #values > 0 then
        -- Check if values form an increasing sequence starting from 0
        local isStateMachine = true
        local maxVal = 0
        local seenZero = false
        local uniqueVals = {}

        for _, v in ipairs(values) do
          uniqueVals[v] = true
          if v == 0 then seenZero = true end
          if v > maxVal then maxVal = v end
        end

        -- Count unique values
        local uniqueCount = 0
        for _ in pairs(uniqueVals) do uniqueCount = uniqueCount + 1 end

        -- State machine: starts at 0, has multiple unique values, max > 2
        if seenZero and uniqueCount >= 3 and maxVal >= 2 then
          local initVal = initialSnap[off] or -1
          console:log(string.format(
            "  +0x%02X: %d unique values (0..%d), initial=%d → CANDIDATE",
            off, uniqueCount, maxVal, initVal))

          if maxVal > bestMaxVal then
            bestMaxVal = maxVal
            bestOff = off
          end
        end
      end
    end

    console:log("")
    if bestOff then
      console:log("========================================")
      console:log(string.format("FOUND: gMain.state = gMain + 0x%02X", bestOff))
      console:log(string.format("       Address = 0x%08X", gMainBase + bestOff))
      console:log("========================================")
      console:log("")
      console:log("Update config/run_and_bun.lua warp section:")
      console:log(string.format("  gMainState = 0x%08X,", gMainBase + bestOff))
      found = true
    else
      console:log("No clear state machine pattern found.")
      console:log("Try entering a door from the overworld (not a warp pad).")

      -- Print all candidates that changed at all
      console:log("")
      console:log("Changed bytes during map load:")
      for _, off in ipairs(candidates) do
        local values = snapshots[off]
        if values and #values > 0 then
          local uniqueVals = {}
          for _, v in ipairs(values) do uniqueVals[v] = true end
          local uniqueCount = 0
          local valStr = ""
          for v in pairs(uniqueVals) do
            uniqueCount = uniqueCount + 1
            valStr = valStr .. string.format("%d ", v)
          end
          if uniqueCount > 1 then
            console:log(string.format("  +0x%02X: unique values = {%s}", off, valStr))
          end
        end
      end
    end
  end

  prevCb2 = cb2
end)

console:log("Scanner running. Enter a building to trigger detection.")
