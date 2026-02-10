--[[
  EWRAM Battle Diff — Snapshot Comparison Tool

  Takes two snapshots of the full 256KB EWRAM and compares them byte-by-byte.
  Groups contiguous changed regions into blocks. Highlights large blocks that
  are likely gBattleBufferA/B, gBattleMons, or gBattleResources heap data.

  USAGE:
  1. Load this script in mGBA
  2. In the overworld, press START to take Snapshot A (baseline)
  3. Enter a trainer battle, wait for battle menu to appear
  4. Press SELECT to take Snapshot B (battle state)
  5. Diff is computed and printed to console automatically

  KEY INSIGHT: In pokeemerald-expansion, gBattleResources is a POINTER to
  heap-allocated memory. bufferA/B are at offsets within the allocated struct:
    bufferA = *gBattleResources + 16
    bufferB = *gBattleResources + 16 + 2048
  The diff will show the heap allocation block.

  OUTPUT: Address ranges, sizes, sample hex values for changed regions.
]]

console:log("=== EWRAM BATTLE DIFF TOOL ===")

local EWRAM_SIZE = 0x40000  -- 256KB
local CHUNK_SIZE = 4096

-- Known volatile regions to filter (not battle-related)
local VOLATILE_REGIONS = {
  -- Player position (changes while walking)
  { start = 0x02024CB0, stop = 0x02024CD0, name = "player_pos" },
  -- Camera (changes every frame during scroll)
  { start = 0x02024C80, stop = 0x02024CA0, name = "camera" },
  -- gMain struct (callback2, state, frame counter, etc.)
  { start = 0x02020648, stop = 0x020206C0, name = "gMain" },
  -- RNG (IWRAM, not in EWRAM scan, but add as safety)
}

-- Snapshots
local snapshotA = nil
local snapshotB = nil
local snapshotAFrame = 0
local snapshotBFrame = 0
local frameCount = 0

-- State tracking
local startPrev = false
local selectPrev = false

--[[
  Take a full EWRAM snapshot using readRange for performance.
  Returns a table of strings (chunks of 4096 bytes each).
]]
local function takeSnapshot()
  local chunks = {}
  local ok_count = 0

  for offset = 0, EWRAM_SIZE - CHUNK_SIZE, CHUNK_SIZE do
    local ok, data = pcall(emu.memory.wram.readRange, emu.memory.wram, offset, CHUNK_SIZE)
    if ok and data then
      chunks[offset] = data
      ok_count = ok_count + 1
    else
      chunks[offset] = nil
    end
  end

  console:log(string.format("  Snapshot taken: %d/%d chunks read (%d KB)",
    ok_count, EWRAM_SIZE / CHUNK_SIZE, ok_count * CHUNK_SIZE / 1024))

  return chunks
end

--[[
  Check if an address falls within a known volatile region.
]]
local function isVolatile(absAddr)
  for _, region in ipairs(VOLATILE_REGIONS) do
    if absAddr >= region.start and absAddr < region.stop then
      return true, region.name
    end
  end
  return false, nil
end

--[[
  Compare two snapshots byte-by-byte. Group contiguous changes into blocks.
]]
local function computeDiff(snapA, snapB)
  local blocks = {}
  local currentBlock = nil
  local totalChanged = 0
  local filteredBytes = 0

  for offset = 0, EWRAM_SIZE - CHUNK_SIZE, CHUNK_SIZE do
    local chunkA = snapA[offset]
    local chunkB = snapB[offset]

    if chunkA and chunkB and #chunkA == CHUNK_SIZE and #chunkB == CHUNK_SIZE then
      for i = 1, CHUNK_SIZE do
        local byteA = string.byte(chunkA, i)
        local byteB = string.byte(chunkB, i)
        local absAddr = 0x02000000 + offset + (i - 1)

        if byteA ~= byteB then
          local volatile, volName = isVolatile(absAddr)
          if volatile then
            filteredBytes = filteredBytes + 1
            -- End current block if we hit volatile region
            if currentBlock then
              table.insert(blocks, currentBlock)
              currentBlock = nil
            end
          else
            totalChanged = totalChanged + 1
            if currentBlock and absAddr == currentBlock.stop then
              -- Extend current block
              currentBlock.stop = absAddr + 1
              currentBlock.size = currentBlock.size + 1
              -- Store sample bytes (first 32 and last 32)
              if currentBlock.size <= 32 then
                table.insert(currentBlock.samplesA, byteA)
                table.insert(currentBlock.samplesB, byteB)
              end
            else
              -- Start new block (close previous if any)
              if currentBlock then
                table.insert(blocks, currentBlock)
              end
              currentBlock = {
                start = absAddr,
                stop = absAddr + 1,
                size = 1,
                samplesA = { byteA },
                samplesB = { byteB },
              }
            end
          end
        else
          -- Byte unchanged — allow gaps of up to 16 bytes within a block (merge nearby changes)
          if currentBlock and absAddr - currentBlock.stop < 16 then
            -- Keep block open (small gap)
          elseif currentBlock then
            table.insert(blocks, currentBlock)
            currentBlock = nil
          end
        end
      end
    end
  end

  if currentBlock then
    table.insert(blocks, currentBlock)
  end

  return blocks, totalChanged, filteredBytes
end

--[[
  Format bytes as hex string.
]]
local function hexBytes(bytes, maxLen)
  local parts = {}
  for i = 1, math.min(#bytes, maxLen or 16) do
    table.insert(parts, string.format("%02X", bytes[i]))
  end
  if #bytes > (maxLen or 16) then
    table.insert(parts, "...")
  end
  return table.concat(parts, " ")
end

--[[
  Print diff results to console.
]]
local function printDiff(blocks, totalChanged, filteredBytes)
  console:log("")
  console:log(string.format("=== EWRAM DIFF: %d changed bytes, %d filtered (volatile), %d blocks ===",
    totalChanged, filteredBytes, #blocks))
  console:log(string.format("  Snapshot A: frame %d | Snapshot B: frame %d",
    snapshotAFrame, snapshotBFrame))
  console:log("")

  -- Sort blocks by size (largest first)
  table.sort(blocks, function(a, b) return a.size > b.size end)

  -- Count blocks by size category
  local smallCount = 0    -- < 16 bytes
  local mediumCount = 0   -- 16-63 bytes
  local notableCount = 0  -- 64-255 bytes
  local largeCount = 0    -- >= 256 bytes

  for _, block in ipairs(blocks) do
    if block.size < 16 then smallCount = smallCount + 1
    elseif block.size < 64 then mediumCount = mediumCount + 1
    elseif block.size < 256 then notableCount = notableCount + 1
    else largeCount = largeCount + 1 end
  end

  console:log(string.format("  Summary: %d small(<16), %d medium(16-63), %d notable(64-255), %d LARGE(256+)",
    smallCount, mediumCount, notableCount, largeCount))
  console:log("")

  -- Only print blocks >= 64 bytes (skip noise)
  local printIndex = 0
  for _, block in ipairs(blocks) do
    if block.size >= 64 then
      printIndex = printIndex + 1
      local sizeLabel = ""
      if block.size >= 2048 then
        sizeLabel = " *** VERY LARGE (likely buffer or party data)"
      elseif block.size >= 256 then
        sizeLabel = " ** LARGE (likely gBattleMons or bufferA/B)"
      else
        sizeLabel = " * notable"
      end

      console:log(string.format("[Block %d] 0x%08X - 0x%08X  (%d bytes)%s",
        printIndex, block.start, block.stop - 1, block.size, sizeLabel))

      console:log(string.format("  First 16 before: %s", hexBytes(block.samplesA, 16)))
      console:log(string.format("  First 16 after:  %s", hexBytes(block.samplesB, 16)))

      -- Try to identify what the block might be
      if block.size >= 600 and block.size <= 620 then
        console:log("  -> Likely PARTY DATA (6 Pokemon x 100 bytes = 600)")
      elseif block.size >= 2048 and block.size <= 2100 then
        console:log("  -> Likely gBattleBufferA or gBattleBufferB (2048 bytes each)")
      elseif block.size >= 4096 then
        console:log("  -> Likely heap allocation (gBattleResources or battle struct)")
      end

      -- Check if first 4 bytes of "after" look like an EWRAM pointer (0x0200xxxx)
      if block.size >= 4 and #block.samplesB >= 4 then
        local ptr = block.samplesB[1] + block.samplesB[2] * 256 + block.samplesB[3] * 65536 + block.samplesB[4] * 16777216
        if ptr >= 0x02000000 and ptr <= 0x0203FFFF then
          console:log(string.format("  -> First 4 bytes = 0x%08X (EWRAM POINTER — possible gBattleResources!)", ptr))
        end
      end

      console:log("")
    end
  end

  -- Highlight potential gBattleResources
  console:log("--- ANALYSIS ---")
  local largeBlocks = {}
  for _, block in ipairs(blocks) do
    if block.size >= 256 then
      table.insert(largeBlocks, block)
    end
  end

  if #largeBlocks > 0 then
    console:log(string.format("  %d large blocks (>= 256 bytes):", #largeBlocks))
    for _, b in ipairs(largeBlocks) do
      console:log(string.format("    0x%08X  %d bytes", b.start, b.size))
    end
    console:log("")
    console:log("  TIP: Check if any of these contain EWRAM pointers at the start")
    console:log("  (values 0x0200xxxx). If so, that's likely gBattleResources.")
    console:log("  bufferA = *gBattleResources + 16")
    console:log("  bufferB = *gBattleResources + 16 + 0x800")
  else
    console:log("  No large blocks found. Battle may not have started yet?")
  end

  console:log("")
  console:log("=== END DIFF ===")
end

-- Frame callback: detect START/SELECT presses
local function onFrame()
  frameCount = frameCount + 1

  local ok, keys = pcall(function() return emu.memory.io:read16(0x0130) end)
  if not ok then return end

  local pressed = (~keys) & 0x000F
  local startNow = (pressed & 0x0008) ~= 0  -- START = bit 3
  local selectNow = (pressed & 0x0004) ~= 0  -- SELECT = bit 2

  -- Edge detect START: take Snapshot A
  if startNow and not startPrev then
    console:log("")
    console:log("[START pressed] Taking Snapshot A (baseline)...")
    snapshotA = takeSnapshot()
    snapshotAFrame = frameCount
    console:log("  Snapshot A ready. Now enter battle and press SELECT.")
  end

  -- Edge detect SELECT: take Snapshot B and compute diff
  if selectNow and not selectPrev then
    if not snapshotA then
      console:log("[SELECT pressed] ERROR: Take Snapshot A first (press START)")
    else
      console:log("")
      console:log("[SELECT pressed] Taking Snapshot B (battle state)...")
      snapshotB = takeSnapshot()
      snapshotBFrame = frameCount

      console:log("  Computing diff...")
      local blocks, totalChanged, filteredBytes = computeDiff(snapshotA, snapshotB)
      printDiff(blocks, totalChanged, filteredBytes)
    end
  end

  startPrev = startNow
  selectPrev = selectNow
end

callbacks:add("frame", onFrame)

console:log("")
console:log("Instructions:")
console:log("  1. In overworld: press START to take baseline snapshot")
console:log("  2. Enter a trainer battle, wait for battle menu")
console:log("  3. Press SELECT to take battle snapshot + compute diff")
console:log("  4. Check console for changed memory regions")
console:log("")
console:log("  Large blocks (>256 bytes) are highlighted as potential")
console:log("  gBattleBufferA/B, gBattleMons, or gBattleResources data.")
console:log("")
console:log("=== READY ===")
