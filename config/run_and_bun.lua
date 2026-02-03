--[[
  Pokémon Run & Bun Configuration

  ROM hack based on Pokémon Emerald with extensive modifications
  Game ID: BPEE (same as Emerald)

  Offsets found via mGBA memory scanning on: 2026-02-02
  Camera offsets found on: 2026-02-03
  Method: STATIC (player in EWRAM, camera in IWRAM)
]]

return {
  name = "Pokémon Run & Bun",
  gameId = "BPEE",
  version = "1.0",

  offsets = {
    playerX = 0x02024CBC,     -- 16-bit
    playerY = 0x02024CBE,     -- 16-bit
    mapGroup = 0x02024CC0,    -- 8-bit
    mapId = 0x02024CC1,       -- 8-bit
    facing = 0x02036934,      -- 8-bit, EWRAM

    -- Camera offsets (IWRAM 0x03000000 region - read via emu.memory.iwram)
    cameraX = 0x03005DFC,     -- s16, IWRAM (gSpriteCoordOffsetX)
    cameraY = 0x03005DF8,     -- s16, IWRAM (gSpriteCoordOffsetY)
  },

  facing = {
    NONE = 0,
    DOWN = 1,
    UP = 2,
    LEFT = 3,
    RIGHT = 4
  },

  validation = {
    minX = 0,
    maxX = 2048,
    minY = 0,
    maxY = 2048,
    minMapGroup = 0,
    maxMapGroup = 50,
    minMapId = 0,
    maxMapId = 255
  },

  validatePosition = function(self, x, y, mapGroup, mapId)
    local v = self.validation
    if x < v.minX or x > v.maxX then return false end
    if y < v.minY or y > v.maxY then return false end
    if mapGroup < v.minMapGroup or mapGroup > v.maxMapGroup then return false end
    if mapId < v.minMapId or mapId > v.maxMapId then return false end
    return true
  end,
}
