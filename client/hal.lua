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
