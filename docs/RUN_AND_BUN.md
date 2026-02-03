# Pokémon Run & Bun - Memory Offsets Documentation

> **Status:** Offsets DISCOVERED and IMPLEMENTED
> **Last Updated:** 2026-02-02
> **Method Used:** Static (direct WRAM addresses)

---

## Overview

Pokémon Run & Bun is a heavily modified ROM hack based on Pokémon Emerald. Due to extensive code modifications, **Emerald vanilla memory offsets DO NOT work** directly.

The offsets below were discovered via mGBA Lua memory scanning and are confirmed working.

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

## Known Limitations

### Found and Working
- [x] PlayerX, PlayerY, MapID, MapGroup, Facing - All working
- [x] Camera X/Y - Found in IWRAM (0x03005DFC, 0x03005DF8)
- [x] Ghost rendering - Working via relative screen-center positioning (no camera offsets needed)

### Ghost Rendering Note
Camera offsets (gSpriteCoordOffsetX/Y) were found but are **not used** for ghost positioning.
The tile coordinates are map-local, so `tile*16 + cameraOffset` produces map-dependent results.
Instead, ghost rendering uses **relative positioning**: `ghostScreen = screenCenter + (ghostTile - playerTile) * 16`.
This works because the GBA camera always centers on the player sprite.

### Not Yet Searched (needed for Phase 2+)
- [ ] Player sprite ID - For correct ghost visual (Phase 2)
- [ ] Player name - For ghost labels (Phase 2)
- [ ] Movement state (walk/run/bike) - For animation (Phase 2)
- [ ] Battle flag - For warp mode constraints (Phase 3)
- [ ] Warp target addresses - For duel room teleportation (Phase 3)

### Future Work
- Find player sprite ID for correct visual representation (Phase 2)
- Find battle flag for warp mode constraints (Phase 3)

---

## ROM-Specific Notes

### Run & Bun Differences from Emerald

- **Player data block shifted**: Core player position data is at 0x02024CBC instead of 0x02024844 (shifted +0x878 bytes)
- **Facing direction relocated**: Stored at 0x02036934, far from the position data block (in Emerald it's at 0x02024848, right next to position)
- **Same game ID**: Uses BPEE like vanilla Emerald, so ROM detection relies on title string matching
- **Static offsets**: Despite heavy modifications, the offset mode is still static (no SaveBlock pointer chains needed)

---

## Quick Debug Commands

```lua
-- Run these in mGBA scripting console to verify offsets
print(string.format("X: %d", emu.memory.wram:read16(0x00024CBC)))
print(string.format("Y: %d", emu.memory.wram:read16(0x00024CBE)))
print(string.format("MapGroup: %d", emu.memory.wram:read8(0x00024CC0)))
print(string.format("MapId: %d", emu.memory.wram:read8(0x00024CC1)))
print(string.format("Facing: %d", emu.memory.wram:read8(0x00036934)))
```

Note: WRAM reads use offset from base (0x02000000), so 0x02024CBC becomes 0x00024CBC.

---

## Sign-off

- [x] All 5 critical offsets found and validated
- [x] Config file updated with correct addresses
- [x] HAL works in static mode (no modifications needed)
- [x] ROM detection added to main.lua
- [x] All tests pass (movement, map changes, facing)
- [x] Documentation complete

**Completed:** 2026-02-02
**Verification:** Offsets tested via mGBA Lua scripting console and live gameplay
