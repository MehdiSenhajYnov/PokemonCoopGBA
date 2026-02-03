--[[
  Pokémon Emerald (US) Configuration

  Game ID: BPEE (from ROM header)
  Version: US 1.0

  Memory offsets for player position and map data
  Tested on Pokémon Emerald US ROM
]]

return {
  -- Game metadata
  name = "Pokémon Emerald (US)",
  gameId = "BPEE",
  version = "1.0",

  -- Memory offsets
  offsets = {
    -- Player coordinates (16-bit values)
    playerX = 0x02024844,       -- Player X coordinate
    playerY = 0x02024846,       -- Player Y coordinate

    -- Map information (8-bit values)
    mapGroup = 0x02024843,      -- Map group (region)
    mapId = 0x02024842,         -- Map ID (specific map)

    -- Player state
    facing = 0x02024848,        -- Facing direction: 1=Down, 2=Up, 3=Left, 4=Right

    -- Additional offsets for future use
    isMoving = 0x02024849,      -- Movement state flag
    runningState = 0x0202484A,  -- Walking/Running state

    -- SaveBlock pointers (for dynamic data)
    saveBlock1Ptr = 0x03005D8C, -- Pointer to SaveBlock1
    saveBlock2Ptr = 0x03005D90, -- Pointer to SaveBlock2

    -- Warp target coordinates (for duel warp feature)
    warpMapGroup = 0x02024D14,  -- Target map group for warp
    warpMapId = 0x02024D15,     -- Target map ID for warp
    warpX = 0x02024D16,         -- Target X for warp
    warpY = 0x02024D17,         -- Target Y for warp
  },

  -- Known map locations (for reference and validation)
  maps = {
    -- Battle facilities
    battleColosseum = {
      mapGroup = 7,
      mapId = 4,
      description = "Battle Colosseum (for Link battles)"
    },

    -- Starting areas
    littleroot = {
      mapGroup = 3,
      mapId = 1,
      description = "Littleroot Town"
    },

    oldale = {
      mapGroup = 3,
      mapId = 2,
      description = "Oldale Town"
    },
  },

  -- Facing direction constants
  facing = {
    NONE = 0,
    DOWN = 1,
    UP = 2,
    LEFT = 3,
    RIGHT = 4
  },

  -- Validation ranges
  validation = {
    -- Coordinate limits (most maps use 0-255 range)
    minX = 0,
    maxX = 1024,
    minY = 0,
    maxY = 1024,

    -- Map limits
    minMapGroup = 0,
    maxMapGroup = 34,
    minMapId = 0,
    maxMapId = 255
  },

  --[[
    Validate position data
    @param x X coordinate
    @param y Y coordinate
    @param mapGroup Map group
    @param mapId Map ID
    @return boolean True if valid
  ]]
  validatePosition = function(self, x, y, mapGroup, mapId)
    local v = self.validation

    if x < v.minX or x > v.maxX then return false end
    if y < v.minY or y > v.maxY then return false end
    if mapGroup < v.minMapGroup or mapGroup > v.maxMapGroup then return false end
    if mapId < v.minMapId or mapId > v.maxMapId then return false end

    return true
  end,

  --[[
    Get spawn coordinates for duel warp
    Returns coordinates in front of Battle Colosseum NPC
  ]]
  getDuelWarpCoords = function(self)
    return {
      mapGroup = self.maps.battleColosseum.mapGroup,
      mapId = self.maps.battleColosseum.mapId,
      x = 7,  -- Example coordinates (adjust based on actual map)
      y = 8,
      facing = self.facing.UP
    }
  end
}
