--[[
  Pokémon Run & Bun Configuration

  ROM hack based on Pokémon Emerald, built on pokeemerald-expansion (RHH)
  Game ID: BPEE (same as Emerald)
  Creator: dekzeh

  Offsets found via mGBA memory scanning on: 2026-02-02
  Camera offsets found on: 2026-02-03
  Party addresses corrected on: 2026-02-05 (cross-referenced with pokemon-run-bun-exporter)
  Method: STATIC (player in EWRAM, camera in IWRAM)

  Reference repos (cloned in refs/):
  - refs/pokemon-run-bun-exporter  — Lua exporter with validated party addresses
  - refs/runandbundex               — Official data tables (species, moves, abilities)
  - refs/pokeemerald-expansion      — Source structs and battle constants
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

    -- gMain.state offset from gMain base (for CB2_LoadMap switch statement)
    -- Confirmed from pokeemerald-expansion main.h: state is always 1 byte before inBattle bitfield
    -- R&B has inBattle at gMain+0x66 → state = gMain+0x65
    gMainStateOffset = 0x65,     -- CONFIRMED (main.h: state is 1 byte before inBattle)

    -- sWarpData address: auto-detected at runtime by HAL.trackCallback2()
    -- After initial game load (CB2_LoadMap → CB2_Overworld), sWarpDestination matches
    -- SaveBlock1->location in EWRAM. HAL scans for this pattern automatically.
    -- Set a fixed address here only if auto-detection fails.
    sWarpDataAddr = nil,         -- AUTO-DETECTED at runtime (no manual scan needed)

    -- WarpIntoMap ROM address: auto-detected by HAL.scanROMForWarpFunction()
    -- Used by EWRAM trampoline: writes THUMB code to EWRAM that calls WarpIntoMap + CB2_LoadMap.
    -- GBA has no MMU — EWRAM is executable. This avoids needing SetCB2WarpAndLoadMap.
    -- Set manually only if auto-detection fails.
    warpIntoMapAddr = nil,       -- AUTO-DETECTED via ROM scan (Phase 1-3 or fallback)

    -- Legacy: SetCB2WarpAndLoadMap ROM address (if known, used as Priority 2)
    setCB2WarpAddr = nil,        -- Manual override only
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

  -- Pokemon structure constants (from pokeemerald-expansion + run-bun-exporter)
  pokemon = {
    PARTY_SIZE = 6,
    PARTY_MON_SIZE = 100,     -- sizeof(struct Pokemon) = BoxPokemon(80) + battle stats(20)
    BOX_MON_SIZE = 80,        -- sizeof(struct BoxPokemon) = header(32) + encrypted(48)
    FULL_PARTY_BYTES = 600,   -- 6 * 100

    -- PartyMon offsets from mon base address
    HP_OFFSET = 86,           -- +0x56: u16 current HP
    MAX_HP_OFFSET = 88,       -- +0x58: u16 max HP
    LEVEL_OFFSET = 84,        -- +0x54: u8 level
    STATUS_OFFSET = 80,       -- +0x50: u32 status condition
    ATTACK_OFFSET = 90,       -- +0x5A: u16
    DEFENSE_OFFSET = 92,      -- +0x5C: u16
    SPEED_OFFSET = 94,        -- +0x5E: u16
    SP_ATTACK_OFFSET = 96,    -- +0x60: u16
    SP_DEFENSE_OFFSET = 98,   -- +0x62: u16

    -- BoxMon header offsets
    PERSONALITY_OFFSET = 0,   -- +0x00: u32
    OT_ID_OFFSET = 4,         -- +0x04: u32
    NICKNAME_OFFSET = 8,      -- +0x08: 10 bytes
    ENCRYPTED_OFFSET = 32,    -- +0x20: 48 bytes (4 substructs x 12 bytes, XOR encrypted)

    -- Run & Bun specific
    NUM_SPECIES = 1234,       -- Gen 1-8 + forms (species IDs 0-1233)
    NUM_MOVES = 782,          -- Through Gen 8 "Take Heart"
    HAS_HIDDEN_NATURE = true, -- bits 16-20 of growth substruct word 2 (value 26 = use PID)
    HAS_3_ABILITIES = true,   -- altAbility uses 2 bits (0=primary, 1=secondary, 2=hidden)
  },

  -- Battle system addresses (for PvP combat)
  battle = {
    -- Party data — CORRECTED from pokemon-run-bun-exporter (community-validated)
    gPlayerParty      = 0x02023A98,  -- VERIFIED: from run-bun-exporter (was 0x020233D0 from scanner)
    gPlayerPartyCount = 0x02023A95,  -- VERIFIED: from run-bun-exporter (3 bytes before gPlayerParty)
    gEnemyParty       = 0x02023CF0,  -- DERIVED: gPlayerParty + 0x258 (600 bytes = 6 * 100)
    gPokemonStorage   = 0x02028848,  -- VERIFIED: from run-bun-exporter (PC box storage)

    -- Battle state (found via scanner — need re-verification with corrected base)
    gBattleTypeFlags = 0x020090E8,  -- FOUND via scanner (independent, likely correct)
    gTrainerBattleOpponent_A = nil, -- TODO: scan
    gBattleControllerExecFlags = 0x020239FC, -- FOUND via scanner — WARNING: very close to gPlayerParty, verify
    gBattleBufferB = nil,           -- INVALIDATED: was 0x02022748 (derived from wrong gPlayerParty), re-scan needed
    gBattleOutcome = nil,           -- Not found — using gMainInBattle as fallback

    -- gMain struct fields
    gMainAddr = 0x02020648,         -- gMain base address (callback2Addr - 4)
    gMainInBattle = 0x020206AE,     -- FOUND via find_inbattle_offset.lua (gMain+0x66, pattern 0→1→0)

    -- RNG (IWRAM)
    gRngValue = 0x03005D90,         -- FOUND (changes every frame)

    -- ROM function pointers (found via scan_battle_callbacks.lua)
    CB2_BattleMain = 0x08094815,    -- FOUND: active during entire battle
    CB2_InitBattle = nil,           -- Not separate in R&B (CB2_LoadMap handles init)
    CB2_ReturnToField = nil,        -- Not separate in R&B (CB2_LoadMap handles return)
    CB2_WhiteOut = nil,             -- TODO: lose a battle to find

    -- ROM data tables (read-only, for display/validation)
    speciesNameTable = 0x003185C8,  -- From run-bun-exporter (ROM address, not WRAM)
  },

  -- Battle type flag constants (from pokeemerald-expansion include/constants/battle.h)
  battleFlags = {
    DOUBLE       = 0x00000001,  -- 1 << 0
    LINK         = 0x00000002,  -- 1 << 1
    IS_MASTER    = 0x00000004,  -- 1 << 2
    TRAINER      = 0x00000008,  -- 1 << 3
    FIRST_BATTLE = 0x00000010,  -- 1 << 4
    SAFARI       = 0x00000080,  -- 1 << 7
    BATTLE_TOWER = 0x00000100,  -- 1 << 8
    RECORDED     = 0x01000000,  -- 1 << 24
    SECRET_BASE  = 0x08000000,  -- 1 << 27
  },

  -- Battle outcome constants (from pokeemerald-expansion)
  battleOutcome = {
    WON       = 1,
    LOST      = 2,
    DREW      = 3,
    RAN       = 4,
    CAUGHT    = 7,
    FORFEITED = 9,
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
