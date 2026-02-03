# Memory Scanning Scripts for Pokémon Run & Bun

This directory contains Lua scripts for discovering memory offsets in Pokémon Run & Bun using mGBA's built-in Lua scripting console.

---

## Prerequisites

- **mGBA 0.10.0+** with Lua scripting support
- **Pokémon Run & Bun ROM** (latest version)
- **Basic understanding** of memory addresses (optional but helpful)

---

## Quick Start Guide

### Step 1: Test Vanilla Offsets (5 minutes)

**Goal:** Check if Pokémon Emerald vanilla offsets work on Run & Bun

1. Open mGBA and load Pokémon Run & Bun
2. Open the scripting console: **Tools → Scripting**
3. Click **Load Script** and select `scan_vanilla_offsets.lua`
4. **OR** Copy-paste the entire contents of `scan_vanilla_offsets.lua` into the console
5. Press Enter to run
6. Move your character around in the game
7. Re-run the script and check if X/Y values change correctly

**If values change correctly:**
- ✅ Great! Vanilla offsets work. Skip to Step 4.

**If values are garbage or don't change:**
- ❌ Proceed to Step 2.

---

### Step 2: Manual Memory Scanning (30-60 minutes)

**Goal:** Find the actual memory addresses where player data is stored

1. Load `scan_wram.lua` into mGBA console
2. Note your current position in the game (count tiles from a reference point)
3. Estimate X coordinate: `tiles × 16` (e.g., 10 tiles = 160)
4. Run: `candidatesX = scanWRAM(160, 2)`
   - This scans all of GBA WRAM for the value 160 (16-bit)
5. Move right 5-10 tiles
6. Calculate new X: `new_tiles × 16`
7. Run: `candidatesX = rescan(candidatesX, newValue, 2)`
8. Repeat steps 5-7 until you have 1-5 candidates
9. Test each candidate: `watchAddress(0x02??????, 2)`
10. Repeat for Y, MapID, MapGroup, and Facing

**Sizes to use:**
- X, Y: `size = 2` (16-bit word)
- MapID, MapGroup, Facing: `size = 1` (8-bit byte)

---

### Step 3: Determine Static vs Dynamic (10 minutes)

**Goal:** Check if addresses are fixed or change between sessions

1. Note the addresses you found in Step 2
2. **Save a savestate** in mGBA (File → Save State)
3. Close mGBA completely
4. Reopen mGBA and load the savestate
5. Run `validate_offsets.lua` (after editing it with your found addresses)
6. Check if values still make sense

**If values are correct after reloading:**
- ✅ **Static offsets** - addresses don't change

**If values are garbage after reloading:**
- ❌ **Dynamic offsets** - proceed to Step 3b

---

### Step 3b: Find SaveBlock Pointers (Dynamic Mode Only)

**Goal:** Find the pointer that points to the player data structure

1. Load `find_saveblock_pointers.lua` into mGBA console
2. Run the script - it will scan IWRAM for pointers to WRAM
3. You'll get a list of candidate pointer addresses
4. Test each: `dumpStructure(0x03??????, 256)`
5. Look for your player X/Y coordinates in the hex dump
6. Once found, note:
   - The pointer address (in IWRAM, 0x03??????)
   - The offset from the pointed address to each data field

---

### Step 4: Configure and Validate (15 minutes)

**Goal:** Update the config file and test it

1. Open `config/run_and_bun.lua` in a text editor
2. Set `OFFSETS_DISCOVERED = true`
3. If static (Step 3): Fill in the `offsets` table with your addresses
4. If dynamic (Step 3b): Set `USE_DYNAMIC_POINTERS = true` and fill in pointer + offsets
5. Save the file
6. Edit `scripts/validate_offsets.lua` with your offsets
7. Run `validate_offsets.lua` in mGBA console
8. Run `startMonitor()` to see real-time values
9. Walk around, enter buildings, change directions - verify everything works
10. Run `stopMonitor()` when done

---

## Script Reference

### `scan_vanilla_offsets.lua`

Quick test to check if Pokémon Emerald vanilla offsets work on Run & Bun.

**Usage:**
```lua
-- Copy-paste entire script into mGBA console, then:
-- 1. Walk around
-- 2. Re-run script
-- 3. Check if X/Y change correctly
```

**Output:**
- Shows current values of all offsets
- Instructions on what to check

---

### `scan_wram.lua`

Comprehensive memory scanner for finding data in GBA WRAM.

**Functions:**

#### `scanWRAM(value, size)`
Scan entire WRAM for a specific value.
- `value`: The number to search for
- `size`: 1 (byte), 2 (word), 4 (dword)
- Returns: Table of addresses

**Example:**
```lua
-- Find X coordinate = 160
results = scanWRAM(160, 2)
```

#### `rescan(previousResults, newValue, size)`
Narrow down previous results by scanning for a new value.
- `previousResults`: Results from previous scan
- `newValue`: New value to search for
- `size`: Same as scanWRAM
- Returns: Filtered table of addresses

**Example:**
```lua
-- After moving right, X = 240
results = rescan(results, 240, 2)
```

#### `watchAddress(address, size)`
Monitor an address in real-time (displays on screen).
- `address`: Memory address to watch
- `size`: Read size

**Example:**
```lua
watchAddress(0x02024844, 2)
-- To stop: callbacks.remove(callbackId)
```

---

### `find_saveblock_pointers.lua`

Finds SaveBlock pointer addresses (for dynamic offset mode).

**Usage:**
```lua
-- Copy-paste entire script, it will automatically scan
-- Then test candidates:
dumpStructure(0x03005D8C, 256)
```

**Functions:**

#### `dumpStructure(ptrAddr, length)`
Dumps memory structure pointed to by a pointer.
- `ptrAddr`: Address of the pointer (IWRAM, 0x03??????)
- `length`: Number of bytes to dump (default 256)

**Output:**
- Hex dump of the structure
- Look for your X/Y coordinates to identify offsets

---

### `validate_offsets.lua`

Validates discovered offsets and provides real-time monitoring.

**Setup:**
1. Edit the `OFFSETS` table at the top with your addresses
2. Set `USE_DYNAMIC` if using SaveBlock pointers
3. If dynamic, fill in `SAVEBLOCK1_PTR` and `OFFSETS_DYNAMIC`

**Usage:**
```lua
-- Run once to validate
-- Output shows current values and validation result

-- Start real-time monitor
startMonitor()

-- Stop monitor
stopMonitor()
```

---

## Common Issues & Solutions

### Issue: "Too many matches" when scanning

**Solution:** Be more specific. Move further or scan with more precision.
```lua
-- Instead of scanning for X=160, move to an odd position
-- e.g., X=173 (fewer false positives)
results = scanWRAM(173, 2)
```

### Issue: "No matches found" when rescanning

**Possible causes:**
1. Coordinates didn't actually change (check in-game)
2. Wrong size (try size=1 instead of size=2)
3. Value stored differently than expected

**Solution:** Start a new scan from scratch.

### Issue: Values are always 0 or very large numbers

**Possible causes:**
1. Wrong address size (using read16 on a byte value, or vice versa)
2. Address is in a different memory region

**Solution:**
- For MapID, MapGroup, Facing: use `size = 1`
- For X, Y: use `size = 2`

### Issue: Dynamic pointers - dump shows garbage

**Solution:** The pointer address might be wrong. Try other candidates from `find_saveblock_pointers.lua`.

---

## Memory Layout Reference

### GBA Memory Regions

| Region | Address Range | Description |
|--------|---------------|-------------|
| IWRAM | 0x03000000 - 0x03007FFF | Internal RAM (pointers live here) |
| WRAM | 0x02000000 - 0x0203FFFF | Work RAM (player data lives here) |
| ROM | 0x08000000+ | ROM data (read-only) |

### Expected Data Sizes

| Data | Type | Size | Typical Range |
|------|------|------|---------------|
| PlayerX | uint16 | 2 bytes | 0 - 2048 |
| PlayerY | uint16 | 2 bytes | 0 - 2048 |
| MapID | uint8 | 1 byte | 0 - 255 |
| MapGroup | uint8 | 1 byte | 0 - 50 |
| Facing | uint8 | 1 byte | 0 - 4 |

### Facing Direction Values

| Value | Direction |
|-------|-----------|
| 0 | None |
| 1 | Down |
| 2 | Up |
| 3 | Left |
| 4 | Right |

---

## Tips for Efficient Scanning

1. **Start with X coordinate** - easiest to track by counting tiles
2. **Use savestates** - save before scanning to quickly retry
3. **Move significantly** - move 5-10 tiles between scans for clear changes
4. **Test in open areas** - avoid buildings/obstacles during initial scans
5. **Document as you go** - note addresses in `docs/RUN_AND_BUN.md` immediately
6. **Validate often** - use `watchAddress()` to confirm candidates early

---

## Workflow Summary

```
1. scan_vanilla_offsets.lua
   ├─ ✅ Works → Done! Fill config
   └─ ❌ Fails → Continue

2. scan_wram.lua
   ├─ scanWRAM(value, 2) → Move → rescan()
   ├─ Repeat until 1-5 candidates
   └─ watchAddress() to confirm

3. Check persistence
   ├─ ✅ Static → Fill config with addresses
   └─ ❌ Dynamic → Continue

4. find_saveblock_pointers.lua
   ├─ Find pointer candidates
   ├─ dumpStructure() to locate offsets
   └─ Fill config with pointer + offsets

5. validate_offsets.lua
   ├─ Edit with your offsets
   ├─ Run validation
   └─ startMonitor() to verify
```

---

## Documentation

After completing the scan, document your findings in:
- `config/run_and_bun.lua` - The actual offsets
- `docs/RUN_AND_BUN.md` - Detailed documentation of the process

---

## Need Help?

See the complete guide: `docs/MEMORY_GUIDE.md`

For task-specific instructions: `Tasks/todo/P0_00_MEMORY_OFFSET_DISCOVERY.md`

---

**Good luck with your memory scanning!**
