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
-- WARP SYSTEM
-- ============================================================
-- Cache for sWarpData EWRAM offset (found via runtime scan)
local sWarpDataOffset = nil

-- Watchpoint state (flag-based: watchpoint sets flag, frame loop processes)
local warpWatchpointId = nil
local warpWatchpointFired = false  -- set true by watchpoint callback

-- Golden warp state (save state buffer captured during first natural warp)
local goldenWarpState = nil

-- SaveBlock1 preservation constants
local SAVEBLOCK1_BASE = 0x02024CBC   -- SaveBlock1 start in Run & Bun
local SAVEBLOCK1_WORDS = 4096        -- 16KB / 4 bytes = 4096 u32 words

--[[
  Scan EWRAM to find sWarpData address.
  sWarpData is the game's internal warp destination struct. CB2_LoadMap reads
  from sWarpData (not SaveBlock1) to know where to load. After any map transition,
  sWarpData and SaveBlock1->location contain identical bytes, so we can find
  sWarpData by scanning for duplicates of SaveBlock1->location in EWRAM.

  Call this after HAL.init() and after each natural map change.
  @return boolean True if sWarpData was found (or was already cached)
]]
function HAL.findSWarpData()
  if not config or not config.warp then return false end
  if sWarpDataOffset then return true end -- Already cached

  local locOffset = toWRAMOffset(config.offsets.mapGroup)

  -- Read SaveBlock1->location (8 bytes: mapGroup + mapNum + warpId + pad + x + y)
  local ok1, ref32a = pcall(emu.memory.wram.read32, emu.memory.wram, locOffset)
  local ok2, ref32b = pcall(emu.memory.wram.read32, emu.memory.wram, locOffset + 4)
  if not ok1 or not ok2 then return false end

  -- Skip if data is zeroed (game not fully initialized)
  if ref32a == 0 and ref32b == 0 then return false end

  console:log("[HAL] Scanning EWRAM for sWarpData...")

  for offset = 0, 0x3FFFC, 4 do
    -- Skip the SaveBlock1->location range itself
    if offset < locOffset or offset >= locOffset + 8 then
      local s1, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
      if s1 and val == ref32a then
        local s2, val2 = pcall(emu.memory.wram.read32, emu.memory.wram, offset + 4)
        if s2 and val2 == ref32b then
          sWarpDataOffset = offset
          console:log(string.format("[HAL] sWarpData found at 0x%08X", 0x02000000 + offset))
          return true
        end
      end
    end
  end

  console:log("[HAL] sWarpData not found (enter a door to calibrate)")
  return false
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
  Phase 2: Trigger the map load by properly preparing gMain state.

  The game's main loop calls callback1() then callback2() each frame.
  Setting callback2 = CB2_LoadMap alone causes a freeze because:
  - callback1 (CB1_Overworld) keeps processing events/camera, conflicting with map load
  - gMain.state must be 0 for CB2_LoadMap's switch/state machine to start correctly
  - VBlank/HBlank/VCount/Serial interrupt callbacks may interfere

  Fix: replicate what the game's Task_WarpAndLoadMap does before setting CB2_LoadMap.

  gMain struct layout (pokeemerald Main struct, size 0x44 = 68 bytes):
    +0x00  callback1          (4 bytes) MainCallback
    +0x04  callback2          (4 bytes) MainCallback
    +0x08  savedCallback      (4 bytes) MainCallback
    +0x0C  vblankCallback     (4 bytes) IntrCallback
    +0x10  hblankCallback     (4 bytes) IntrCallback
    +0x14  vcountCallback     (4 bytes) IntrCallback
    +0x18  serialCallback     (4 bytes) IntrCallback
    +0x1C  intrCheck          (2 bytes) u16
    +0x1E  vblankCounter1     (4 bytes) u32
    +0x22  vblankCounter2     (4 bytes) u32
    +0x26  heldKeysRaw        (2 bytes) u16
    +0x28  heldKeys           (2 bytes) u16
    +0x2A  newKeys            (2 bytes) u16
    +0x2C  newAndRepeatedKeys (2 bytes) u16
    +0x2E  keyRepeatCounter   (2 bytes) u16
    +0x30  watchedKeysPressed (2 bytes) bool16
    +0x32  watchedKeysMask    (2 bytes) u16
    +0x34  objCount           (1 byte)  u8
    +0x35  state              (1 byte)  u8  ← CRITICAL for CB2_LoadMap switch
    +0x36  oamLoadDisabled    (1 byte)  u8
    +0x37  inBattle           (1 byte)  u8

  Call this a few frames AFTER writeWarpData().
  @return boolean Success status
]]
function HAL.triggerMapLoad()
  if not config or not config.warp then return false end

  -- gMain base = callback2Addr - 4 (callback2 is at offset +4)
  local gMainBase = config.warp.callback2Addr - 4
  local base = toWRAMOffset(gMainBase)

  -- 1. NULL callback1 to stop CB1_Overworld from interfering
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x00, 0)

  -- 2. NULL savedCallback
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x08, 0)

  -- 3. Clear all interrupt callbacks (VBlank, HBlank, VCount, Serial)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x0C, 0)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x10, 0)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x14, 0)
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x18, 0)

  -- 4. Zero gMain.state at +0x35 (CRITICAL: CB2_LoadMap switch starts from case 0)
  pcall(emu.memory.wram.write8, emu.memory.wram, base + 0x35, 0)

  -- 5. Set callback2 = CB2_LoadMap
  pcall(emu.memory.wram.write32, emu.memory.wram, base + 0x04, config.warp.cb2LoadMap)

  console:log(string.format("[HAL] triggerMapLoad: cb1=NULL state(@+0x35)=0 intrs=NULL cb2=0x%08X",
    config.warp.cb2LoadMap))
  return true
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
  Setup a WRITE_CHANGE watchpoint on gMain.callback2.
  Uses FLAG-BASED approach: the watchpoint callback only sets a flag.
  The main frame loop must call HAL.checkWarpWatchpoint() each frame to process.

  This avoids crashes from reading/writing memory inside watchpoint callbacks
  (known mGBA issue #3050).

  @return boolean True if watchpoint was set successfully
]]
function HAL.setupWarpWatchpoint()
  if not config or not config.warp then
    console:log("[HAL] setupWarpWatchpoint: no warp config")
    return false
  end

  -- Clear existing watchpoint if any
  if warpWatchpointId then
    pcall(emu.clearBreakpoint, emu, warpWatchpointId)
    warpWatchpointId = nil
  end

  local addr = config.warp.callback2Addr

  local ok, wpId = pcall(function()
    return emu:setWatchpoint(function()
      -- MINIMAL work here: just set flag. Memory access in watchpoint = crash risk.
      warpWatchpointFired = true
    end, addr, C.WATCHPOINT_TYPE.WRITE_CHANGE)
  end)

  if ok and wpId then
    warpWatchpointId = wpId
    warpWatchpointFired = false
    console:log(string.format("[HAL] Watchpoint set on callback2 (0x%08X), id=%d", addr, wpId))
    return true
  else
    console:log("[HAL] ERROR: Failed to set watchpoint on callback2")
    return false
  end
end

--[[
  Check if the warp watchpoint fired since last check.
  Call this every frame from the main loop.

  @return boolean True if callback2 changed to CB2_LoadMap this frame
]]
function HAL.checkWarpWatchpoint()
  if not warpWatchpointFired then
    return false
  end
  warpWatchpointFired = false

  -- Now safe to read memory (we're in frame callback context, not watchpoint)
  local cb2 = HAL.readCallback2()
  if not cb2 then return false end

  return cb2 == config.warp.cb2LoadMap
end

--[[
  Check if a golden warp state has been captured.
  @return boolean
]]
function HAL.hasGoldenState()
  return goldenWarpState ~= nil
end

--[[
  Capture the golden warp state (save state buffer).
  Call this when callback2 transitions to CB2_LoadMap during a natural warp.
  The emulator is in a clean mid-warp state at this point.

  @return boolean True if capture succeeded
]]
function HAL.captureGoldenState()
  local ok, buf = pcall(function()
    return emu:saveStateBuffer()  -- flags=31 (ALL) by default
  end)

  if ok and buf then
    goldenWarpState = buf
    console:log(string.format("[HAL] Golden warp state captured (%d bytes)", #buf))
    return true
  else
    console:log("[HAL] ERROR: Failed to capture golden state")
    return false
  end
end

--[[
  Load the golden warp state.
  Restores the emulator to the clean mid-warp state.
  SRAM (save file) is NOT overwritten (default flags=29).

  @return boolean True if load succeeded
]]
function HAL.loadGoldenState()
  if not goldenWarpState then
    console:log("[HAL] loadGoldenState: no golden state captured")
    return false
  end

  local ok, result = pcall(function()
    return emu:loadStateBuffer(goldenWarpState, 29)  -- 29 = ALL except SAVEDATA (SRAM not overwritten)
  end)

  if ok and result then
    console:log("[HAL] Golden warp state loaded")
    return true
  else
    console:log("[HAL] ERROR: Failed to load golden state")
    return false
  end
end

--[[
  Save current game data from SaveBlock1 in WRAM.
  Reads 16KB (4096 x u32) starting from SAVEBLOCK1_BASE.
  This preserves the player's team, inventory, flags, progression, etc.

  @return table Array of u32 values, or nil on failure
]]
function HAL.saveGameData()
  local data = {}
  local baseOffset = toWRAMOffset(SAVEBLOCK1_BASE)

  local ok = pcall(function()
    for i = 0, SAVEBLOCK1_WORDS - 1 do
      data[i] = emu.memory.wram:read32(baseOffset + i * 4)
    end
  end)

  if ok then
    console:log(string.format("[HAL] Game data saved (%d words from 0x%08X)",
      SAVEBLOCK1_WORDS, SAVEBLOCK1_BASE))
    return data
  else
    console:log("[HAL] ERROR: Failed to save game data")
    return nil
  end
end

--[[
  Restore game data to SaveBlock1 in WRAM.
  Writes back the 16KB saved by saveGameData().

  @param data table Array of u32 values (from saveGameData)
  @return boolean True if restore succeeded
]]
function HAL.restoreGameData(data)
  if not data then return false end

  local baseOffset = toWRAMOffset(SAVEBLOCK1_BASE)

  local ok = pcall(function()
    for i = 0, SAVEBLOCK1_WORDS - 1 do
      if data[i] then
        emu.memory.wram:write32(baseOffset + i * 4, data[i])
      end
    end
  end)

  if ok then
    console:log(string.format("[HAL] Game data restored (%d words to 0x%08X)",
      SAVEBLOCK1_WORDS, SAVEBLOCK1_BASE))
    return true
  else
    console:log("[HAL] ERROR: Failed to restore game data")
    return false
  end
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
