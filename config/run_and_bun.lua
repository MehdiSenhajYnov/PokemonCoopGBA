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

  -- Warp system addresses (found via scan_warp_addresses.lua on 2026-02-03)
  warp = {
    callback2Addr = 0x0202064C,  -- gMain.callback2 (EWRAM, offset +4 in gMain)
    cb2LoadMap    = 0x08007441,  -- CB2_LoadMap ROM function pointer
    cb2Overworld  = 0x080A89A5,  -- CB2_Overworld ROM function pointer (for completion detect)
  },

  -- Duel room coordinates (MAP_BATTLE_COLOSSEUM_2P — same as vanilla Emerald)
  duelRoom = {
    mapGroup = 28,
    mapId = 24,
    playerAX = 3,
    playerAY = 5,
    playerBX = 10,
    playerBY = 5
  },

  -- Battle system addresses (for PvP combat)
  -- Scanned using scripts/scan_battle_addresses.lua on 2026-02-05
  battle = {
    -- Party data (600 bytes each = 6 Pokemon x 100 bytes)
    gPlayerParty = 0x020233D0,      -- FOUND (via HP at +0x56)
    gEnemyParty = 0x02023458,       -- FOUND (via species scan)

    -- Battle state
    gBattleTypeFlags = 0x020090E8,  -- FOUND
    gTrainerBattleOpponent_A = nil, -- TODO: scan
    gBattleControllerExecFlags = 0x020239FC, -- FOUND
    gBattleBufferB = 0x02022748,    -- FOUND (via delta prediction from gPlayerParty)
    gBattleOutcome = nil,           -- Not found - using gMainInBattle as fallback

    -- gMain struct fields
    gMainInBattle = 0x020233E0,     -- FOUND (inBattle flag)

    -- RNG (IWRAM)
    gRngValue = 0x03005D90,         -- FOUND (changes every frame)

    -- ROM function pointers (for triggering battles)
    CB2_InitBattle = nil,           -- TODO: scan via watchpoint
    CB2_ReturnToField = nil,        -- TODO: scan via watchpoint
    CB2_WhiteOut = nil,             -- TODO: scan via watchpoint
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
