# Pokémon Run & Bun - Memory Offsets & Reference Data

> **Status:** Core offsets VERIFIED, battle system IN PROGRESS
> **Last Updated:** 2026-02-05
> **Method Used:** Static (direct WRAM addresses)
> **Base Project:** pokeemerald-expansion (RHH) — by dekzeh

---

## Overview

Pokémon Run & Bun is built on **pokeemerald-expansion** (ROM Hacking Hideout), which extends Pokémon Emerald with Gen 1-8 support. Due to extensive code modifications, **Emerald vanilla memory offsets DO NOT work** directly.

The offsets below come from two sources:
1. **mGBA Lua memory scanning** (overworld + warp + battle state)
2. **Cross-reference with [pokemon-run-bun-exporter](https://github.com/luisvega23/pokemon-run-bun-exporter)** (party addresses — community-validated)

---

## Memory Offset Discovery Process

### Date: 2026-02-02
### Tools Used:
- mGBA dev build #8977 (2026-02-02)
- Scripts: `scripts/scan_wram.lua`, `scripts/validate_offsets.lua`

### Method:

**Step 1: Test Vanilla Offsets**
- [x] Ran `scripts/scan_vanilla_offsets.lua`
- [x] Result: Failed - Emerald vanilla offsets do NOT work for Run & Bun

**Step 2: Manual Scanning**
- [x] Used `scripts/scan_wram.lua` to find PlayerX
- [x] Used `scripts/scan_wram.lua` to find PlayerY
- [x] Used `scripts/scan_wram.lua` to find MapID
- [x] Used `scripts/scan_wram.lua` to find MapGroup
- [x] Used `scripts/scan_wram.lua` to find Facing

**Step 3: Static vs Dynamic**
- [x] Tested persistence across sessions
- [x] Result: **STATIC** - addresses are fixed, no pointer chains needed

**Step 4: SaveBlock Pointers**
- N/A - offsets are static, no dynamic pointers required

---

## Discovered Offsets

### Configuration Mode
- **Type:** STATIC (direct WRAM addresses)
- **ROM Game ID:** BPEE (same as Emerald)
- **ROM Title:** Detected from header (contains "RUN" or "BUN")

### Static Offsets

```lua
-- Memory addresses in WRAM (0x02000000 - 0x0203FFFF)
playerX      = 0x02024CBC  -- 16-bit (Emerald vanilla: 0x02024844)
playerY      = 0x02024CBE  -- 16-bit (Emerald vanilla: 0x02024846)
mapGroup     = 0x02024CC0  -- 8-bit  (Emerald vanilla: 0x02024843)
mapId        = 0x02024CC1  -- 8-bit  (Emerald vanilla: 0x02024842)
facing       = 0x02036934  -- 8-bit  (Emerald vanilla: 0x02024848)
```

### Camera Offsets (found 2026-02-03)

```lua
-- Camera offsets in IWRAM (0x03000000 - 0x03007FFF)
cameraX      = 0x03005DFC  -- s16, IWRAM (gSpriteCoordOffsetX)
cameraY      = 0x03005DF8  -- s16, IWRAM (gSpriteCoordOffsetY)
```

Found via `scripts/scan_camera_auto.lua` (automatic differential IWRAM scanner).
Verified with `scripts/verify_camera.lua`: delta = exactly ±16 per tile moved.

Note: Camera offsets are in **IWRAM** (not EWRAM like player data). Read via `emu.memory.iwram:read16(offset)`.

### Key Observations
- PlayerX/Y/MapGroup/MapId are grouped together (0x02024CBC-0x02024CC1), offset ~0x878 from Emerald
- Facing direction is stored much further in memory (0x02036934 vs 0x02024848), offset ~0x120EC from Emerald
- Camera offsets are in IWRAM (0x03000000 region), separate from player data in EWRAM
- All player addresses are within valid WRAM range

---

## Validation Results

### Movement Validation (2026-02-02)

| Action | Expected | Result |
|--------|----------|--------|
| Move UP | Y decreases | Confirmed |
| Move DOWN | Y increases | Confirmed |
| Move LEFT | X decreases | Confirmed |
| Move RIGHT | X increases | Confirmed |

### Map Change Validation (2026-02-02)

| Action | Result |
|--------|--------|
| Enter building | MapID and MapGroup change correctly |
| Exit building | MapID and MapGroup restore correctly |
| Change route | Values update on zone transition |

### Facing Direction Validation (2026-02-02)

| Direction | Expected Value | Result |
|-----------|----------------|--------|
| Down | 1 | Confirmed |
| Up | 2 | Confirmed |
| Left | 3 | Confirmed |
| Right | 4 | Confirmed |

### Persistence Test (Static Offsets)
- Addresses are consistent across save/load cycles
- Confirmed as static (no pointer indirection needed)

---

## Implementation

### Config File: `config/run_and_bun.lua`

```lua
return {
  name = "Pokémon Run & Bun",
  gameId = "BPEE",
  version = "1.0",

  offsets = {
    playerX = 0x02024CBC,     -- 16-bit
    playerY = 0x02024CBE,     -- 16-bit
    mapGroup = 0x02024CC0,    -- 8-bit
    mapId = 0x02024CC1,       -- 8-bit
    facing = 0x02036934,      -- 8-bit
  },

  -- ... validation, facing constants
}
```

### Files Modified
- `config/run_and_bun.lua` - Filled with discovered offsets
- `client/config/run_and_bun.lua` - Mirror copy
- `client/hal.lua` - No changes needed (static mode)
- `client/main.lua` - ROM detection for Run & Bun added

---

## Party & Battle Addresses (2026-02-05)

### Party Data (from pokemon-run-bun-exporter — community validated)

```lua
gPlayerParty      = 0x02023A98  -- 600 bytes (6 * 100), EWRAM
gPlayerPartyCount = 0x02023A95  -- 8-bit, 3 bytes before gPlayerParty
gEnemyParty       = 0x02023CF0  -- gPlayerParty + 0x258 (600 bytes)
gPokemonStorage   = 0x02028848  -- PC box storage, EWRAM
```

**NOTE**: Previous scanner found gPlayerParty at 0x020233D0 — this was WRONG. The exporter's address 0x02023A98 is correct (community-tested).

### Battle State (from mGBA scanner)

```lua
gBattleTypeFlags           = 0x020090E8  -- 32-bit
gBattleControllerExecFlags = 0x020239FC  -- 32-bit (needs verification)
gMainInBattle              = 0x020206AE  -- gMain + 0x66 (bit 1)
gRngValue                  = 0x03005D90  -- IWRAM, 32-bit (changes every frame)
gBattleBufferB             = nil         -- INVALIDATED (was derived from wrong base)
gBattleOutcome             = nil         -- Not found yet
```

### ROM Function Pointers

```lua
CB2_BattleMain = 0x08094815  -- Active during entire battle
CB2_LoadMap    = 0x08007441  -- Map load transition
CB2_Overworld  = 0x080A89A5  -- Overworld callback (warp completion detect)
```

---

## Pokémon Struct Layout

Run & Bun uses pokeemerald-expansion struct format:

### struct Pokemon (100 bytes = 0x64)

| Offset | Size | Field | Notes |
|--------|------|-------|-------|
| +0x00 | u32 | personality | PID |
| +0x04 | u32 | otId | Original Trainer ID |
| +0x08 | 10B | nickname | GBA charset |
| +0x13 | u8 | flags | bit0=badEgg, bit1=hasSpecies, bit2=isEgg |
| +0x14 | 10B | otName | Trainer name |
| +0x20 | 48B | **encrypted** | 4 substructs × 12B, XOR `otId ^ personality` |
| +0x50 | u32 | status | Status condition bitfield |
| +0x54 | u8 | level | Current level |
| +0x56 | u16 | hp | Current HP |
| +0x58 | u16 | maxHP | Maximum HP |
| +0x5A | u16 | attack | Attack stat |
| +0x5C | u16 | defense | Defense stat |
| +0x5E | u16 | speed | Speed stat |
| +0x60 | u16 | spAttack | Sp. Attack stat |
| +0x62 | u16 | spDefense | Sp. Defense stat |

### Substruct Decryption

Substructs are reordered by `personality % 24` (24 permutations). Each is 12 bytes (3 × u32 words), XOR decrypted with `otId ^ personality`.

- **Sub 0 (Growth)**: species(16b), heldItem(16b), experience(32b), ppBonuses(8b), friendship(8b), **hiddenNature**(5b, R&B-specific, 26=PID)
- **Sub 1 (Attacks)**: move1-4(16b each), pp1-4(8b each)
- **Sub 2 (EVs)**: hpEV, atkEV, defEV, spdEV, spAtkEV, spDefEV (8b each)
- **Sub 3 (Misc)**: pokerus, metLocation, IVs(5b each), **altAbility**(2b: 0=primary, 1=secondary, 2=hidden)

---

## Run & Bun Game Data

From `refs/runandbundex` (official data by dekzeh):

| Data | Count | Notes |
|------|-------|-------|
| Species | 1234 | Gen 1-8 + all forms (Mega, Alolan, Galarian, Hisuian) |
| Moves | 782 | Through Gen 8 "Take Heart" |
| Abilities | 267 | Gen 1-8 + custom modifications |
| Maps with encounters | 131 | Hoenn layout with custom encounter tables |

### Key R&B Modifications
- Trade evolutions → level-based (Haunter→Gengar lvl 40, Kadabra→Alakazam lvl 36)
- Magma Armor: "Blocks criticals and freeze" (custom ability effect)
- Hidden Nature field in growth substruct (not in vanilla Emerald)
- 3-ability system (primary/secondary/hidden, 2 bits)

---

## Known Limitations

### Found and Working
- [x] PlayerX, PlayerY, MapID, MapGroup, Facing — overworld working
- [x] Camera X/Y — IWRAM (0x03005DFC, 0x03005DF8)
- [x] Ghost rendering — relative screen-center positioning
- [x] Warp system — save state hijack + door fallback
- [x] gPlayerParty, gEnemyParty — corrected from exporter
- [x] gBattleTypeFlags, gRngValue — from scanner

### Needs Verification/Re-scan
- [ ] gBattleBufferB — was derived from wrong gPlayerParty, needs re-scan
- [ ] gBattleOutcome — not found yet (using inBattle transition as fallback)
- [ ] gBattleControllerExecFlags — found but very close to gPlayerParty, verify

---

## ROM-Specific Notes

### Run & Bun Differences from Emerald

- **Built on pokeemerald-expansion** (not binary-hacked) — struct layouts follow expansion conventions
- **Player data block shifted**: 0x02024CBC instead of 0x02024844 (shifted +0x878 bytes)
- **Facing direction relocated**: 0x02036934, far from position data
- **Party relocated**: 0x02023A98 instead of vanilla's position
- **Same game ID**: BPEE — ROM detection relies on title string
- **Static offsets**: No SaveBlock pointer chains needed

---

## Quick Debug Commands

```lua
-- Overworld
print(string.format("X: %d", emu.memory.wram:read16(0x00024CBC)))
print(string.format("Y: %d", emu.memory.wram:read16(0x00024CBE)))
print(string.format("Map: %d:%d", emu.memory.wram:read8(0x00024CC0), emu.memory.wram:read8(0x00024CC1)))
print(string.format("Facing: %d", emu.memory.wram:read8(0x00036934)))

-- Party
print(string.format("PartyCount: %d", emu.memory.wram:read8(0x00023A95)))
print(string.format("Party[0] species: %d", emu.memory.wram:read16(0x00023A98)))  -- encrypted!
print(string.format("Party[0] HP: %d", emu.memory.wram:read16(0x00023A98 + 86)))

-- Battle state
print(string.format("BattleFlags: 0x%08X", emu.memory.wram:read32(0x000090E8)))
print(string.format("InBattle: %d", emu.memory.wram:read8(0x000206AE)))
```

---

## Reference Repos (in refs/)

| Repo | Content | Usage |
|------|---------|-------|
| `pokemon-run-bun-exporter` | Party read code + validated addresses | Source of truth for gPlayerParty |
| `runandbundex` | Species, moves, abilities, encounters data (C) | Game data reference |
| `pokeemerald-expansion` | Full source decomp (structs, headers) | Struct layouts, battle constants |

---

## Sign-off

- [x] All 5 overworld offsets found and validated (2026-02-02)
- [x] Camera offsets found (2026-02-03)
- [x] Warp system addresses found and working (2026-02-03)
- [x] Party addresses corrected via community cross-reference (2026-02-05)
- [x] Config enriched with struct constants and battle flags (2026-02-05)
- [x] Reference repos cloned locally (2026-02-05)
- [ ] Battle buffer addresses need re-verification

**Last Updated:** 2026-02-05
**Verification:** Overworld tested live, party addresses from community-validated exporter
