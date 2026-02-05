--[[
  Warp Address Scanner
  =====================
  Finds gMain.callback2 address and CB2_LoadMap value by monitoring
  EWRAM changes during a normal map transition (entering a door).

  WHY: Writing playerX/Y/mapId/mapGroup to RAM only changes the values
  but does NOT reload the map. The game's tile data, collision, and
  events stay from the old map. To trigger a proper map transition,
  we need to set gMain.callback2 = CB2_LoadMap, which tells the game
  to execute its full map loading routine on the next frame.

  HOW IT WORKS:
  1. Scans EWRAM for addresses containing ROM function pointers
  2. Takes a snapshot of all those candidates
  3. Monitors them every frame during a door transition
  4. callback2 is the address that:
     - Changes from CB2_Overworld (ROM ptr) to CB2_LoadMap (different ROM ptr)
     - Then reverts back to CB2_Overworld when loading finishes

  USAGE:
  1. Load this script in mGBA (File > Load script)
  2. Wait for initial scan (~1 second, game may freeze briefly)
  3. Walk your character in front of a door
  4. Press B to arm the monitor
  5. Walk through the door (enter the building)
  6. Wait for results (appears after transition completes)
  7. Note the addresses printed in the console

  OUTPUT:
  - gMain.callback2 address (EWRAM)
  - CB2_LoadMap value (ROM function pointer)
  - CB2_Overworld value (ROM function pointer)
  - SaveBlock1 struct layout verification
]]

-- ============================================================
-- CONFIG: Change these if using a different ROM
-- ============================================================
local MAP_GROUP_ADDR = 0x02024CC0  -- Run & Bun
local MAP_ID_ADDR    = 0x02024CC1  -- Run & Bun
local PLAYER_X_ADDR  = 0x02024CBC  -- Run & Bun
local PLAYER_Y_ADDR  = 0x02024CBE  -- Run & Bun

-- How long to wait after map change before reporting (frames)
local POST_WARP_WAIT = 120

-- ============================================================
-- INTERNAL STATE
-- ============================================================
local candidates = {}
local scanDone = false
local monitoring = false
local prevSelect = false
local prevMapGroup = 0
local prevMapId = 0
local mapChanged = false
local frameCount = 0
local monitorStartFrame = 0
local postWarpFrames = 0
local trialCount = 0

-- ============================================================
-- HELPERS
-- ============================================================
local function toOff(addr)
  return addr - 0x02000000
end

local function isRomPtr(val)
  -- ROM function pointers are in 0x08000000-0x09FFFFFF range
  -- Thumb code has bit 0 set (odd address)
  return val >= 0x08000001 and val < 0x0A000000 and (val % 2) == 1
end

local function readMap()
  return emu.memory.wram:read8(toOff(MAP_GROUP_ADDR)),
         emu.memory.wram:read8(toOff(MAP_ID_ADDR))
end

-- ============================================================
-- STEP 1: Verify SaveBlock1 struct layout
-- ============================================================
local function verifySaveBlock1()
  console:log("")
  console:log("=== STEP 1: Verify SaveBlock1 Layout ===")
  console:log("If our addresses are SaveBlock1 fields, then:")
  console:log("  pos.x (s16)          = playerX")
  console:log("  pos.y (s16)          = playerY")
  console:log("  location.mapGroup    = mapGroup")
  console:log("  location.mapNum      = mapId")
  console:log("  location.warpId (s8) at +6")
  console:log("  location.x (s16)     at +8   <-- should match playerX")
  console:log("  location.y (s16)     at +10  <-- should match playerY")
  console:log("")

  -- Read known values
  local posX  = emu.memory.wram:read16(toOff(PLAYER_X_ADDR))
  local posY  = emu.memory.wram:read16(toOff(PLAYER_Y_ADDR))
  local mapGr = emu.memory.wram:read8(toOff(MAP_GROUP_ADDR))
  local mapId = emu.memory.wram:read8(toOff(MAP_ID_ADDR))

  -- Read predicted addresses
  local warpId = emu.memory.wram:read8(toOff(0x02024CC2))
  local locX   = emu.memory.wram:read16(toOff(0x02024CC4))
  local locY   = emu.memory.wram:read16(toOff(0x02024CC6))
  local contGr = emu.memory.wram:read8(toOff(0x02024CC8))
  local contId = emu.memory.wram:read8(toOff(0x02024CC9))

  console:log(string.format("  pos.x           = %d  (0x%08X)", posX, PLAYER_X_ADDR))
  console:log(string.format("  pos.y           = %d  (0x%08X)", posY, PLAYER_Y_ADDR))
  console:log(string.format("  loc.mapGroup    = %d  (0x%08X)", mapGr, MAP_GROUP_ADDR))
  console:log(string.format("  loc.mapNum      = %d  (0x%08X)", mapId, MAP_ID_ADDR))
  console:log(string.format("  loc.warpId      = %d  (0x%08X) [predicted]", warpId, 0x02024CC2))
  console:log(string.format("  loc.x           = %d  (0x%08X) [predicted]", locX, 0x02024CC4))
  console:log(string.format("  loc.y           = %d  (0x%08X) [predicted]", locY, 0x02024CC6))
  console:log(string.format("  contWarp.mapGrp = %d  (0x%08X) [predicted]", contGr, 0x02024CC8))
  console:log(string.format("  contWarp.mapNum = %d  (0x%08X) [predicted]", contId, 0x02024CC9))
  console:log("")

  if posX == locX and posY == locY then
    console:log("  >> loc.x/y MATCH pos.x/y -> SaveBlock1 layout CONFIRMED")
  else
    console:log(string.format("  >> WARNING: pos(%d,%d) != loc(%d,%d) -> layout may differ!", posX, posY, locX, locY))
    console:log("  >> The warp system may need different addresses")
  end
  console:log("")
end

-- ============================================================
-- STEP 2: Scan EWRAM for ROM pointer candidates
-- ============================================================
local function scanCandidates()
  console:log("=== STEP 2: Scanning EWRAM for ROM Pointers ===")
  console:log("Scanning 256KB... (may freeze briefly)")
  candidates = {}

  for offset = 0, 0x3FFFC, 4 do
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok and isRomPtr(val) then
      candidates[#candidates + 1] = {
        offset = offset,
        addr = 0x02000000 + offset,
        snapshot = val,
        firstChange = nil,
        reverted = false,
        revertFrame = nil,
      }
    end
  end

  console:log(string.format("Found %d ROM pointer candidates", #candidates))
  console:log("")
  console:log("=== STEP 3: Warp Monitor ===")
  console:log("Stand in front of a door, then press B.")
  console:log("Then walk through the door.")
  console:log("")
  scanDone = true
end

-- ============================================================
-- FRAME CALLBACK
-- ============================================================
callbacks:add("frame", function()
  frameCount = frameCount + 1

  -- One-time init
  if not scanDone then
    verifySaveBlock1()
    scanCandidates()
    return
  end

  -- B button edge detection (KEYINPUT register bit 1)
  local ok, raw = pcall(emu.memory.io.read16, emu.memory.io, 0x0130)
  local bDown = ok and ((~raw) & 0x0002) ~= 0
  if bDown and not prevSelect and not monitoring then
    monitoring = true
    mapChanged = false
    postWarpFrames = 0
    monitorStartFrame = frameCount
    prevMapGroup, prevMapId = readMap()

    -- Refresh snapshots
    for _, c in ipairs(candidates) do
      local s, v = pcall(emu.memory.wram.read32, emu.memory.wram, c.offset)
      c.snapshot = s and v or 0
      c.firstChange = nil
      c.reverted = false
      c.revertFrame = nil
    end

    trialCount = trialCount + 1
    console:log(string.format(">> ARMED (trial #%d)! Enter the door now... <<", trialCount))
  end
  prevSelect = bDown or false

  if not monitoring then return end

  -- Timeout: if no map change after 600 frames (~10s), disarm
  if not mapChanged and (frameCount - monitorStartFrame) > 600 then
    console:log(">> Timeout: no map change detected. Press SELECT to try again.")
    monitoring = false
    return
  end

  -- Check for map change
  local mg, mi = readMap()
  if not mapChanged and (mg ~= prevMapGroup or mi ~= prevMapId) then
    mapChanged = true
    postWarpFrames = 0
    console:log(string.format("MAP CHANGE at frame +%d: %d:%d -> %d:%d",
      frameCount - monitorStartFrame, prevMapGroup, prevMapId, mg, mi))
  end

  -- Monitor candidates every frame
  for _, c in ipairs(candidates) do
    local s, val = pcall(emu.memory.wram.read32, emu.memory.wram, c.offset)
    if not s then val = 0 end

    if val ~= c.snapshot then
      -- Value differs from snapshot
      if not c.firstChange then
        c.firstChange = { val = val, frame = frameCount }
      end
    else
      -- Value matches snapshot again (may have reverted)
      if c.firstChange and not c.reverted then
        c.reverted = true
        c.revertFrame = frameCount
      end
    end
  end

  -- After map change, wait then report
  if mapChanged then
    postWarpFrames = postWarpFrames + 1

    if postWarpFrames >= POST_WARP_WAIT then
      console:log("")
      console:log("============================================")
      console:log("=== RESULTS (Trial #" .. trialCount .. ") ===")
      console:log("============================================")

      -- Categorize
      local callbackHits = {}  -- ROM -> different ROM -> reverted = callback2
      local romToRom = {}      -- ROM -> different ROM, no revert

      for _, c in ipairs(candidates) do
        if c.firstChange and isRomPtr(c.firstChange.val) then
          if c.reverted then
            callbackHits[#callbackHits + 1] = c
          else
            romToRom[#romToRom + 1] = c
          end
        end
      end

      -- Report strong candidates (changed + reverted = transient callback)
      console:log("")
      console:log(string.format("CALLBACK CANDIDATES (ROM->ROM->revert): %d", #callbackHits))
      for _, c in ipairs(callbackHits) do
        console:log(string.format("  0x%08X: 0x%08X -> 0x%08X -> reverted",
          c.addr, c.snapshot, c.firstChange.val))
      end

      if #callbackHits > 0 then
        -- Pick the one most likely to be callback2
        -- (the one that changed earliest and reverted)
        local best = callbackHits[1]
        console:log("")
        console:log("========================================")
        console:log(string.format("  gMain.callback2  = 0x%08X", best.addr))
        console:log(string.format("  CB2_Overworld    = 0x%08X", best.snapshot))
        console:log(string.format("  CB2_LoadMap      = 0x%08X", best.firstChange.val))
        console:log("========================================")
        console:log("")
        console:log("Add these to your config file:")
        console:log("  warp = {")
        console:log(string.format("    callback2Addr = 0x%08X,", best.addr))
        console:log(string.format("    cb2LoadMap = 0x%08X,", best.firstChange.val))
        console:log("  },")
      elseif #romToRom > 0 then
        console:log("")
        console:log("No reverted candidates found.")
        console:log("Non-reverted ROM->ROM changes (callback2 might not have reverted yet):")
        for _, c in ipairs(romToRom) do
          console:log(string.format("  0x%08X: 0x%08X -> 0x%08X",
            c.addr, c.snapshot, c.firstChange.val))
        end
        console:log("Try increasing POST_WARP_WAIT or run another trial.")
      else
        console:log("")
        console:log("No ROM->ROM pointer changes detected!")
        console:log("Make sure you entered a door AFTER pressing SELECT.")
      end

      console:log("")
      console:log("Press B to run another trial.")
      monitoring = false
    end
  end
end)

console:log("")
console:log("================================================")
console:log("  Warp Address Scanner for Pokemon Co-op")
console:log("================================================")
console:log("Initializing...")
