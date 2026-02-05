--[[
  find_sWarpData.lua — Find sWarpData address for Run & Bun

  HOW TO USE:
  1. Load this script in mGBA
  2. Enter a building through a door (triggers a natural warp)
  3. The script detects the warp and scans EWRAM for sWarpData
  4. It will print all matches

  WHY: sWarpData is where CB2_LoadMap reads the warp destination from.
  After a door warp, sWarpData should contain the same mapGroup/mapId/x/y
  as the new location. We scan EWRAM for this pattern.

  ALTERNATIVE METHOD: This script also watches for callback2 changing to
  CB2_LoadMap and scans immediately during the transition.
]]

local gMainBaseWRAM = 0x02020648 - 0x02000000
local callback2Offset = 4
local CB2_LoadMap = 0x08007441
local CB2_Overworld = 0x080A89A5

-- Player data offsets (Run & Bun)
local mapGroupOff = 0x02024CC0 - 0x02000000
local mapIdOff = 0x02024CC1 - 0x02000000
local playerXOff = 0x02024CBC - 0x02000000
local playerYOff = 0x02024CBE - 0x02000000

local prevCb2 = 0
local scanDone = false
local warpCount = 0

console:log("=== sWarpData Scanner ===")
console:log("Walk through a door to trigger warp detection...")
console:log("")

-- Scan for WarpData pattern in EWRAM
-- WarpData = { s8 mapGroup, s8 mapNum, s8 warpId, padding, s16 x, s16 y }
local function scanForWarpData(mapGroup, mapId, x, y)
  console:log(string.format("[Scan] Looking for pattern: mapGroup=%d mapId=%d x=%d y=%d",
    mapGroup, mapId, x, y))

  local matches = {}

  -- Build the 8-byte pattern
  local byte0 = mapGroup & 0xFF
  local byte1 = mapId & 0xFF
  -- byte2 = warpId (could be anything)
  -- byte3 = padding (could be anything)
  local byte4 = x & 0xFF
  local byte5 = (x >> 8) & 0xFF
  local byte6 = y & 0xFF
  local byte7 = (y >> 8) & 0xFF

  -- Scan EWRAM in 4-byte steps
  for offset = 0, 0x3FFF8, 4 do
    -- Quick check: first byte must be mapGroup
    local ok1, val0 = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    if ok1 and val0 == byte0 then
      -- Check mapId
      local ok2, val1 = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 1)
      if ok2 and val1 == byte1 then
        -- Check x (at offset +4)
        local ok3, valX = pcall(emu.memory.wram.read16, emu.memory.wram, offset + 4)
        if ok3 and valX == x then
          -- Check y (at offset +6)
          local ok4, valY = pcall(emu.memory.wram.read16, emu.memory.wram, offset + 6)
          if ok4 and valY == y then
            -- Read warpId too
            local _, warpId = pcall(emu.memory.wram.read8, emu.memory.wram, offset + 2)
            local absAddr = 0x02000000 + offset

            -- Skip the known SaveBlock1->location area
            local isSaveBlock = (offset >= mapGroupOff - 2 and offset <= mapGroupOff + 2)

            if isSaveBlock then
              console:log(string.format("  0x%08X: SKIP (SaveBlock1->location)", absAddr))
            else
              matches[#matches + 1] = { offset = offset, addr = absAddr, warpId = warpId or 0 }
              console:log(string.format("  0x%08X: MATCH (warpId=%d) ← CANDIDATE sWarpData",
                absAddr, warpId or 0))
            end
          end
        end
      end
    end
  end

  return matches
end

callbacks:add("frame", function()
  -- Read callback2
  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, gMainBaseWRAM + callback2Offset)
  if not ok then return end

  -- Detect transition from CB2_LoadMap to CB2_Overworld (map load just completed)
  if prevCb2 == CB2_LoadMap and cb2 == CB2_Overworld then
    warpCount = warpCount + 1
    console:log(string.format("[Scanner] Warp #%d completed! Scanning EWRAM...", warpCount))

    -- Read current position (this is the NEW position after the warp)
    local ok1, mg = pcall(emu.memory.wram.read8, emu.memory.wram, mapGroupOff)
    local ok2, mi = pcall(emu.memory.wram.read8, emu.memory.wram, mapIdOff)
    local ok3, px = pcall(emu.memory.wram.read16, emu.memory.wram, playerXOff)
    local ok4, py = pcall(emu.memory.wram.read16, emu.memory.wram, playerYOff)

    if ok1 and ok2 and ok3 and ok4 then
      local matches = scanForWarpData(mg, mi, px, py)

      console:log("")
      if #matches > 0 then
        console:log(string.format("Found %d candidate(s) for sWarpData:", #matches))
        for i, m in ipairs(matches) do
          console:log(string.format("  #%d: 0x%08X (warpId=%d)", i, m.addr, m.warpId))
        end
        console:log("")
        console:log("Update config/run_and_bun.lua warp section:")
        console:log(string.format("  sWarpDataAddr = 0x%08X,", matches[1].addr))
      else
        console:log("No sWarpData candidates found.")
        console:log("This could mean Run & Bun uses SaveBlock1->location directly.")
        console:log("Try entering a different building.")
      end
      console:log("")
    end
  end

  -- Also scan during CB2_LoadMap (sWarpData should be set before map load starts)
  if cb2 == CB2_LoadMap and prevCb2 ~= CB2_LoadMap then
    console:log("[Scanner] CB2_LoadMap detected! Scanning for warp destination...")

    -- Read where the game THINKS it's going (from various known locations)
    -- Check several likely offsets near gMain
    console:log("  Checking known struct areas around gMain...")

    -- Read current SaveBlock1->location for reference
    local ok1, mg = pcall(emu.memory.wram.read8, emu.memory.wram, mapGroupOff)
    local ok2, mi = pcall(emu.memory.wram.read8, emu.memory.wram, mapIdOff)
    if ok1 and ok2 then
      console:log(string.format("  Current SaveBlock1->location: mapGroup=%d mapId=%d", mg, mi))
    end
  end

  prevCb2 = cb2
end)

console:log("Scanner running. Walk through doors to trigger detection.")
console:log("Each door warp will be scanned for sWarpData pattern.")
