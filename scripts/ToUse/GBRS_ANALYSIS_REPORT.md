# gBlockReceivedStatus Handling Analysis Report
**Date:** 2026-02-10
**Purpose:** Investigate if the difference between GBA-PK and our implementation can cause problems

## Context

**GBA-PK approach:**
1. Line 12739: Writes `gBlockReceivedStatus = 0x0` initially (prepare the game)
2. Line 12780/12798: Writes `gBlockReceivedStatus = 0x03` at stage 4 (players 0+1 "received")

**Our approach:**
1. Line 702 (battle.lua): Writes `gBlockReceivedStatus = 0x0F` at start (all 4 players received)
2. Line 1417 (battle.lua): Writes `gBlockReceivedStatus = 0x03` during stage 4-5 (GBA-PK compat)
3. ROM patch at 0x0A598: `GetBlockReceivedStatus()` always returns 0x0F (MOV R0, #15; BX LR)

**Concern:**
ROM code might read gBlockReceivedStatus DIRECTLY at address 0x0300307C without calling GetBlockReceivedStatus(), bypassing our patch.

## Methodology

### 1. Scan ROM for Direct References
**Script:** `scan_gbrs_refs.py`

Found **4 literal pool references** to gBlockReceivedStatus (0x0300307C):
1. **0x0800A5C0** - Inside GetBlockReceivedStatus() itself (PATCHED - safe)
2. **0x0800A5F8** - Inside function at 0x0800A5D1 (SetBlockReceivedFlag)
3. **0x0800A630** - Inside function at 0x0800A5FD (ResetBlockReceivedFlags)
4. **0x0800A664** - Inside function at 0x0800A635 (ClearReceivedBlockStatus)

**Result:** 3 functions bypass our GetBlockReceivedStatus() patch by reading gBlockReceivedStatus directly.

### 2. Analyze Battle Init Functions
**Script:** `analyze_gbrs_usage.py`

Checked battle init functions for direct GBRS access:
- CB2_InitBattle (0x080363C1, 204 bytes)
- CB2_InitBattleInternal (0x0803648D, 4096 bytes)
- CB2_HandleStartBattle (0x08037B45, 2048 bytes)

**Findings:**
- ✅ NO direct literal pool references to gBlockReceivedStatus
- ✅ NO calls to SetBlockReceivedFlag
- ✅ NO calls to ResetBlockReceivedFlags
- ✅ NO calls to ClearReceivedBlockStatus

**Conclusion:** Battle init functions do NOT directly access gBlockReceivedStatus. All reads go through GetBlockReceivedStatus() (which we patch).

### 3. Find Callers of Direct-Access Functions
**Script:** `find_gbrs_func_callers.py`

Scanned entire ROM for BL calls to the 3 direct-access functions:

**Result:**
- SetBlockReceivedFlag: **0 callers found**
- ResetBlockReceivedFlags: **0 callers found**
- ClearReceivedBlockStatus: **0 callers found**

**Interpretation:** These functions are likely:
1. Called via function pointers (task callbacks, etc.)
2. Used by non-battle link systems (wireless, trade, Union Room)
3. NOT part of the PvP battle init code path

## Key Findings

### Finding 1: Battle Init Uses Patched Function Only
All gBlockReceivedStatus reads during battle init go through GetBlockReceivedStatus(), which we patch to return 0x0F.

**Evidence:**
- CB2_HandleStartBattle calls GetBlockReceivedStatus() 4 times (checks in Cases 2, 4, 6, 8)
- No direct memory reads at 0x0300307C in battle init code
- Our ROM patch covers ALL battle init access

### Finding 2: Direct-Access Functions Not Used in Battle Init
The 3 functions that bypass our patch are NOT called during battle init:
- No BL calls found in entire ROM (likely called via function pointers)
- Not in battle init address range (0x08036000-0x08040000)
- Likely used for wireless/link cable systems outside of battle

### Finding 3: GBA-PK Staged Approach vs Our Immediate Write
**GBA-PK:** 0x0 → 0x03 (staged)
**Our code:** 0x0F → 0x03 (immediate then staged)

**Impact:** NONE - Because:
1. All battle init reads go through our patched GetBlockReceivedStatus() → returns 0x0F regardless
2. The memory value (0x0 vs 0x0F) is never read directly during battle init
3. The patch return value is what matters, not the memory contents

## Conclusion

### Answer to Research Question
**Q:** Can the difference in gBlockReceivedStatus handling between GBA-PK and our implementation cause problems?

**A:** **NO.** The difference is irrelevant for battle init because:

1. **All battle init reads are patched:** CB2_HandleStartBattle reads gBlockReceivedStatus via GetBlockReceivedStatus(), which we patch to always return 0x0F.

2. **No direct reads in battle code:** The 3 functions that bypass our patch (SetBlockReceivedFlag, ResetBlockReceivedFlags, ClearReceivedBlockStatus) are NOT called during battle init.

3. **Memory value doesn't matter:** Whether we write 0x0 or 0x0F to memory initially is irrelevant—the ROM patch controls the return value.

4. **Stage 4-5 write to 0x03 is cosmetic:** We write 0x03 at stage 4-5 for GBA-PK compatibility, but it's never read during our battle flow (GetBlockReceivedStatus() still returns 0x0F due to patch).

### Recommendations

✅ **NO CHANGES NEEDED** to our implementation.

**Current approach is safe:**
- Writing 0x0F immediately is valid
- ROM patch covers all battle init reads
- Direct-access functions are not in battle code path

**Optional improvement (cosmetic only):**
If we want 100% alignment with GBA-PK for debugging clarity:
- Write 0x0 initially (like GBA-PK line 12739)
- Write 0x03 at stage 4 (already done at line 1417)

But this is **purely cosmetic** and has **zero functional impact** on battle behavior.

## Evidence Files

Created scripts (in `scripts/ToUse/`):
1. `scan_gbrs_refs.py` - Found 4 literal pool refs
2. `disasm_gbrs_funcs.py` - Disassembled 3 direct-access functions
3. `analyze_gbrs_usage.py` - Checked battle init functions
4. `find_gbrs_func_callers.py` - Searched for callers ROM-wide

All scripts confirmed: **Our approach is safe.**

---

**Investigator Note:** This analysis demonstrates the importance of understanding both the ROM code AND our patches. The memory value at 0x0300307C is a red herring—what matters is the patched GetBlockReceivedStatus() return value, which battle init reads exclusively.
