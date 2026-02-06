--[[
  Hardware Abstraction Layer (HAL)

  Provides safe memory access functions for GBA hardware
  Handles pointer dereferencing, DMA protection, and sanity checks

  Adapted for mGBA development build API
]]

local HAL = {}

-- GBA Memory Regions
local WRAM_START = 0x00000000  -- WRAM is accessed at offset 0 in emu.memory.wram
local WRAM_SIZE = 0x00040000   -- 256KB
local IWRAM_START = 0x00000000 -- IWRAM is accessed at offset 0 in emu.memory.iwram
local IWRAM_SIZE = 0x00008000  -- 32KB

-- Current game configuration
local config = nil

--[[
  Initialize HAL with game-specific configuration
  @param gameConfig Table containing memory offsets for the current ROM
]]
function HAL.init(gameConfig)
  config = gameConfig
  console:log("[HAL] Initialized with config: " .. (gameConfig.name or "Unknown"))
  if config.warp then
    console:log(string.format("[HAL] Warp config OK: callback2=0x%08X cb2LoadMap=0x%08X",
      config.warp.callback2Addr, config.warp.cb2LoadMap))
    -- Scan ROM for WarpIntoMap address (needed for EWRAM trampoline)
    -- CB2_LoadMap alone hangs because gMapHeader isn't loaded.
    -- The trampoline calls WarpIntoMap + CB2_LoadMap from executable EWRAM.
    HAL.scanROMForWarpFunction()
  else
    console:log("[HAL] WARNING: No warp config in profile — duel warp will not work")
  end
end

--[[
  Check if address is within valid WRAM range
  Note: mGBA's emu.memory.wram uses relative offsets (0x02024844 becomes 0x24844)
  @param address Memory address to check
  @return boolean True if address is valid
]]
local function isValidWRAM(address)
  -- Convert absolute GBA address to WRAM offset
  local offset = address - 0x02000000
  return offset >= WRAM_START and offset < WRAM_SIZE
end

--[[
  Convert absolute GBA address to WRAM offset
  @param address Absolute address (e.g., 0x02024844)
  @return offset Relative offset (e.g., 0x24844)
]]
local function toWRAMOffset(address)
  return address - 0x02000000
end

--[[
  Safe memory read with error handling
  @param address Memory address to read from (absolute GBA address)
  @param size Read size: 1 (byte), 2 (halfword), 4 (word)
  @return value or nil on error
]]
local function safeRead(address, size)
  if not isValidWRAM(address) then
    return nil
  end

  local offset = toWRAMOffset(address)

  local success, value = pcall(function()
    if size == 1 then
      return emu.memory.wram:read8(offset)
    elseif size == 2 then
      return emu.memory.wram:read16(offset)
    elseif size == 4 then
      return emu.memory.wram:read32(offset)
    end
  end)

  if success then
    return value
  end

  return nil
end

--[[
  Check if address is within valid IWRAM range (0x03000000 - 0x03007FFF)
  @param address Absolute GBA IWRAM address
  @return boolean
]]
local function isValidIWRAM(address)
  local offset = address - 0x03000000
  return offset >= IWRAM_START and offset < IWRAM_SIZE
end

--[[
  Convert absolute GBA IWRAM address to IWRAM offset
  @param address Absolute address (e.g., 0x03005DFC)
  @return offset Relative offset (e.g., 0x5DFC)
]]
local function toIWRAMOffset(address)
  return address - 0x03000000
end

--[[
  Safe IWRAM read with error handling
  @param address Absolute GBA IWRAM address (0x03xxxxxx)
  @param size Read size: 1 (byte), 2 (halfword), 4 (word)
  @return value or nil on error
]]
local function safeReadIWRAM(address, size)
  if not isValidIWRAM(address) then
    return nil
  end

  local offset = toIWRAMOffset(address)

  local success, value = pcall(function()
    if size == 1 then
      return emu.memory.iwram:read8(offset)
    elseif size == 2 then
      return emu.memory.iwram:read16(offset)
    elseif size == 4 then
      return emu.memory.iwram:read32(offset)
    end
  end)

  if success then
    return value
  end

  return nil
end

--[[
  Read pointer chain safely
  Follows a chain of pointers to reach final address

  @param base Base address to start from
  @param offsets Array of offsets to follow
  @return final address or nil on error

  Example: readSafePointer(0x02000000, {0x10, 0x20})
    1. Read pointer at 0x02000000
    2. Add 0x10 to get intermediate address
    3. Read pointer at intermediate
    4. Add 0x20 to get final address
]]
function HAL.readSafePointer(base, offsets)
  if not offsets or #offsets == 0 then
    return base
  end

  local currentAddress = base

  for i, offset in ipairs(offsets) do
    -- For last offset, don't dereference - just add it
    if i == #offsets then
      currentAddress = currentAddress + offset
      break
    end

    -- Read pointer at current address
    local pointer = safeRead(currentAddress, 4)
    if not pointer then
      return nil
    end

    -- Add offset to get next address
    currentAddress = pointer + offset

    -- Validate intermediate address
    if not isValidWRAM(currentAddress) then
      return nil
    end
  end

  return currentAddress
end

--[[
  Safe write to memory (for future warp functionality)
  @param address Memory address
  @param value Value to write
  @param size Write size: 1, 2, or 4
  @return boolean Success status
]]
function HAL.safeWrite(address, value, size)
  if not isValidWRAM(address) then
    return false
  end

  local offset = toWRAMOffset(address)

  local success = pcall(function()
    if size == 1 then
      emu.memory.wram:write8(offset, value)
    elseif size == 2 then
      emu.memory.wram:write16(offset, value)
    elseif size == 4 then
      emu.memory.wram:write32(offset, value)
    end
  end)

  return success
end

--[[
  Game-specific read functions
  These use the loaded configuration
]]

--[[
  Read value supporting both static and dynamic offset modes
  @param offsetConfig Either a number (static) or table {pointer, offsets} (dynamic)
  @param size Read size (1, 2, or 4 bytes)
  @return value or nil
]]
local function readOffset(offsetConfig, size)
  if not offsetConfig then
    return nil
  end

  -- Static mode: offset is a direct address
  if type(offsetConfig) == "number" then
    return safeRead(offsetConfig, size)
  end

  -- Dynamic mode: offset is {pointer = "name", offsets = {chain}}
  if type(offsetConfig) == "table" and offsetConfig.pointer then
    if not config.pointers or not config.pointers[offsetConfig.pointer] then
      return nil
    end

    local basePtr = config.pointers[offsetConfig.pointer]
    local finalAddr = HAL.readSafePointer(basePtr, offsetConfig.offsets)

    if not finalAddr then
      return nil
    end

    return safeRead(finalAddr, size)
  end

  return nil
end

function HAL.readPlayerX()
  if not config or not config.offsets.playerX then
    return nil
  end
  return readOffset(config.offsets.playerX, 2)
end

function HAL.readPlayerY()
  if not config or not config.offsets.playerY then
    return nil
  end
  return readOffset(config.offsets.playerY, 2)
end

function HAL.readMapId()
  if not config or not config.offsets.mapId then
    return nil
  end
  return readOffset(config.offsets.mapId, 1)
end

function HAL.readMapGroup()
  if not config or not config.offsets.mapGroup then
    return nil
  end
  return readOffset(config.offsets.mapGroup, 1)
end

function HAL.readFacing()
  if not config or not config.offsets.facing then
    return nil
  end
  return readOffset(config.offsets.facing, 1)
end

--[[
  Read KEYINPUT register (0x04000130) for direction buttons.
  Active-low: bit=0 means pressed. Direction bits 4-7.
  Priority: Down > Up > Left > Right (matches Pokemon engine).
  @return "down"/"up"/"left"/"right" or nil if no direction pressed
]]
function HAL.readKeyInput()
  local raw = HAL.readIOReg16(0x0130)
  if not raw then return nil end
  local pressed = (~raw) & 0x00F0  -- invert active-low, mask bits 4-7
  if (pressed & 0x0080) ~= 0 then return "down" end
  if (pressed & 0x0040) ~= 0 then return "up" end
  if (pressed & 0x0020) ~= 0 then return "left" end
  if (pressed & 0x0010) ~= 0 then return "right" end
  return nil
end

--[[
  Read A and B button state from KEYINPUT register (0x04000130).
  Active-low: bit=0 means pressed. A=bit0, B=bit1.
  @return keyA (boolean), keyB (boolean)
]]
function HAL.readButtons()
  local raw = HAL.readIOReg16(0x0130)
  if not raw then return false, false end
  local pressed = (~raw) & 0x0003  -- invert active-low, mask bits 0-1
  local keyA = (pressed & 0x0001) ~= 0
  local keyB = (pressed & 0x0002) ~= 0
  return keyA, keyB
end

--[[
  Convert unsigned 16-bit to signed 16-bit
  Camera offsets (gSpriteCoordOffsetX/Y) are s16 but read16 returns u16
]]
local function toSigned16(value)
  if value and value >= 0x8000 then
    return value - 0x10000
  end
  return value
end

function HAL.readCameraX()
  if not config or not config.offsets.cameraX then
    return nil
  end
  local addr = config.offsets.cameraX
  local raw
  if addr >= 0x03000000 and addr < 0x03008000 then
    raw = safeReadIWRAM(addr, 2)
  else
    raw = safeRead(addr, 2)
  end
  return toSigned16(raw)
end

function HAL.readCameraY()
  if not config or not config.offsets.cameraY then
    return nil
  end
  local addr = config.offsets.cameraY
  local raw
  if addr >= 0x03000000 and addr < 0x03008000 then
    raw = safeReadIWRAM(addr, 2)
  else
    raw = safeRead(addr, 2)
  end
  return toSigned16(raw)
end

--[[
  Write player position (for warp functionality)
  @param x New X coordinate
  @param y New Y coordinate
  @param mapId New map ID
  @param mapGroup New map group
  @return boolean Success status
]]
function HAL.writePlayerPosition(x, y, mapId, mapGroup)
  if not config then
    return false
  end

  local success = true

  if config.offsets.playerX then
    success = success and HAL.safeWrite(config.offsets.playerX, x, 2)
  end

  if config.offsets.playerY then
    success = success and HAL.safeWrite(config.offsets.playerY, y, 2)
  end

  if config.offsets.mapId then
    success = success and HAL.safeWrite(config.offsets.mapId, mapId, 1)
  end

  if config.offsets.mapGroup then
    success = success and HAL.safeWrite(config.offsets.mapGroup, mapGroup, 1)
  end

  return success
end

-- ============================================================
-- WARP SYSTEM v2: EWRAM Code Injection Trampoline
-- ============================================================
-- Instead of finding SetCB2WarpAndLoadMap in ROM (which failed — 280 refs,
-- none matched criteria), we write our own equivalent as THUMB code in EWRAM.
-- GBA has no MMU — EWRAM is fully executable.
--
-- The trampoline calls WarpIntoMap() then CB2_LoadMap(), replicating what
-- SetCB2WarpAndLoadMap does in the original code.
--
-- Finding WarpIntoMap: use sWarpDestination (0x020318A8) as anchor.
-- Functions referencing this EWRAM address include ApplyCurrentWarp.
-- WarpIntoMap calls ApplyCurrentWarp as its first BL (3 BL calls total).

-- Cache for sWarpData EWRAM offset (found via runtime scan)
local sWarpDataOffset = nil

-- Callback2 transition tracking (for sWarpData auto-calibration)
local prevTrackedCb2 = nil

-- Warp function addresses
local warpIntoMapAddr = nil   -- ROM address of WarpIntoMap (THUMB)
local warpFuncAddr = nil      -- Legacy: SetCB2WarpAndLoadMap (config override only)
local trampolineAddr = nil    -- EWRAM trampoline address (with THUMB bit)
local romScanned = false

-- EWRAM location for trampoline (high address, unlikely game data collision)
local TRAMPOLINE_EWRAM = 0x0203FF00

--[[
  Scan EWRAM to find sWarpData address.
  sWarpData is the game's internal warp destination struct. CB2_LoadMap reads
  from sWarpData (not SaveBlock1) to know where to load.

  Uses two strategies:
  1. Cluster scan: find two consecutive sDummyWarpData patterns (sFixedDiveWarp + sFixedHoleWarp),
     which are ALWAYS reset to {FF,FF,FF,00,FFFF,FFFF} by ApplyCurrentWarp after every warp.
     sWarpDestination = found_address - 8 (they are adjacent in overworld.c).
  2. Pattern match: fall back to matching SaveBlock1->location content in EWRAM.

  Call this after HAL.init() and after each natural map change.
  @return boolean True if sWarpData was found (or was already cached)
]]
function HAL.findSWarpData()
  if not config or not config.warp then return false end
  if sWarpDataOffset then return true end -- Already cached

  -- Use config-provided address if available (from scanner results)
  if config.warp.sWarpDataAddr then
    sWarpDataOffset = toWRAMOffset(config.warp.sWarpDataAddr)
    console:log(string.format("[HAL] sWarpData set from config: 0x%08X", config.warp.sWarpDataAddr))
    return true
  end

  -- === Strategy 1: Cluster scan for sDummyWarpData pair ===
  -- In overworld.c, the declarations are adjacent:
  --   sWarpDestination  (WarpData, 8 bytes)
  --   sFixedDiveWarp    (WarpData, 8 bytes)
  --   sFixedHoleWarp    (WarpData, 8 bytes)
  -- ApplyCurrentWarp() resets sFixedDiveWarp and sFixedHoleWarp to sDummyWarpData
  -- after EVERY warp (including initial game load).
  -- sDummyWarpData = { mapGroup=0xFF, mapNum=0xFF, warpId=0xFF, pad=0, x=-1, y=-1 }
  --                = bytes: FF FF FF 00 FF FF FF FF
  --                = u32 pair: 0x00FFFFFF, 0xFFFFFFFF
  local DUMMY_LO = 0x00FFFFFF  -- FF FF FF 00 (mapGroup, mapNum, warpId, pad)
  local DUMMY_HI = 0xFFFFFFFF  -- FFFF FFFF (x=-1, y=-1)

  console:log("[HAL] findSWarpData: cluster scan for sDummyWarpData pair (full EWRAM)...")

  for offset = 8, 0x3FFF0, 4 do  -- start at 8 so sWarpDestination (offset-8) >= 0
    local ok1, v1 = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok1 and v1 == DUMMY_LO then
      local ok2, v2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
      if ok2 and v2 == DUMMY_HI then
        -- Found one sDummyWarpData at 'offset'. Check if next 8 bytes also match.
        local ok3, v3 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 8)
        local ok4, v4 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 12)
        if ok3 and ok4 and v3 == DUMMY_LO and v4 == DUMMY_HI then
          -- Two consecutive sDummyWarpData found!
          -- sFixedDiveWarp = offset, sFixedHoleWarp = offset + 8
          -- sWarpDestination = offset - 8
          local candidateOffset = offset - 8
          -- Sanity check: verify sWarpDestination looks like a WarpData
          -- (mapGroup and mapId should be within valid ranges, or zeroed)
          local okA, warpLo = pcall(emu.memory.wram.read32, emu.memory.wram, candidateOffset)
          if okA then
            local mg = warpLo & 0xFF
            local mi = (warpLo >> 8) & 0xFF
            -- Accept if mapGroup/mapId are valid OR zeroed (game hasn't set it yet)
            if mg <= 50 or mg == 0xFF or warpLo == 0 then
              sWarpDataOffset = candidateOffset
              console:log(string.format("[HAL] sWarpData FOUND via cluster scan at 0x%08X (mapGroup=%d mapId=%d)",
                0x02000000 + candidateOffset, mg, mi))
              return true
            end
          end
        end
      end
    end
  end

  console:log("[HAL] findSWarpData: cluster scan found no sDummyWarpData pair")

  -- === Strategy 2: Pattern match against SaveBlock1->location ===
  -- After a warp, sWarpDestination content == SaveBlock1->location content.
  -- Scan all EWRAM (excluding SaveBlock1 itself) for the same 8-byte pattern.
  local locOffset = toWRAMOffset(config.offsets.mapGroup)
  local ok1, ref32a = pcall(emu.memory.wram.read32, emu.memory.wram, locOffset)
  local ok2, ref32b = pcall(emu.memory.wram.read32, emu.memory.wram, locOffset + 4)
  if not ok1 or not ok2 then return false end

  if ref32a == 0 and ref32b == 0 then
    console:log("[HAL] findSWarpData: SaveBlock1->location is zeroed, skipping pattern scan")
    return false
  end

  local mg = ref32a & 0xFF
  local mi = (ref32a >> 8) & 0xFF
  console:log(string.format("[HAL] findSWarpData: pattern scan mapGroup=%d mapId=%d (ref32a=0x%08X ref32b=0x%08X)",
    mg, mi, ref32a, ref32b))

  -- Scan all EWRAM, skip the SaveBlock1->location itself (at locOffset)
  for offset = 0, 0x3FFF8, 4 do
    if offset ~= locOffset then
      local s1, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
      if s1 and val == ref32a then
        local s2, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
        if s2 and val2 == ref32b then
          -- Verify neighbor: check if +8 or +16 has sDummyWarpData pattern
          local okN, nv = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 8)
          if okN and nv == DUMMY_LO then
            sWarpDataOffset = offset
            console:log(string.format("[HAL] sWarpData FOUND via pattern+neighbor at 0x%08X",
              0x02000000 + offset))
            return true
          end
          -- Accept even without neighbor verification if in low EWRAM (< SaveBlock1)
          if offset < locOffset then
            sWarpDataOffset = offset
            console:log(string.format("[HAL] sWarpData FOUND via pattern match at 0x%08X (low EWRAM)",
              0x02000000 + offset))
            return true
          end
        end
      end
    end
  end

  console:log("[HAL] findSWarpData: no match found in full EWRAM scan")
  return false
end

-- Helper: read u16 little-endian from binary string at 1-indexed position
local function strU16(s, pos)
  local b0, b1 = string.byte(s, pos, pos + 1)
  if not b0 or not b1 then return nil end
  return b0 + b1 * 256
end

-- Helper: decode THUMB BL target from two halfwords + PC address
local function decodeBL(instrH, instrL, pc)
  local off11hi = instrH & 0x07FF
  local off11lo = instrL & 0x07FF
  local fullOff = (off11hi << 12) | (off11lo << 1)
  if fullOff >= 0x400000 then fullOff = fullOff - 0x800000 end
  return pc + fullOff
end

--[[
  Multi-phase ROM scanner to find WarpIntoMap's address.

  Phase 1: Search ROM for sWarpDestination (0x020318A8) in literal pools
           — much more targeted than CB2_LoadMap (3-10 refs vs 280)
  Phase 2: Identify functions referencing sWarpDestination
           — these are ApplyCurrentWarp, SetWarpDestination, etc.
  Phase 3: Search nearby ROM for WarpIntoMap
           — exactly 3 BL calls, one targeting a Phase 2 function
  Fallback: Extract BL targets near CB2_LoadMap literal pool entries
           — the BL right before LDR =CB2_LoadMap often targets WarpIntoMap

  @return boolean True if WarpIntoMap was found (or manual override exists)
]]
function HAL.scanROMForWarpFunction()
  if romScanned then return warpIntoMapAddr ~= nil or warpFuncAddr ~= nil end
  romScanned = true

  if not config or not config.warp then return false end

  -- Check manual overrides
  if config.warp.warpIntoMapAddr then
    warpIntoMapAddr = config.warp.warpIntoMapAddr
    console:log(string.format("[HAL] WarpIntoMap from config: 0x%08X", warpIntoMapAddr))
    return true
  end
  if config.warp.setCB2WarpAddr then
    warpFuncAddr = config.warp.setCB2WarpAddr
    console:log(string.format("[HAL] SetCB2WarpAndLoadMap from config: 0x%08X", warpFuncAddr))
    return true
  end

  console:log("[HAL] Scanning ROM for WarpIntoMap (EWRAM trampoline approach)...")

  -- ===== PHASE 1: Find sWarpDestination in ROM literal pools =====
  local SWARP = 0x020318A8
  local SW_B0, SW_B1, SW_B2, SW_B3 = 0xA8, 0x18, 0x03, 0x02
  local SCAN_SIZE = 0x800000  -- 8MB
  local CHUNK = 4096
  local swarpRefs = {}

  for base = 0, SCAN_SIZE - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do
        local b0, b1, b2, b3 = string.byte(data, i, i + 3)
        if b0 == SW_B0 and b1 == SW_B1 and b2 == SW_B2 and b3 == SW_B3 then
          table.insert(swarpRefs, base + i - 1)
        end
      end
    end
  end

  console:log(string.format("[HAL] Phase 1: %d ROM refs to sWarpDestination (0x%08X)", #swarpRefs, SWARP))

  if #swarpRefs == 0 then
    console:log("[HAL] No sWarpDestination refs — trying CB2_LoadMap fallback...")
    return HAL.findWarpViaCallback()
  end

  -- ===== PHASE 2: Find containing functions =====
  local swarpFuncs = {}

  for _, litOff in ipairs(swarpRefs) do
    local searchStart = math.max(0, litOff - 256)
    local readLen = litOff - searchStart
    if readLen >= 2 then
      local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, searchStart, readLen)
      if ok and data then
        for back = 2, readLen, 2 do
          local pos = readLen - back + 1
          if pos >= 1 and pos + 1 <= #data then
            local instr = strU16(data, pos)
            if instr and ((instr & 0xFF00) == 0xB400 or (instr & 0xFF00) == 0xB500) then
              local funcRomOff = searchStart + pos - 1
              local funcAddr = 0x08000000 + funcRomOff + 1
              local dup = false
              for _, f in ipairs(swarpFuncs) do
                if f.addr == funcAddr then dup = true; break end
              end
              if not dup then
                table.insert(swarpFuncs, { addr = funcAddr, romOff = funcRomOff })
              end
              break
            end
          end
        end
      end
    end
  end

  console:log(string.format("[HAL] Phase 2: %d functions reference sWarpDestination", #swarpFuncs))
  for _, f in ipairs(swarpFuncs) do
    console:log(string.format("[HAL]   0x%08X", f.addr))
  end

  if #swarpFuncs == 0 then
    return HAL.findWarpViaCallback()
  end

  -- ===== PHASE 3: Search nearby ROM for WarpIntoMap =====
  -- WarpIntoMap: exactly 3 BL calls, one targets a swarpFunc, 12-60 bytes
  local targets = {}
  for _, f in ipairs(swarpFuncs) do
    targets[f.addr & 0xFFFFFFFE] = true
    targets[f.addr] = true
  end

  local WINDOW = 0x8000  -- ±32KB
  local candidates = {}
  local scannedRanges = {}

  for _, sf in ipairs(swarpFuncs) do
    local rangeStart = math.max(0, sf.romOff - WINDOW)
    local rangeEnd = math.min(SCAN_SIZE, sf.romOff + WINDOW)
    local rangeKey = math.floor(rangeStart / WINDOW)

    if not scannedRanges[rangeKey] then
      scannedRanges[rangeKey] = true
      local readLen = rangeEnd - rangeStart
      local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, rangeStart, readLen)
      if ok and data then
        local i = 1
        while i <= #data - 3 do
          local instr = strU16(data, i)
          if instr and ((instr & 0xFF00) == 0xB400 or (instr & 0xFF00) == 0xB500) then
            local funcStart = i
            -- Find function end (POP {PC} or BX LR, max 128 bytes)
            local funcEnd = nil
            local j = funcStart + 2
            while j <= math.min(funcStart + 128, #data - 1) do
              local instr2 = strU16(data, j)
              if instr2 then
                if (instr2 & 0xFF00) == 0xBD00 or instr2 == 0x4770 then
                  funcEnd = j + 2
                  break
                end
              end
              j = j + 2
            end

            if funcEnd then
              local funcSize = funcEnd - funcStart
              if funcSize >= 12 and funcSize <= 60 then
                local blCount = 0
                local blTargets = {}
                local callsSwarp = false
                local k = funcStart
                while k <= funcEnd - 4 do
                  local h = strU16(data, k)
                  local l = strU16(data, k + 2)
                  if h and l and (h & 0xF800) == 0xF000 and (l & 0xF800) == 0xF800 then
                    blCount = blCount + 1
                    local blPC = 0x08000000 + (rangeStart + k - 1) + 4
                    local target = decodeBL(h, l, blPC)
                    table.insert(blTargets, target)
                    if targets[target] or targets[target & 0xFFFFFFFE] then
                      callsSwarp = true
                    end
                    k = k + 4
                  else
                    k = k + 2
                  end
                end

                if blCount == 3 and callsSwarp then
                  local funcAddr = 0x08000000 + (rangeStart + funcStart - 1) + 1
                  local dup = false
                  for _, c in ipairs(candidates) do
                    if c.addr == funcAddr then dup = true; break end
                  end
                  if not dup then
                    table.insert(candidates, { addr = funcAddr, size = funcSize, blTargets = blTargets })
                  end
                end
              end
            end
          end
          i = i + 2
        end
      end
    end
  end

  console:log(string.format("[HAL] Phase 3: %d WarpIntoMap candidates", #candidates))

  if #candidates > 0 then
    table.sort(candidates, function(a, b) return a.size < b.size end)
    warpIntoMapAddr = candidates[1].addr
    console:log(string.format("[HAL] WarpIntoMap FOUND at 0x%08X (%d bytes)", warpIntoMapAddr, candidates[1].size))
    for j, t in ipairs(candidates[1].blTargets) do
      console:log(string.format("[HAL]   BL%d -> 0x%08X", j, t))
    end
    return true
  end

  console:log("[HAL] Phase 3 found no WarpIntoMap — trying CB2_LoadMap fallback...")
  return HAL.findWarpViaCallback()
end

--[[
  Fallback: Find WarpIntoMap by analyzing BL targets near CB2_LoadMap literal pool refs.
  In Task_WarpAndLoadMap state 2: BL WarpIntoMap, LDR R0 =CB2_LoadMap, BL SetMainCallback2.
  The BL right before the LDR that loads CB2_LoadMap targets WarpIntoMap.
  @return boolean
]]
function HAL.findWarpViaCallback()
  local CB2_LM = config.warp.cb2LoadMap
  if not CB2_LM then return false end

  local CB2_B0, CB2_B1 = CB2_LM & 0xFF, (CB2_LM >> 8) & 0xFF
  local CB2_B2, CB2_B3 = (CB2_LM >> 16) & 0xFF, (CB2_LM >> 24) & 0xFF
  local SCAN_SIZE = 0x800000
  local CHUNK = 4096

  -- Find CB2_LoadMap literal pool entries
  local cb2Refs = {}
  for base = 0, SCAN_SIZE - CHUNK, CHUNK do
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, base, CHUNK)
    if ok and data then
      for i = 1, #data - 3, 4 do
        local b0, b1, b2, b3 = string.byte(data, i, i + 3)
        if b0 == CB2_B0 and b1 == CB2_B1 and b2 == CB2_B2 and b3 == CB2_B3 then
          table.insert(cb2Refs, base + i - 1)
        end
      end
    end
  end

  console:log(string.format("[HAL] Fallback: %d CB2_LoadMap refs in ROM", #cb2Refs))

  -- For each literal, find the LDR that loads it, then extract BL target before it
  local blTargetCounts = {}

  for _, litOff in ipairs(cb2Refs) do
    local readStart = math.max(0, litOff - 256)
    local readLen = litOff - readStart + 4
    local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, readStart, readLen)
    if ok and data then
      for pos = 1, #data - 1, 2 do
        local instr = strU16(data, pos)
        if instr and (instr & 0xF800) == 0x4800 then
          -- LDR Rd, [PC, #imm8*4]
          local instrRomOff = readStart + pos - 1
          local imm8 = instr & 0xFF
          local effPC = (instrRomOff + 4) & 0xFFFFFFFC
          local loadAddr = effPC + imm8 * 4
          if loadAddr == litOff then
            -- Found LDR that loads CB2_LoadMap. Check BL before it.
            if pos >= 5 then
              local blH = strU16(data, pos - 4)
              local blL = strU16(data, pos - 2)
              if blH and blL and (blH & 0xF800) == 0xF000 and (blL & 0xF800) == 0xF800 then
                local blPC = 0x08000000 + (readStart + pos - 5) + 4
                local target = decodeBL(blH, blL, blPC)
                blTargetCounts[target] = (blTargetCounts[target] or 0) + 1
              end
            end
          end
        end
      end
    end
  end

  -- Sort by frequency — most common BL target before LDR =CB2_LoadMap
  local sorted = {}
  for addr, count in pairs(blTargetCounts) do
    table.insert(sorted, { addr = addr, count = count })
  end
  table.sort(sorted, function(a, b) return a.count > b.count end)

  console:log(string.format("[HAL] Fallback: %d unique BL targets before LDR =CB2_LoadMap", #sorted))
  for i = 1, math.min(5, #sorted) do
    console:log(string.format("[HAL]   0x%08X (x%d)", sorted[i].addr, sorted[i].count))
  end

  -- Verify candidates: should be small function with 3 BL calls
  for _, st in ipairs(sorted) do
    local funcRomOff = (st.addr & 0xFFFFFFFE) - 0x08000000
    if funcRomOff >= 0 and funcRomOff < SCAN_SIZE then
      local readLen = math.min(128, SCAN_SIZE - funcRomOff)
      local ok, data = pcall(emu.memory.cart0.readRange, emu.memory.cart0, funcRomOff, readLen)
      if ok and data and #data >= 2 then
        local firstInstr = strU16(data, 1)
        if firstInstr and ((firstInstr & 0xFF00) == 0xB400 or (firstInstr & 0xFF00) == 0xB500) then
          local funcEnd = nil
          local blCount = 0
          local pos = 1
          while pos <= #data - 1 do
            local instr = strU16(data, pos)
            if instr and pos > 2 and ((instr & 0xFF00) == 0xBD00 or instr == 0x4770) then
              funcEnd = pos + 2
              break
            end
            if pos <= #data - 3 then
              local next = strU16(data, pos + 2)
              if instr and next and (instr & 0xF800) == 0xF000 and (next & 0xF800) == 0xF800 then
                blCount = blCount + 1
                pos = pos + 4
              else
                pos = pos + 2
              end
            else
              pos = pos + 2
            end
          end

          if funcEnd then
            local funcSize = funcEnd - 1
            if blCount == 3 and funcSize >= 12 and funcSize <= 60 then
              warpIntoMapAddr = st.addr | 1
              console:log(string.format("[HAL] WarpIntoMap FOUND via fallback at 0x%08X (%d bytes, 3 BL, x%d refs)",
                warpIntoMapAddr, funcSize, st.count))
              return true
            end
          end
        end
      end
    end
  end

  console:log("[HAL] WARNING: WarpIntoMap not found — forced warp will use direct CB2_LoadMap (may hang)")
  console:log("[HAL] Set config.warp.warpIntoMapAddr = <address> in run_and_bun.lua for manual override")
  return false
end

--[[
  Inject EWRAM trampoline: THUMB code that calls WarpIntoMap then CB2_LoadMap.
  GBA has no MMU — EWRAM is executable.

  THUMB layout (24 bytes at TRAMPOLINE_EWRAM):
    +0x00: B510  PUSH {R4, LR}
    +0x02: 4C03  LDR R4, [PC, #12]  ; load WarpIntoMap from +0x10
    +0x04: 46FE  MOV LR, PC         ; set return addr = +0x08
    +0x06: 4720  BX R4              ; call WarpIntoMap()
    +0x08: 4C02  LDR R4, [PC, #8]   ; load CB2_LoadMap from +0x14
    +0x0A: 46FE  MOV LR, PC         ; set return addr = +0x0E
    +0x0C: 4720  BX R4              ; call CB2_LoadMap()
    +0x0E: BD10  POP {R4, PC}       ; return to main loop
    +0x10: .word WarpIntoMap        ; literal pool
    +0x14: .word CB2_LoadMap        ; literal pool

  @return number|nil  Trampoline address with THUMB bit, or nil
]]
function HAL.injectTrampoline()
  if trampolineAddr then return trampolineAddr end
  if not warpIntoMapAddr then return nil end

  local off = toWRAMOffset(TRAMPOLINE_EWRAM)

  -- Verify EWRAM area is available
  local ok, existing = pcall(emu.memory.wram.read32, emu.memory.wram, off)
  if ok and existing ~= 0 then
    console:log(string.format("[HAL] WARNING: EWRAM at 0x%08X not zero (0x%08X) — overwriting",
      TRAMPOLINE_EWRAM, existing))
  end

  -- Write THUMB instructions
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x00, 0xB510) -- PUSH {R4, LR}
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x02, 0x4C03) -- LDR R4, [PC, #12]
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x04, 0x46FE) -- MOV LR, PC
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x06, 0x4720) -- BX R4
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x08, 0x4C02) -- LDR R4, [PC, #8]
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x0A, 0x46FE) -- MOV LR, PC
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x0C, 0x4720) -- BX R4
  pcall(emu.memory.wram.write16, emu.memory.wram, off + 0x0E, 0xBD10) -- POP {R4, PC}

  -- Write literal pool
  pcall(emu.memory.wram.write32, emu.memory.wram, off + 0x10, warpIntoMapAddr)
  pcall(emu.memory.wram.write32, emu.memory.wram, off + 0x14, config.warp.cb2LoadMap)

  trampolineAddr = TRAMPOLINE_EWRAM + 1  -- +1 for THUMB bit
  console:log(string.format("[HAL] Trampoline injected at 0x%08X (WarpIntoMap=0x%08X CB2_LoadMap=0x%08X)",
    TRAMPOLINE_EWRAM, warpIntoMapAddr, config.warp.cb2LoadMap))

  return trampolineAddr
end

--[[
  Phase 1: Write warp destination to sWarpData + SaveBlock1.
  Does NOT trigger the map load yet — call triggerMapLoad() after a few frames.

  @param mapGroup Destination map group
  @param mapId Destination map ID
  @param x Destination X tile coordinate
  @param y Destination Y tile coordinate
  @return boolean Success status
]]
function HAL.writeWarpData(mapGroup, mapId, x, y)
  if not config or not config.warp then
    console:log("[HAL] writeWarpData: no warp config available")
    return false
  end

  -- Write to sWarpData (CB2_LoadMap reads destination from here)
  if sWarpDataOffset then
    pcall(emu.memory.wram.write8, emu.memory.wram, sWarpDataOffset, mapGroup)
    pcall(emu.memory.wram.write8, emu.memory.wram, sWarpDataOffset + 1, mapId)
    pcall(emu.memory.wram.write8, emu.memory.wram, sWarpDataOffset + 2, 0xFF) -- warpId = -1 (use x,y)
    pcall(emu.memory.wram.write8, emu.memory.wram, sWarpDataOffset + 3, 0)    -- padding
    pcall(emu.memory.wram.write16, emu.memory.wram, sWarpDataOffset + 4, x)
    pcall(emu.memory.wram.write16, emu.memory.wram, sWarpDataOffset + 6, y)
  else
    console:log("[HAL] WARNING: sWarpData not found — warp may load wrong map")
  end

  -- Also write to SaveBlock1->location + pos
  local locOff = toWRAMOffset(config.offsets.mapGroup)
  pcall(emu.memory.wram.write8, emu.memory.wram, locOff, mapGroup)
  pcall(emu.memory.wram.write8, emu.memory.wram, locOff + 1, mapId)
  pcall(emu.memory.wram.write8, emu.memory.wram, locOff + 2, 0xFF)
  pcall(emu.memory.wram.write8, emu.memory.wram, locOff + 3, 0)
  pcall(emu.memory.wram.write16, emu.memory.wram, locOff + 4, x)
  pcall(emu.memory.wram.write16, emu.memory.wram, locOff + 6, y)

  pcall(emu.memory.wram.write16, emu.memory.wram, toWRAMOffset(config.offsets.playerX), x)
  pcall(emu.memory.wram.write16, emu.memory.wram, toWRAMOffset(config.offsets.playerY), y)

  console:log(string.format("[HAL] writeWarpData: %d:%d (%d,%d) sWarpData=%s",
    mapGroup, mapId, x, y, sWarpDataOffset and "OK" or "MISSING"))

  return true
end

--[[
  Phase 2: Trigger the map load.

  Priority 1: EWRAM trampoline (calls WarpIntoMap + CB2_LoadMap via injected THUMB code)
  Priority 2: Legacy SetCB2WarpAndLoadMap (from config override only)
  Priority 3: Direct CB2_LoadMap (will hang — WarpIntoMap not called)

  @return boolean Success status
]]
function HAL.triggerMapLoad()
  if not config or not config.warp then return false end

  local gMainBase = config.warp.callback2Addr - 4
  local base = toWRAMOffset(gMainBase)
  local stateOffset = (config.warp.gMainStateOffset) or 0x65

  -- Ensure ROM scan is done
  if not romScanned then
    HAL.scanROMForWarpFunction()
  end

  -- Priority 1: EWRAM trampoline (calls WarpIntoMap + CB2_LoadMap)
  if warpIntoMapAddr then
    local tAddr = HAL.injectTrampoline()
    if tAddr then
      pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x00, 0)           -- NULL callback1
      pcall(emu.memory.wram.write8, emu.memory.wram, base + stateOffset, 0)     -- zero state
      pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x04, tAddr)       -- callback2 = trampoline
      console:log(string.format("[HAL] triggerMapLoad via EWRAM trampoline (0x%08X)", tAddr))
      return true
    end
  end

  -- Priority 2: Legacy SetCB2WarpAndLoadMap (config override)
  if warpFuncAddr then
    pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x00, 0)
    pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x04, warpFuncAddr)
    console:log(string.format("[HAL] triggerMapLoad via SetCB2WarpAndLoadMap (0x%08X)", warpFuncAddr))
    return true
  end

  -- Priority 3: Direct CB2_LoadMap (may hang — WarpIntoMap not called)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x00, 0)
  pcall(emu.memory.wram.write8, emu.memory.wram, base + stateOffset, 0)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x04, config.warp.cb2LoadMap)
  console:log(string.format("[HAL] triggerMapLoad via direct CB2_LoadMap FALLBACK (0x%08X) — may hang!",
    config.warp.cb2LoadMap))
  return true
end

--[[
  Read gMain.inBattle flag.
  @return u8 inBattle value (0 = overworld, 1 = in battle), or nil
]]
function HAL.readInBattle()
  if not config or not config.battle or not config.battle.gMainInBattle then
    return nil
  end
  local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram,
    toWRAMOffset(config.battle.gMainInBattle))
  if ok then return val end
  return nil
end

--[[
  Read gMain.callback2 value (for warp diagnostics).
  @return u32 callback2 value, or nil
]]
function HAL.readCallback2()
  if not config or not config.warp then return nil end
  local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram,
    toWRAMOffset(config.warp.callback2Addr))
  if ok then return val end
  return nil
end

--[[
  Check if warp is complete (callback2 returned to CB2_Overworld).
  @return boolean True if callback2 == CB2_Overworld
]]
function HAL.isWarpComplete()
  if not config or not config.warp or not config.warp.cb2Overworld then return false end
  local cb2 = HAL.readCallback2()
  return cb2 == config.warp.cb2Overworld
end

--[[
  Track callback2 every frame for sWarpData auto-calibration.
  Detects transitions (CB2_LoadMap -> CB2_Overworld) and auto-calibrates
  sWarpData by scanning EWRAM for pattern match after map load completes.

  @return string|nil  "loading", "overworld", "other", or nil
]]
function HAL.trackCallback2()
  if not config or not config.warp then return nil end

  local cb2 = HAL.readCallback2()
  if not cb2 then return nil end

  local state = nil
  if cb2 == config.warp.cb2LoadMap then
    state = "loading"
  elseif cb2 == config.warp.cb2Overworld then
    state = "overworld"
  else
    state = "other"
  end

  -- First call: try immediate calibration based on current state
  if prevTrackedCb2 == nil then
    if state ~= "loading" and not sWarpDataOffset then
      -- Game is past initial load — try to find sWarpData now
      local found = HAL.findSWarpData()
      if found then
        console:log("[HAL] sWarpData auto-calibrated on first frame!")
      end
    end
    prevTrackedCb2 = cb2
    return state
  end

  -- Detect CB2_LoadMap -> non-CB2_LoadMap (map load completed)
  if prevTrackedCb2 == config.warp.cb2LoadMap and cb2 ~= config.warp.cb2LoadMap then
    if not sWarpDataOffset then
      console:log("[HAL] Map load completed — auto-calibrating sWarpData...")
      local found = HAL.findSWarpData()
      if found then
        console:log("[HAL] sWarpData auto-calibrated!")
      end
    end
  end

  prevTrackedCb2 = cb2
  return state
end

--[[
  Check if sWarpData has been calibrated.
  @return boolean
]]
function HAL.hasSWarpData()
  return sWarpDataOffset ~= nil
end

--[[
  Blank the GBA screen by filling all palette RAM with black (0x0000).
  Used before triggering CB2_LoadMap to mimic the game's normal fade-to-black.
]]
function HAL.blankScreen()
  -- Fill BG palettes (0x000-0x1FF) and OBJ palettes (0x200-0x3FF) with black
  for i = 0, 511 do
    pcall(emu.memory.palette.write16, emu.memory.palette, i * 2, 0x0000)
  end
end

--[[
  Perform a complete direct warp: find sWarpData, blank screen, write destination,
  and trigger CB2_LoadMap. This is the primary warp method — no golden state needed.

  The game engine handles CB2_Overworld -> CB2_LoadMap transitions natively.
  triggerMapLoad() replicates the game's internal warp preparation (NULL callbacks,
  zero state, set CB2_LoadMap).

  @param mapGroup Destination map group
  @param mapId Destination map ID
  @param x Destination X tile coordinate
  @param y Destination Y tile coordinate
  @return boolean success, string|nil error message
]]
function HAL.performDirectWarp(mapGroup, mapId, x, y)
  if not config or not config.warp then
    return false, "no warp config"
  end

  -- Ensure sWarpData is available
  if not sWarpDataOffset then
    HAL.findSWarpData()
    if not sWarpDataOffset then
      return false, "sWarpData not found"
    end
  end

  -- Ensure ROM scan is done (needed for EWRAM trampoline)
  if not romScanned then
    HAL.scanROMForWarpFunction()
  end

  -- 1. Blank screen (fade to black before map load)
  HAL.blankScreen()

  -- 2. Write destination to sWarpDestination + SaveBlock1
  HAL.writeWarpData(mapGroup, mapId, x, y)

  -- 3. Trigger map load (EWRAM trampoline > SetCB2WarpAndLoadMap > CB2_LoadMap fallback)
  HAL.triggerMapLoad()

  local method = "CB2_LoadMap (fallback)"
  if warpIntoMapAddr and trampolineAddr then
    method = "EWRAM trampoline"
  elseif warpFuncAddr then
    method = "SetCB2WarpAndLoadMap"
  end
  console:log(string.format("[HAL] Direct warp initiated: %d:%d (%d,%d) via %s",
    mapGroup, mapId, x, y, method))
  return true
end

--[[
  Debug function to verify WRAM access
]]
function HAL.testMemoryAccess()
  console:log("[HAL] Testing memory access...")

  -- Test valid WRAM read
  local testValue = safeRead(0x02000000, 1)
  if testValue ~= nil then
    console:log("[HAL] WRAM access: OK")
  else
    console:log("[HAL] WRAM access: FAILED")
  end

  -- Test invalid address handling
  local invalidValue = safeRead(0x00000000, 1)
  if invalidValue == nil then
    console:log("[HAL] Invalid address protection: OK")
  else
    console:log("[HAL] Invalid address protection: FAILED")
  end

  -- Test configuration
  if config then
    console:log("[HAL] Config loaded: " .. config.name)
    console:log("[HAL] PlayerX offset: " .. string.format("0x%08X", config.offsets.playerX))
  else
    console:log("[HAL] No config loaded")
  end
end

--[[
  Read a single OAM entry (3x u16: attr0, attr1, attr2)
  @param index OAM index (0-127)
  @return attr0, attr1, attr2 or nil on error
]]
function HAL.readOAMEntry(index)
  if not index or index < 0 or index > 127 then
    return nil, nil, nil
  end

  local success, attr0, attr1, attr2 = pcall(function()
    local base = index * 8
    local a0 = emu.memory.oam:read16(base)
    local a1 = emu.memory.oam:read16(base + 2)
    local a2 = emu.memory.oam:read16(base + 4)
    return a0, a1, a2
  end)

  if success then
    return attr0, attr1, attr2
  end
  return nil, nil, nil
end

--[[
  Read sprite tiles from VRAM (4bpp, 32 bytes per tile)
  Sprites are stored in VRAM at offset 0x10000 (obj tile base)
  @param tileIndex Starting tile index from OAM attr2
  @param numTiles Number of tiles to read
  @return string of raw tile bytes, or nil on error
]]
function HAL.readSpriteTiles(tileIndex, numTiles)
  if not tileIndex or not numTiles or numTiles <= 0 then
    return nil
  end

  local offset = 0x10000 + tileIndex * 32
  local length = numTiles * 32

  -- Validate range stays within sprite VRAM (0x10000-0x17FFF)
  if offset < 0x10000 or (offset + length) > 0x18000 then
    return nil
  end

  local success, data = pcall(function()
    return emu.memory.vram:readRange(offset, length)
  end)

  if success and data then
    return data
  end
  return nil
end

--[[
  Read a sprite palette bank (16 colors, BGR555 format)
  Sprite palettes start at palette RAM offset 0x200
  @param bank Palette bank index (0-15)
  @return table of 16 BGR555 values (indexed 0-15), or nil on error
]]
function HAL.readSpritePalette(bank)
  if not bank or bank < 0 or bank > 15 then
    return nil
  end

  local success, palette = pcall(function()
    local pal = {}
    local base = 0x200 + bank * 32
    for i = 0, 15 do
      pal[i] = emu.memory.palette:read16(base + i * 2)
    end
    return pal
  end)

  if success and palette then
    return palette
  end
  return nil
end

--[[
  Read a 16-bit I/O register from GBA I/O memory (0x04000000 region)
  @param offset Register offset (e.g. 0x0008 for BG0CNT)
  @return u16 value or nil on error
]]
function HAL.readIOReg16(offset)
  local success, value = pcall(function()
    return emu.memory.io:read16(offset)
  end)
  if success then
    return value
  end
  return nil
end

--[[
  Read and parse a BG control register (BGnCNT)
  @param bgIndex BG layer index (0-3)
  @return table {priority, charBaseBlock, is8bpp, screenBaseBlock, screenSize} or nil
]]
function HAL.readBGControl(bgIndex)
  if not bgIndex or bgIndex < 0 or bgIndex > 3 then
    return nil
  end
  local regOffset = 0x0008 + bgIndex * 2
  local val = HAL.readIOReg16(regOffset)
  if not val then
    return nil
  end
  return {
    priority = val & 0x3,
    charBaseBlock = (val >> 2) & 0x3,
    is8bpp = ((val >> 7) & 0x1) == 1,
    screenBaseBlock = (val >> 8) & 0x1F,
    screenSize = (val >> 14) & 0x3,
  }
end

--[[
  Read BG scroll registers (BGnHOFS / BGnVOFS)
  @param bgIndex BG layer index (0-3)
  @return scrollX, scrollY (9-bit masked) or nil, nil
]]
function HAL.readBGScroll(bgIndex)
  if not bgIndex or bgIndex < 0 or bgIndex > 3 then
    return nil, nil
  end
  local hofs = HAL.readIOReg16(0x0010 + bgIndex * 4)
  local vofs = HAL.readIOReg16(0x0012 + bgIndex * 4)
  if not hofs or not vofs then
    return nil, nil
  end
  return hofs & 0x1FF, vofs & 0x1FF
end

--[[
  Read a 16-bit tilemap entry from BG VRAM
  Handles multi-screenblock layouts (32x32, 64x32, 32x64, 64x64)
  @param screenBaseBlock Screen base block (from BGnCNT)
  @param tileX Tile X coordinate in full map space
  @param tileY Tile Y coordinate in full map space
  @param screenSize Screen size code (0=32x32, 1=64x32, 2=32x64, 3=64x64)
  @return u16 tilemap entry or nil
]]
function HAL.readBGTilemapEntry(screenBaseBlock, tileX, tileY, screenSize)
  -- Each screenblock is 32x32 tiles = 2048 bytes
  local sbOffset = 0
  local localX = tileX % 32
  local localY = tileY % 32

  if screenSize == 1 then
    -- 64x32: SB0 (left 32 cols), SB1 (right 32 cols)
    if tileX >= 32 then sbOffset = 1 end
  elseif screenSize == 2 then
    -- 32x64: SB0 (top 32 rows), SB1 (bottom 32 rows)
    if tileY >= 32 then sbOffset = 1 end
  elseif screenSize == 3 then
    -- 64x64: SB0 (TL), SB1 (TR), SB2 (BL), SB3 (BR)
    if tileX >= 32 then sbOffset = sbOffset + 1 end
    if tileY >= 32 then sbOffset = sbOffset + 2 end
  end

  local vramAddr = (screenBaseBlock + sbOffset) * 2048 + (localY * 32 + localX) * 2

  local success, value = pcall(function()
    return emu.memory.vram:read16(vramAddr)
  end)
  if success then
    return value
  end
  return nil
end

--[[
  Read 32 bytes of 4bpp tile pixel data from BG VRAM area
  BG tiles start at VRAM offset 0x0000 (unlike sprites at 0x10000)
  @param charBaseBlock Character base block (from BGnCNT, 0-3)
  @param tileId Tile ID (0-1023)
  @return string of 32 bytes, or nil
]]
function HAL.readBGTileData(charBaseBlock, tileId)
  local offset = charBaseBlock * 0x4000 + tileId * 32

  -- Validate stays within BG VRAM area (0x00000-0x0FFFF)
  if offset < 0 or (offset + 32) > 0x10000 then
    return nil
  end

  local success, data = pcall(function()
    return emu.memory.vram:readRange(offset, 32)
  end)
  if success and data then
    return data
  end
  return nil
end

--[[
  Read a 16-color BG palette bank from palette RAM
  BG palettes start at offset 0x000 (sprite palettes at 0x200)
  @param palBank Palette bank index (0-15)
  @return table of 16 BGR555 values (indexed 0-15), or nil
]]
function HAL.readBGPalette(palBank)
  if not palBank or palBank < 0 or palBank > 15 then
    return nil
  end

  local success, palette = pcall(function()
    local pal = {}
    local base = palBank * 32  -- BG palettes at 0x000 (not 0x200)
    for i = 0, 15 do
      pal[i] = emu.memory.palette:read16(base + i * 2)
    end
    return pal
  end)
  if success and palette then
    return palette
  end
  return nil
end

return HAL
