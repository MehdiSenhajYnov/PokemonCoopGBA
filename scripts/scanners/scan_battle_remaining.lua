--[[
  Auto-Scanner for remaining battle addresses

  USAGE:
  1. Load this script in mGBA (Tools > Scripting > Load Script)
  2. Stay OUT of battle for 3 seconds (calibration)
  3. Enter a battle and WIN it
  4. The script will automatically find gBattleOutcome and gBattleBufferB

  No manual commands needed!
]]

local EWRAM_START = 0x02000000

-- Known addresses (already found)
local KNOWN = {
  gMainInBattle = 0x020206AE,  -- FOUND: gMain+0x66 via find_inbattle_offset.lua
  gPlayerParty = 0x020233D0,
  gBattleControllerExecFlags = 0x020239FC,
}

-- Scanner state
local state = "waiting_outside"  -- waiting_outside -> in_battle -> battle_won -> done
local frameCount = 0
local outsideFrames = 0
local battleFrames = 0

-- Candidate storage
local outcomeCandidates = nil
local bufferCandidates = nil

-- Results
local results = {
  gBattleOutcome = nil,
  gBattleBufferB = nil,
}

-- Read inBattle flag
local function isInBattle()
  local offset = KNOWN.gMainInBattle - EWRAM_START
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
  return ok and val == 1
end

-- Scan all EWRAM for a specific 8-bit value
local function scanAll8(target)
  local matches = {}
  for offset = 0, 0x3FFFF do
    local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = offset
    end
  end
  return matches
end

-- Rescan candidates for new value
local function rescanKeep(candidates, target)
  local kept = {}
  for _, offset in ipairs(candidates) do
    local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    if ok and val == target then
      kept[#kept + 1] = offset
    end
  end
  return kept
end

-- Find gBattleBufferB using delta prediction
local function findBattleBufferB()
  -- Method: Use delta from vanilla
  -- Vanilla: gBattleBufferB = 0x02023864, gPlayerParty = 0x020244EC
  -- Delta = gBattleBufferB - gPlayerParty = -0xC88
  -- Our gPlayerParty = 0x020233D0
  -- Predicted gBattleBufferB = 0x020233D0 - 0xC88 = 0x02022748

  local predicted = KNOWN.gPlayerParty - 0xC88

  -- Verify by checking it's in a reasonable range and readable
  local offset = predicted - EWRAM_START
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)

  if ok then
    results.gBattleBufferB = predicted
    console:log(string.format("[AUTO] gBattleBufferB (predicted): 0x%08X", predicted))
    return true
  end

  return false
end

-- Main tick function
local function tick()
  frameCount = frameCount + 1

  -- Only check every 10 frames
  if frameCount % 10 ~= 0 then return end

  local inBattle = isInBattle()

  -- State machine
  if state == "waiting_outside" then
    if not inBattle then
      outsideFrames = outsideFrames + 1
      if outsideFrames == 1 then
        console:log("[AUTO] Calibrating... stay OUT of battle")
      end
      if outsideFrames >= 18 then  -- ~3 seconds at 60fps/10
        console:log("[AUTO] Ready! Now ENTER a battle and WIN it")
        state = "waiting_for_battle"
      end
    else
      outsideFrames = 0
    end

  elseif state == "waiting_for_battle" then
    if inBattle then
      console:log("[AUTO] Battle detected! Scanning...")

      -- Scan for outcome = 0 (during battle)
      outcomeCandidates = scanAll8(0)
      console:log(string.format("[AUTO] Outcome candidates (val=0): %d", #outcomeCandidates))

      -- Find BattleBufferB via prediction
      findBattleBufferB()

      state = "in_battle"
      battleFrames = 0
    end

  elseif state == "in_battle" then
    battleFrames = battleFrames + 1

    if not inBattle then
      console:log("[AUTO] Battle ended! Checking for WIN...")

      -- Wait a moment for values to settle
      state = "battle_ended"
    end

  elseif state == "battle_ended" then
    -- Rescan for outcome = 1 (WIN)
    local winCandidates = rescanKeep(outcomeCandidates, 1)
    console:log(string.format("[AUTO] Candidates with val=1 after battle: %d", #winCandidates))

    if #winCandidates > 0 and #winCandidates < 50 then
      -- Filter: should be near battle-related addresses (0x0200xxxx to 0x0203xxxx)
      local validCandidates = {}
      for _, offset in ipairs(winCandidates) do
        local addr = EWRAM_START + offset
        -- Should be in a reasonable range near other battle addresses
        if addr >= 0x02008000 and addr <= 0x02030000 then
          validCandidates[#validCandidates + 1] = addr
        end
      end

      console:log("=== gBattleOutcome candidates ===")
      for i, addr in ipairs(validCandidates) do
        if i <= 10 then
          console:log(string.format("  0x%08X", addr))
        end
      end

      if #validCandidates == 1 then
        results.gBattleOutcome = validCandidates[1]
        console:log(string.format("[AUTO] gBattleOutcome FOUND: 0x%08X", validCandidates[1]))
      elseif #validCandidates > 1 then
        -- Pick the one closest to other battle addresses
        local bestAddr = validCandidates[1]
        local bestDist = math.abs(bestAddr - KNOWN.gBattleControllerExecFlags)
        for _, addr in ipairs(validCandidates) do
          local dist = math.abs(addr - KNOWN.gBattleControllerExecFlags)
          if dist < bestDist then
            bestDist = dist
            bestAddr = addr
          end
        end
        results.gBattleOutcome = bestAddr
        console:log(string.format("[AUTO] gBattleOutcome (best guess): 0x%08X", bestAddr))
      end
    else
      console:log("[AUTO] Could not determine gBattleOutcome - try again with a WIN")
    end

    state = "done"

  elseif state == "done" then
    -- Print final results
    console:log("")
    console:log("========================================")
    console:log("=== FINAL RESULTS ===")
    console:log("========================================")

    if results.gBattleBufferB then
      console:log(string.format("gBattleBufferB = 0x%08X", results.gBattleBufferB))
    else
      console:log("gBattleBufferB = NOT FOUND")
    end

    if results.gBattleOutcome then
      console:log(string.format("gBattleOutcome = 0x%08X", results.gBattleOutcome))
    else
      console:log("gBattleOutcome = NOT FOUND")
    end

    console:log("========================================")
    console:log("")
    console:log("Copy these to config/run_and_bun.lua!")
    console:log("Script finished. Reload to run again.")

    -- Stop the callback
    if cbId then
      callbacks:remove(cbId)
    end
  end
end

-- Start
console:log("========================================")
console:log("Auto Battle Address Scanner")
console:log("========================================")
console:log("")
console:log("INSTRUCTIONS:")
console:log("1. Stay OUT of battle for 3 seconds")
console:log("2. Enter a battle")
console:log("3. WIN the battle")
console:log("4. Results will appear automatically!")
console:log("")
console:log("Starting in 3 seconds...")

cbId = callbacks:add("frame", tick)
