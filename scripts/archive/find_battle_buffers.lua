--[[
  find_battle_buffers.lua — Runtime discovery of gBattleBufferA and gBattleBufferB

  Purpose: Dereference gBattleResources pointer in EWRAM to find the actual
  heap-allocated bufferA, bufferB, and transferBuffer addresses.

  From pokeemerald-expansion/include/battle.h:
    struct BattleResources {
        struct SecretBase *secretBase;              // +0x00 (4 bytes)
        struct BattleScriptsStack *battleScriptsStack; // +0x04 (4 bytes)
        struct BattleCallbacksStack *battleCallbackStack; // +0x08 (4 bytes)
        struct StatsArray *beforeLvlUp;             // +0x0C (4 bytes)
        u8 bufferA[MAX_BATTLERS_COUNT][0x200];      // +0x10 (0x800 bytes) -- vanilla expansion
        u8 bufferB[MAX_BATTLERS_COUNT][0x200];      // +0x810 (0x800 bytes) -- vanilla expansion
        u8 transferBuffer[0x100];                   // +0x1010 (0x100 bytes) -- vanilla expansion
    };

  NOTE: R&B (pokeemerald-expansion) may have EXTRA pointer fields before the inline
  buffers, which shifts the offsets. The config says bufferA_offset=0x024, bufferB_offset=0x824.
  This means R&B has 5 extra pointer fields (0x14 bytes) between beforeLvlUp and bufferA,
  making the total header 0x24 bytes (9 pointers) instead of 0x10 bytes (4 pointers).

  Usage: Run during an active battle (gBattleResources must be allocated).
    mGBA.exe -t "rom/Pokemon RunBun.ss1" --script "scripts/archive/find_battle_buffers.lua" "rom/Pokemon RunBun.gba"

  Known addresses:
    gBattleResources = 0x02023A18 (EWRAM pointer to heap-allocated struct)
]]

-- Known address from config
local GBATTLE_RESOURCES = 0x02023A18
local GBATTLE_STRUCT    = 0x02023A0C

-- Helper to read from correct memory domain
local function read32(addr)
  if addr >= 0x03000000 and addr < 0x03008000 then
    return emu.memory.iwram:read32(addr - 0x03000000)
  else
    return emu.memory.wram:read32(addr - 0x02000000)
  end
end

local function read8(addr)
  if addr >= 0x03000000 and addr < 0x03008000 then
    return emu.memory.iwram:read8(addr - 0x03000000)
  else
    return emu.memory.wram:read8(addr - 0x02000000)
  end
end

local function isValidEWRAM(addr)
  return addr >= 0x02000000 and addr < 0x02040000
end

local function isValidROM(addr)
  return addr >= 0x08000000 and addr < 0x0A000000
end

local function isValidPtr(addr)
  return isValidEWRAM(addr) or isValidROM(addr)
    or (addr >= 0x03000000 and addr < 0x03008000)
    or (addr >= 0x06000000 and addr < 0x06018000)  -- VRAM
end

local frameCount = 0
local scanned = false

callbacks:add("frame", function()
  frameCount = frameCount + 1

  -- Wait a few frames for battle to initialize (if loaded from save state in battle)
  if frameCount < 30 or scanned then return end
  scanned = true

  console:log("=== find_battle_buffers.lua ===")
  console:log("")

  -- Step 1: Read gBattleResources pointer
  local ok1, resPtr = pcall(read32, GBATTLE_RESOURCES)
  if not ok1 then
    console:log("ERROR: Could not read gBattleResources at 0x" .. string.format("%08X", GBATTLE_RESOURCES))
    return
  end

  console:log(string.format("gBattleResources  = 0x%08X (pointer at 0x%08X)", resPtr, GBATTLE_RESOURCES))

  if resPtr == 0 then
    console:log("ERROR: gBattleResources is NULL. Are you in a battle?")
    console:log("  This script must be run while a battle is active.")
    console:log("  The BattleResources struct is only allocated during battle.")
    return
  end

  if not isValidEWRAM(resPtr) then
    console:log(string.format("WARNING: gBattleResources points outside EWRAM: 0x%08X", resPtr))
    console:log("  Expected range: 0x02000000 - 0x0203FFFF")
    return
  end

  -- Step 2: Read gBattleStruct for reference
  local ok2, bsPtr = pcall(read32, GBATTLE_STRUCT)
  if ok2 then
    console:log(string.format("gBattleStruct     = 0x%08X (pointer at 0x%08X)", bsPtr, GBATTLE_STRUCT))
  end

  console:log("")

  -- Step 3: Dump first 0x30 bytes of the struct (header area with pointers)
  console:log("=== BattleResources struct header (first 0x30 bytes) ===")
  console:log("Offset  Value       Analysis")
  console:log("------  ----------  --------")

  local headerPtrs = {}
  for off = 0, 0x2C, 4 do
    local ok, val = pcall(read32, resPtr + off)
    if ok then
      local analysis = ""
      if val == 0 then
        analysis = "(NULL)"
      elseif isValidEWRAM(val) then
        analysis = "(EWRAM ptr)"
      elseif isValidROM(val) then
        analysis = "(ROM ptr)"
      elseif val >= 0x03000000 and val < 0x03008000 then
        analysis = "(IWRAM ptr)"
      elseif val >= 0x06000000 and val < 0x06018000 then
        analysis = "(VRAM ptr)"
      else
        analysis = "(data/invalid?)"
      end
      console:log(string.format("+0x%03X  0x%08X  %s", off, val, analysis))
      headerPtrs[off] = val
    else
      console:log(string.format("+0x%03X  READ ERROR", off))
    end
  end

  console:log("")

  -- Step 4: Identify where the inline buffer data starts
  -- In vanilla expansion: 4 pointers (0x10 bytes header), bufferA at +0x10
  -- In R&B: possibly 9 pointers (0x24 bytes header), bufferA at +0x24
  -- The key: bufferA/B are INLINE arrays, not pointers. They contain command data.
  -- bufferA[0][0] = command ID byte for battler 0.

  -- Try different header sizes to find where buffer data starts
  console:log("=== Probing for bufferA start (inline array, not pointer) ===")
  console:log("Looking for non-pointer data (buffer command bytes) after header pointers...")
  console:log("")

  -- Check various candidate offsets
  local candidates = { 0x010, 0x014, 0x018, 0x01C, 0x020, 0x024, 0x028 }

  for _, candOff in ipairs(candidates) do
    local bufABase = resPtr + candOff
    local bufBBase = resPtr + candOff + 0x800  -- bufferB is always bufferA + 0x800

    -- Read first 16 bytes of candidate bufferA[0]
    local bytes_a = {}
    local ok = pcall(function()
      for i = 0, 15 do
        bytes_a[i] = read8(bufABase + i)
      end
    end)

    if ok then
      local hexStr = ""
      for i = 0, 15 do
        hexStr = hexStr .. string.format("%02X ", bytes_a[i])
      end

      -- Check if first 4 bytes look like a pointer (would mean this is still header)
      local first4 = bytes_a[0] + bytes_a[1] * 256 + bytes_a[2] * 65536 + bytes_a[3] * 16777216
      local looksLikePtr = isValidPtr(first4)

      -- Read battler[1] at +0x200 offset
      local b1_first4 = 0
      pcall(function()
        b1_first4 = read32(bufABase + 0x200)
      end)

      -- Read corresponding bufferB area
      local bufB_first4 = 0
      pcall(function()
        bufB_first4 = read32(bufBBase)
      end)

      local verdict = ""
      if looksLikePtr then
        verdict = "  <- STILL HEADER (looks like pointer)"
      else
        -- Check if battler[1] area also has reasonable data
        verdict = "  <- CANDIDATE (non-pointer data)"
      end

      console:log(string.format("  +0x%03X: [%s]  first4=0x%08X  bufB+0x800=0x%08X%s",
        candOff, hexStr, first4, bufB_first4, verdict))
    else
      console:log(string.format("  +0x%03X: READ ERROR", candOff))
    end
  end

  console:log("")

  -- Step 5: Try the configured offsets (R&B: 0x024 / 0x824)
  console:log("=== Testing configured offsets (bufferA=+0x024, bufferB=+0x824) ===")
  local configBufA = resPtr + 0x024
  local configBufB = resPtr + 0x824

  console:log(string.format("bufferA base = resPtr + 0x024 = 0x%08X", configBufA))
  console:log(string.format("bufferB base = resPtr + 0x824 = 0x%08X", configBufB))
  console:log("")

  -- Dump first 32 bytes of each battler's bufferA
  for battler = 0, 3 do
    local bAddr = configBufA + battler * 0x200
    local hexStr = ""
    pcall(function()
      for i = 0, 31 do
        hexStr = hexStr .. string.format("%02X ", read8(bAddr + i))
      end
    end)
    console:log(string.format("  bufferA[%d] @ 0x%08X: %s", battler, bAddr, hexStr))
  end

  console:log("")

  for battler = 0, 3 do
    local bAddr = configBufB + battler * 0x200
    local hexStr = ""
    pcall(function()
      for i = 0, 31 do
        hexStr = hexStr .. string.format("%02X ", read8(bAddr + i))
      end
    end)
    console:log(string.format("  bufferB[%d] @ 0x%08X: %s", battler, bAddr, hexStr))
  end

  console:log("")

  -- Step 6: Also try vanilla expansion offsets (0x010 / 0x810)
  console:log("=== Testing vanilla expansion offsets (bufferA=+0x010, bufferB=+0x810) ===")
  local vanillaBufA = resPtr + 0x010
  local vanillaBufB = resPtr + 0x810

  console:log(string.format("bufferA base = resPtr + 0x010 = 0x%08X", vanillaBufA))
  console:log(string.format("bufferB base = resPtr + 0x810 = 0x%08X", vanillaBufB))
  console:log("")

  for battler = 0, 1 do
    local bAddr = vanillaBufA + battler * 0x200
    local hexStr = ""
    pcall(function()
      for i = 0, 31 do
        hexStr = hexStr .. string.format("%02X ", read8(bAddr + i))
      end
    end)
    console:log(string.format("  bufferA[%d] @ 0x%08X: %s", battler, bAddr, hexStr))
  end
  console:log("")

  -- Step 7: Scan for buffer signature
  -- During active battle, bufferA[activeBattler][0] = last command ID sent to controller.
  -- Common command IDs: 0x00=GetMonData, 0x01=GetRawMonData, 0x0F=ChooseMove, etc.
  -- The first byte is the command, bytes 1-3 often have related data.
  -- After battle init, at least one battler should have a non-zero command.
  console:log("=== Buffer signature analysis ===")
  console:log("Scanning for non-zero command bytes to identify correct offset...")
  console:log("")

  -- Test each candidate: if bufferA[0][0] or bufferA[1][0] has a valid command ID,
  -- this is likely the correct offset
  for _, testOff in ipairs({ 0x010, 0x014, 0x018, 0x01C, 0x020, 0x024 }) do
    local bufBase = resPtr + testOff
    local cmd0 = 0
    local cmd1 = 0
    pcall(function()
      cmd0 = read8(bufBase)
      cmd1 = read8(bufBase + 0x200)
    end)

    local valid = (cmd0 > 0 and cmd0 < 0x40) or (cmd1 > 0 and cmd1 < 0x40)
    console:log(string.format("  +0x%03X: cmd[0]=0x%02X cmd[1]=0x%02X %s",
      testOff, cmd0, cmd1, valid and "<- LIKELY BUFFERA" or ""))
  end

  console:log("")

  -- Step 8: transferBuffer location
  -- transferBuffer is right after bufferB (4 battlers x 0x200 = 0x800 after bufferA start + 0x800)
  -- So transferBuffer = bufferA_offset + 0x1000
  console:log("=== transferBuffer ===")
  local tbRB = resPtr + 0x024 + 0x1000
  local tbVanilla = resPtr + 0x010 + 0x1000
  console:log(string.format("  R&B offset:     0x%08X (resPtr + 0x1024)", tbRB))
  console:log(string.format("  Vanilla offset: 0x%08X (resPtr + 0x1010)", tbVanilla))

  console:log("")

  -- Step 9: Summary
  console:log("=== SUMMARY ===")
  console:log(string.format("gBattleResources pointer: 0x%08X", GBATTLE_RESOURCES))
  console:log(string.format("  -> struct at:           0x%08X", resPtr))
  console:log(string.format("  Struct size (vanilla):  0x1110 (4 ptrs + bufA[4x0x200] + bufB[4x0x200] + xfer[0x100])"))
  console:log(string.format("  Struct size (R&B):      0x1124 (9 ptrs + bufA[4x0x200] + bufB[4x0x200] + xfer[0x100])"))
  console:log("")
  console:log("To confirm correct offsets, trigger a battle command and check which")
  console:log("bufferA[0][0] shows a valid command ID (0x00-0x3F range).")
  console:log("")
  console:log("=== DONE ===")
end)
