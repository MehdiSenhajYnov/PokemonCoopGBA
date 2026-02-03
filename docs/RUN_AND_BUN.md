# Pokémon Run & Bun - Memory Offsets Documentation

> **Status:** 🔴 Offsets NOT YET DISCOVERED
> **Last Updated:** [DATE TBD]
> **Method Used:** [TBD - Static or Dynamic]

---

## Overview

Pokémon Run & Bun is a heavily modified ROM hack based on Pokémon Emerald. Due to extensive code modifications, **Emerald vanilla memory offsets DO NOT work** directly.

This document records the discovered memory offsets specific to Run & Bun after completing the memory scanning procedure.

---

## Memory Offset Discovery Process

### Date: [TBD]
### Tools Used:
- mGBA version: [TBD]
- Run & Bun ROM version: [TBD]
- Scripts: `scripts/scan_*.lua`

### Method:

**Step 1: Test Vanilla Offsets**
- [ ] Ran `scripts/scan_vanilla_offsets.lua`
- [ ] Result: ✅ Worked / ❌ Failed

**Step 2: Manual Scanning (if needed)**
- [ ] Used `scripts/scan_wram.lua` to find PlayerX
- [ ] Used `scripts/scan_wram.lua` to find PlayerY
- [ ] Used `scripts/scan_wram.lua` to find MapID
- [ ] Used `scripts/scan_wram.lua` to find MapGroup
- [ ] Used `scripts/scan_wram.lua` to find Facing

**Step 3: Static vs Dynamic**
- [ ] Tested persistence across sessions
- [ ] Result: ✅ Static / ❌ Dynamic

**Step 4: SaveBlock Pointers (if dynamic)**
- [ ] Ran `scripts/find_saveblock_pointers.lua`
- [ ] Found SaveBlock1 pointer at: [ADDRESS TBD]
- [ ] Dumped structure and located offsets

---

## Discovered Offsets

### Configuration Mode
- **Type:** [STATIC or DYNAMIC - TBD]
- **ROM Game ID:** [TBD - detected from 0x080000AC]
- **ROM Title:** [TBD - detected from 0x080000A0]

### Static Offsets (if applicable)

```lua
-- Memory addresses in WRAM (0x02000000 - 0x0203FFFF)
playerX      = 0x02??????  -- [TBD] (16-bit)
playerY      = 0x02??????  -- [TBD] (16-bit)
mapId        = 0x02??????  -- [TBD] (8-bit)
mapGroup     = 0x02??????  -- [TBD] (8-bit)
facing       = 0x02??????  -- [TBD] (8-bit)
```

### Dynamic Offsets (if applicable)

```lua
-- Pointer addresses in IWRAM
saveBlock1Ptr = 0x03??????  -- [TBD]

-- Offsets from SaveBlock1 base
playerX_offset      = 0x????  -- [TBD]
playerY_offset      = 0x????  -- [TBD]
mapId_offset        = 0x????  -- [TBD]
mapGroup_offset     = 0x????  -- [TBD]
facing_offset       = 0x????  -- [TBD]
```

---

## Validation Test Results

### Test 1: Movement Validation
Date: [TBD]

| Action | Expected | Actual | Result |
|--------|----------|--------|--------|
| Move UP | Y decreases | [TBD] | ✅ / ❌ |
| Move DOWN | Y increases | [TBD] | ✅ / ❌ |
| Move LEFT | X decreases | [TBD] | ✅ / ❌ |
| Move RIGHT | X increases | [TBD] | ✅ / ❌ |

### Test 2: Map Change Validation
Date: [TBD]

| Action | MapID Before | MapID After | MapGroup Before | MapGroup After | Result |
|--------|--------------|-------------|-----------------|----------------|--------|
| Enter building | [TBD] | [TBD] | [TBD] | [TBD] | ✅ / ❌ |
| Exit building | [TBD] | [TBD] | [TBD] | [TBD] | ✅ / ❌ |
| Change route | [TBD] | [TBD] | [TBD] | [TBD] | ✅ / ❌ |

### Test 3: Facing Direction Validation
Date: [TBD]

| Direction | Expected Value | Actual Value | Result |
|-----------|----------------|--------------|--------|
| Down | 1 | [TBD] | ✅ / ❌ |
| Up | 2 | [TBD] | ✅ / ❌ |
| Left | 3 | [TBD] | ✅ / ❌ |
| Right | 4 | [TBD] | ✅ / ❌ |

### Test 4: Persistence Test (for static offsets)
Date: [TBD]

1. Read values: X=[TBD] Y=[TBD] Map=[TBD]:[TBD]
2. Close mGBA, reopen, load save
3. Read values: X=[TBD] Y=[TBD] Map=[TBD]:[TBD]
4. **Result:** ✅ Values match (Static) / ❌ Values different (Dynamic)

---

## Implementation in Code

### Files Modified

- `config/run_and_bun.lua` - Memory offsets configuration
- `client/hal.lua` - [Modified if dynamic] / [No changes if static]
- `client/main.lua` - [Modified for ROM detection] / [No changes needed]

### Changes to HAL (if dynamic mode)

**File:** `client/hal.lua`

[DOCUMENT ANY CHANGES MADE HERE]

---

## Known Limitations

### Current Implementation
- [ ] PlayerX, PlayerY, MapID, MapGroup, Facing - ✅ Working / ❌ Not found
- [ ] Camera X/Y - ⏳ Not yet searched
- [ ] Player name - ⏳ Not yet searched
- [ ] Player sprite - ⏳ Not yet searched
- [ ] Movement state (walk/run/bike) - ⏳ Not yet searched

### Future Work
- Find camera offsets for accurate ghost rendering (Phase 2)
- Find player sprite ID for correct visual representation (Phase 2)
- Find battle flag for warp mode constraints (Phase 3)

---

## ROM-Specific Notes

### Run & Bun Differences from Emerald

[DOCUMENT ANY OBSERVATIONS ABOUT HOW RUN & BUN DIFFERS]

Examples:
- Map structure appears different: [DETAILS TBD]
- SaveBlock layout modified: [DETAILS TBD]
- Additional data structures: [DETAILS TBD]

---

## Scanning Session Notes

### Session 1: [DATE TBD]

**Objective:** [e.g., Find PlayerX offset]

**Process:**
1. [STEP BY STEP NOTES]
2. [WHAT WORKED]
3. [WHAT DIDN'T WORK]

**Result:** [SUCCESS/FAILURE + DETAILS]

---

### Session 2: [DATE TBD]

[REPEAT FOR EACH MAJOR SCANNING SESSION]

---

## Troubleshooting

### Issues Encountered

#### Issue 1: [TITLE TBD]
- **Problem:** [DESCRIPTION]
- **Solution:** [WHAT FIXED IT]

---

## Appendix: Scan Commands Used

### Commands that worked:
```lua
-- [PASTE ACTUAL COMMANDS THAT SUCCESSFULLY FOUND OFFSETS]
```

### Commands that didn't work:
```lua
-- [PASTE COMMANDS THAT FAILED, FOR FUTURE REFERENCE]
```

---

## Sign-off

- [ ] All 5 critical offsets found and validated
- [ ] Config file updated with correct addresses
- [ ] HAL modified (if needed for dynamic mode)
- [ ] ROM detection added to main.lua (if needed)
- [ ] All tests pass (movement, map changes, facing)
- [ ] Documentation complete

**Completed by:** [YOUR NAME]
**Date:** [DATE]
**Verification:** Offsets tested with `scripts/validate_offsets.lua` ✅

---

**Next Phase:** Phase 1 - TCP Network Implementation
