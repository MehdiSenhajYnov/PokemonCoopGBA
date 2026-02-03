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

-- Current game configuration
local config = nil

--[[
  Initialize HAL with game-specific configuration
  @param gameConfig Table containing memory offsets for the current ROM
]]
function HAL.init(gameConfig)
  config = gameConfig
  console:log("[HAL] Initialized with config: " .. (gameConfig.name or "Unknown"))
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

return HAL
