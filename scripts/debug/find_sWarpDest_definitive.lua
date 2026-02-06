--[[
  find_sWarpDest_definitive.lua

  DEFINITIVE sWarpDestination finder.

  Strategy: Before/After comparison during a natural door warp.
  1. Take a snapshot of all EWRAM locations matching SaveBlock1->location
  2. After the warp, check which locations changed to the NEW SaveBlock1->location
  3. sWarpDestination = the location(s) that changed from OLD pattern to NEW pattern

  Also checks the cluster scan address (0x020318A8) to see if it's real or false positive.
]]

local SB1_LOC = 0x02024CC0  -- SaveBlock1->location (mapGroup)
local CB2_ADDR = 0x0202064C  -- gMain.callback2
local CB2_OVERWORLD = 0x080A89A5
local CLUSTER_CANDIDATE = 0x020318A8  -- Address from cluster scan

-- Convert absolute address to WRAM offset
local function toOff(addr) return addr - 0x02000000 end

-- Read 8-byte WarpData at given WRAM offset
local function readWarp(off)
  local ok1, lo = pcall(emu.memory.wram.read32, emu.memory.wram, off)
  local ok2, hi = pcall(emu.memory.wram.read32, emu.memory.wram, off + 4)
  if ok1 and ok2 then return lo, hi end
  return nil, nil
end

-- Decode WarpData from two u32s
local function decodeWarp(lo, hi)
  if not lo or not hi then return "nil" end
  local mg = lo & 0xFF
  local mi = (lo >> 8) & 0xFF
  local wid = (lo >> 16) & 0xFF
  local x = hi & 0xFFFF
  local y = (hi >> 16) & 0xFFFF
  return string.format("mapGroup=%d mapId=%d warpId=%d x=%d y=%d (0x%08X 0x%08X)", mg, mi, wid, x, y, lo, hi)
end

console:log("=== DEFINITIVE sWarpDestination Finder ===")
console:log("Walk through a door. The script will find sWarpDestination by tracking changes.")
console:log("")

-- Read current SaveBlock1->location
local oldLo, oldHi = readWarp(toOff(SB1_LOC))
console:log("Current SaveBlock1->location: " .. decodeWarp(oldLo, oldHi))

-- Check cluster candidate
local clLo, clHi = readWarp(toOff(CLUSTER_CANDIDATE))
console:log(string.format("Cluster candidate (0x%08X): %s", CLUSTER_CANDIDATE, decodeWarp(clLo, clHi)))
if clLo == oldLo and clHi == oldHi then
  console:log("  → MATCHES SaveBlock1 (could be correct)")
else
  console:log("  → DOES NOT match SaveBlock1 (likely false positive!)")
end

-- Strategy 1: Snapshot all locations that match current SaveBlock1->location
console:log("\nScanning ALL EWRAM for current SaveBlock1->location pattern...")
local matchesBefore = {}
local skipOff = toOff(SB1_LOC)

for offset = 0, 0x3FFF8, 4 do
  if offset ~= skipOff then
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok and val == oldLo then
      local ok2, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
      if ok2 and val2 == oldHi then
        table.insert(matchesBefore, offset)
      end
    end
  end
end

console:log(string.format("Found %d matches for current pattern in EWRAM", #matchesBefore))
for _, off in ipairs(matchesBefore) do
  console:log(string.format("  Pre-warp match: 0x%08X", 0x02000000 + off))
end

-- Strategy 2: Also snapshot a broader set — match only mapGroup+mapId (first 2 bytes)
local partialMatchesBefore = {}
local refByte0 = oldLo & 0xFF      -- mapGroup
local refByte1 = (oldLo >> 8) & 0xFF  -- mapId

for offset = 0, 0x3FFFF, 4 do
  if offset ~= skipOff then
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok then
      local b0 = val & 0xFF
      local b1 = (val >> 8) & 0xFF
      if b0 == refByte0 and b1 == refByte1 then
        table.insert(partialMatchesBefore, offset)
      end
    end
  end
end

console:log(string.format("Found %d partial matches (mapGroup+mapId only)", #partialMatchesBefore))

-- Now wait for a natural warp
local state = "waiting"
local warpFrame = 0

callbacks:add("frame", function()
  local ok, cb2 = pcall(emu.memory.wram.read32, emu.memory.wram, toOff(CB2_ADDR))
  if not ok then return end

  if state == "waiting" then
    -- Detect warp start (leaving overworld)
    if cb2 ~= CB2_OVERWORLD and cb2 ~= 0 then
      state = "warping"
      warpFrame = 0
      console:log("\n=== WARP DETECTED ===")
    end
  elseif state == "warping" then
    warpFrame = warpFrame + 1
    -- Wait for warp completion (return to overworld)
    if cb2 == CB2_OVERWORLD then
      state = "analyzing"
      console:log(string.format("Warp complete after %d frames. Analyzing...", warpFrame))

      -- Read NEW SaveBlock1->location
      local newLo, newHi = readWarp(toOff(SB1_LOC))
      console:log("New SaveBlock1->location: " .. decodeWarp(newLo, newHi))

      if newLo == oldLo and newHi == oldHi then
        console:log("WARNING: SaveBlock1->location didn't change! Try a door to a DIFFERENT map.")
        state = "waiting"
        return
      end

      -- Check cluster candidate
      local clLoNew, clHiNew = readWarp(toOff(CLUSTER_CANDIDATE))
      console:log(string.format("Cluster candidate after warp: %s", decodeWarp(clLoNew, clHiNew)))
      if clLoNew == newLo and clHiNew == newHi then
        console:log("  → Cluster candidate MATCHES new location! IT IS sWarpDestination!")
      else
        console:log("  → Cluster candidate DOES NOT match. FALSE POSITIVE confirmed.")
      end

      -- Check all pre-warp full matches
      console:log("\nChecking pre-warp full matches for content change:")
      for _, off in ipairs(matchesBefore) do
        local lo, hi = readWarp(off)
        if lo == newLo and hi == newHi then
          console:log(string.format("  0x%08X: CHANGED to new pattern → sWarpDestination CANDIDATE!", 0x02000000 + off))
        elseif lo == oldLo and hi == oldHi then
          console:log(string.format("  0x%08X: unchanged (still old pattern)", 0x02000000 + off))
        else
          console:log(string.format("  0x%08X: changed to something else: %s", 0x02000000 + off, decodeWarp(lo, hi)))
        end
      end

      -- Scan ALL EWRAM for the new pattern (definitive search)
      console:log("\nFull EWRAM scan for NEW SaveBlock1->location pattern:")
      local newSkipOff = toOff(SB1_LOC)
      local newMatches = 0
      for offset = 0, 0x3FFF8, 4 do
        if offset ~= newSkipOff then
          local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
          if ok2 and val == newLo then
            local ok3, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
            if ok3 and val2 == newHi then
              newMatches = newMatches + 1
              -- Check neighbors for sDummyWarpData (FF FF FF 00 FF FF FF FF)
              local okN, n1 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 8)
              local okN2, n2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 12)
              local neighborInfo = ""
              if okN and okN2 then
                if n1 == 0x00FFFFFF and n2 == 0xFFFFFFFF then
                  neighborInfo = " [+8: sDummyWarpData!]"
                end
              end
              -- Check preceding 8 bytes (gLastUsedWarp should have OLD location)
              local okP, p1 = pcall(emu.memory.wram.read32, emu.memory.wram, offset - 8)
              local okP2, p2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset - 4)
              local prevInfo = ""
              if okP and okP2 then
                if p1 == oldLo and p2 == oldHi then
                  prevInfo = " [-8: OLD pattern = gLastUsedWarp!]"
                end
              end
              console:log(string.format("  MATCH at 0x%08X%s%s",
                0x02000000 + offset, neighborInfo, prevInfo))
            end
          end
        end
      end
      console:log(string.format("Total NEW pattern matches: %d", newMatches))

      -- Also scan for the OLD pattern (to find gLastUsedWarp)
      console:log("\nLocations still containing OLD pattern (candidates for gLastUsedWarp):")
      local oldMatches = 0
      for offset = 0, 0x3FFF8, 4 do
        if offset ~= newSkipOff then
          local ok2, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
          if ok2 and val == oldLo then
            local ok3, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
            if ok3 and val2 == oldHi then
              oldMatches = oldMatches + 1
              if oldMatches <= 10 then  -- limit output
                console:log(string.format("  OLD pattern at 0x%08X", 0x02000000 + offset))
              end
            end
          end
        end
      end
      console:log(string.format("Total OLD pattern matches: %d", oldMatches))

      console:log("\n=== ANALYSIS COMPLETE ===")
      console:log("Look for a NEW pattern match with [+8: sDummyWarpData!] and [-8: OLD pattern].")
      console:log("That address is sWarpDestination.")

      -- Update for next warp
      oldLo = newLo
      oldHi = newHi
      state = "done"
    end

    if warpFrame > 300 then
      console:log("Warp taking too long, resetting...")
      state = "waiting"
    end
  end
end)

console:log("\nWaiting for natural door warp... walk through a door now.")
