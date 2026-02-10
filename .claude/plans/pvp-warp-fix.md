# Plan: Eliminate Golden State from Warp System

## Analysis: Why Was the Golden State Needed?

The golden state was a **workaround for an assumed problem that likely doesn't exist**. The concern was that calling `triggerMapLoad()` (setting callback2 = CB2_LoadMap) during normal gameplay — when the game is running CB2_Overworld — would crash because the game state isn't "clean" for a map load.

**But this concern is overblown.** In pokeemerald, the normal warp path is:
1. Player steps on door/warp tile
2. Game calls `SetWarpDestination()` to write sWarpDestination
3. Game sets callback2 = CB2_LoadMap via `DoWarp()`
4. CB2_LoadMap executes, loading the new map

The game itself transitions from CB2_Overworld to CB2_LoadMap all the time — from scripts, menus, teleport, escaping battles, etc. The existing `HAL.triggerMapLoad()` already handles the key preparations:
- NULL callback1 (stops CB1_Overworld interference)
- NULL savedCallback
- Clear interrupt callbacks (VBlank/HBlank/VCount/Serial)
- Zero gMain.state (CB2_LoadMap switch starts from case 0)
- Set callback2 = CB2_LoadMap

This replicates what the game does internally. The golden state was insurance that turned out to be unnecessary overhead.

**The only real requirement is having sWarpDestination's address**, because CB2_LoadMap reads the destination from there (not from SaveBlock1->location directly — ApplyCurrentWarp copies sWarpDestination into SaveBlock1->location).

## Boot-Time sWarpDestination Problem

The scanner (`HAL.findSWarpData()`) works by matching the 8-byte pattern of SaveBlock1->location in low EWRAM. This works at boot because:
- The game's initial load (title screen → save load → overworld) writes sWarpDestination before entering the overworld
- By the time the Lua script's frame callbacks run, sWarpDestination already contains valid data matching SaveBlock1->location

The current code already tries this on the first frame (`trackCallback2` first call, line 656-661). If the game is past initial load, it scans immediately.

**Edge case**: Script loaded during initial title screen before any save is loaded. sWarpDestination may be zeroed. Solution: defer scan until data is non-zero (already handled — `findSWarpData` skips if both words are 0).

## Plan

### 1. Changes to `hal.lua`

#### KEEP (unchanged):
- `HAL.findSWarpData()` — still needed to locate sWarpDestination at runtime
- `HAL.writeWarpData()` — writes destination to sWarpDestination + SaveBlock1
- `HAL.triggerMapLoad()` — triggers CB2_LoadMap directly (this IS the new primary method)
- `HAL.blankScreen()` — visual smoothness before warp
- `HAL.readCallback2()` / `HAL.isWarpComplete()` — track warp completion
- `HAL.saveGameData()` / `HAL.restoreGameData()` — still needed for return warp (preserving progression)
- `HAL.hasSWarpData()` — checks if address was found
- `HAL.readInBattle()` — battle state tracking

#### REMOVE:
- `HAL.captureGoldenState()` — no longer needed
- `HAL.loadGoldenState()` — no longer needed
- `HAL.hasGoldenState()` — no longer needed
- `goldenWarpState` variable — no longer needed
- `HAL.setupWarpWatchpoint()` — watchpoint was only needed for golden state capture timing
- `HAL.checkWarpWatchpoint()` — same reason
- `warpWatchpointId`, `warpWatchpointFired` variables — same reason
- Golden state capture logic inside `HAL.trackCallback2()` — remove the `goldenWarpState` branches

#### MODIFY `HAL.trackCallback2()`:
Simplify to only track sWarpData auto-calibration:
- On first call: try `findSWarpData()` if game is not in loading state
- On CB2_LoadMap → non-CB2_LoadMap transition: re-scan sWarpData
- Remove all golden state capture logic
- Remove `skipGoldenCapture` parameter (no longer relevant)

#### ADD `HAL.performDirectWarp(mapGroup, mapId, x, y)`:
New convenience function that combines the full direct warp sequence:
```lua
function HAL.performDirectWarp(mapGroup, mapId, x, y)
  if not HAL.hasSWarpData() then
    -- Try one more scan
    HAL.findSWarpData()
    if not HAL.hasSWarpData() then
      return false, "sWarpData not found"
    end
  end
  HAL.blankScreen()
  HAL.writeWarpData(mapGroup, mapId, x, y)
  HAL.triggerMapLoad()
  return true
end
```

### 2. Changes to `main.lua`

#### State changes:
- Remove `warpPhase = "waiting_door"` — no longer exists
- Keep all other phases: `"loading"`, `"waiting_party"`, `"in_battle"`, `"returning"`, `"loading_return"`

#### Initialize function:
- Remove `HAL.setupWarpWatchpoint()` call
- Keep `HAL.findSWarpData()` call (still needed for boot-time calibration)

#### Main update loop changes:

**Remove** (lines 486-500):
- `HAL.trackCallback2(State.inputsLocked)` call — simplify to just sWarpData tracking
- `HAL.checkWarpWatchpoint()` block — no longer needed
- Replace with: `HAL.trackCallback2()` (no parameter)

**Remove** (lines 517-546):
- Entire `State.warpPhase == "waiting_door"` block — no longer needed

**Remove** (lines 448-469):
- The "waiting for door" overlay drawing — no longer needed

**Modify** duel_warp handler (lines 833-910):
Replace the golden state branch + door fallback with direct warp:

```
-- New duel_warp handler:
1. Save origin position for return
2. Try HAL.performDirectWarp(coords)
3. If success → set phase "loading", lock inputs, set timeout
4. If fails (sWarpData not found) →
   a. Log warning
   b. Set warpPhase = nil (abort gracefully)
   c. Notify user via overlay that warp failed
   d. Try findSWarpData in background (will work after next natural map change)
```

**Modify** returning phase (lines 680-716):
Replace golden state hijack with direct warp:

```
-- New return warp:
1. Save current game data (SaveBlock1)
2. HAL.performDirectWarp(duelOrigin) -- direct warp to origin
3. Restore game data (to preserve progression gained during battle)
   NOTE: restoreGameData must happen AFTER the warp completes (when CB2_Overworld is active),
   because CB2_LoadMap reads from SaveBlock1 during loading. If we restore before loading,
   we overwrite the origin destination in SaveBlock1->location.
4. Actually... reconsider:
   - writeWarpData already writes the origin destination to both sWarpDestination AND SaveBlock1->location
   - restoreGameData would overwrite SaveBlock1->location with the DUEL ROOM location (old data)
   - Solution: save game data, do warp, then restore game data AFTER warp completes
   - But: the restored SaveBlock1->location will have the duel room coords, not origin coords
   - This is fine because the player is already at the origin map by then, and the next save will update it

   Wait, this is wrong. Let me re-think.

   The issue with return warp + saveGameData/restoreGameData:
   - Before duel: player is at OriginMap (SaveBlock1->location = OriginMap)
   - Warp to duel room: SaveBlock1->location = DuelRoom
   - During battle: player earns XP, items, etc. — these modify SaveBlock1 fields BEYOND location
   - Return warp: we want to go back to OriginMap AND keep all progression

   With golden state approach (old):
   1. saveGameData() — captures SaveBlock1 (location=DuelRoom, but has battle progression)
   2. loadGoldenState() — reset entire emulator to mid-warp state
   3. restoreGameData() — write back SaveBlock1 (with progression)
   4. writeWarpData(origin) — overwrite sWarpDestination AND SaveBlock1->location with origin
   5. CB2_LoadMap runs — copies sWarpDestination to SaveBlock1->location (origin)

   With direct approach (new):
   1. saveGameData() — captures SaveBlock1 (location=DuelRoom, progression intact)
   2. writeWarpData(origin) — overwrites sWarpDestination AND SaveBlock1->location+pos with origin
   3. triggerMapLoad() — CB2_LoadMap runs, copies sWarpDestination to SaveBlock1->location (origin)
   4. Wait for warp complete
   5. restoreGameData() — writes back SaveBlock1 (this OVERWRITES location with DuelRoom!)
   6. Write origin coords again to SaveBlock1->location after restore

   Alternatively:
   1. Don't save/restore game data at all for return — progression is already in SaveBlock1
   2. Just do performDirectWarp(origin)

   Actually, WHY did we need saveGameData/restoreGameData?
   - The golden state approach loaded a FULL EMULATOR STATE from a snapshot
   - This replaced ALL of WRAM, including SaveBlock1, with the snapshot's data
   - saveGameData preserved SaveBlock1 across the state load

   With direct warp, we DON'T replace WRAM! We just write sWarpDestination + trigger CB2_LoadMap.
   SaveBlock1 stays intact. Progression is preserved automatically.

   **Conclusion: saveGameData/restoreGameData is NOT needed for direct warp!**
   The golden state approach needed it because it replaced all WRAM. Direct warp doesn't touch WRAM beyond sWarpDestination and gMain fields.
```

**CRITICAL INSIGHT**: With direct warp, `saveGameData()`/`restoreGameData()` is **NOT needed** at all. The golden state approach loaded a full emulator state that wiped WRAM. Direct warp only writes to sWarpDestination (8 bytes) and gMain fields (< 32 bytes). SaveBlock1 remains untouched, preserving all progression automatically.

### 3. Changes to `config/run_and_bun.lua`

No changes needed. The config already has all necessary addresses:
- `warp.callback2Addr`, `warp.cb2LoadMap`, `warp.cb2Overworld` — used by triggerMapLoad/isWarpComplete
- `warp.gMainStateOffset` — used by triggerMapLoad
- `warp.sWarpDataAddr = nil` — auto-detected at runtime (unchanged)

### 4. Boot-Time Initialization Sequence

```
initialize():
  1. detectROM() → load config
  2. HAL.init(config)
  3. HAL.findSWarpData()  -- Try immediate scan (works if game loaded from save)
  4. Render.init(), Sprite.init(), etc.
  5. Network connect

First frame:
  HAL.trackCallback2() → if sWarpData not yet found AND game is past loading, retry scan

After any natural map change:
  HAL.trackCallback2() detects CB2_LoadMap→CB2_Overworld transition → auto-scans sWarpData
  Also: main.lua line 1064 calls HAL.findSWarpData() on map change
```

### 5. New Duel Warp Flow (Step by Step)

```
1. Player A presses A near ghost → duel_request to server
2. Player B accepts → server sends duel_warp to both players
3. Each player receives duel_warp message:
   a. Save duelOrigin = current position
   b. Set duelPending = {coords, isMaster}
   c. Call HAL.performDirectWarp(coords.mapGroup, coords.mapId, coords.x, coords.y)
      - If sWarpData found:
        - HAL.blankScreen() — fade to black
        - HAL.writeWarpData(dest) — write sWarpDestination + SaveBlock1
        - HAL.triggerMapLoad() — set gMain for CB2_LoadMap
      - If sWarpData NOT found:
        - Log error, abort warp gracefully
        - Send duel_cancelled to server (so opponent isn't stuck)
   d. Set warpPhase = "loading", inputsLocked = true, timeout = 300 frames (5s)
4. Wait for CB2_Overworld (HAL.isWarpComplete()):
   a. Re-scan sWarpData (for future warps)
   b. Send local party data
   c. Transition to warpPhase = "waiting_party"
5. On receiving opponent party:
   a. Inject enemy party
   b. Start battle
   c. Transition to warpPhase = "in_battle"
6. Battle runs (unchanged)
7. Battle ends → warpPhase = "returning"
```

### 6. Return Warp Flow (Step by Step)

```
1. Battle finishes → warpPhase = "returning"
2. Call HAL.performDirectWarp(duelOrigin.mapGroup, duelOrigin.mapId, duelOrigin.x, duelOrigin.y)
   - blankScreen + writeWarpData + triggerMapLoad
   - NO saveGameData/restoreGameData needed (direct warp preserves WRAM)
3. Set warpPhase = "loading_return", timeout = 300 frames
4. Wait for HAL.isWarpComplete()
5. On complete:
   - Clean up all duel state (warpPhase=nil, duelPending=nil, etc.)
   - inputsLocked = false
   - Clear occlusion cache
   - Re-scan sWarpData
```

### 7. Edge Cases and Error Recovery

| Edge Case | Handling |
|-----------|----------|
| **sWarpData not found at duel time** | Abort warp gracefully, log warning. sWarpData will be found after next natural map change. Send duel_cancelled. |
| **Warp timeout (5 seconds)** | Force unlock inputs, clear duel state, log warning. Same as current behavior. |
| **Disconnect during warp** | Cancel duel (current behavior, unchanged). |
| **Disconnect during battle** | Trigger return warp (current behavior, unchanged). |
| **Duel during dialogue/menu** | triggerMapLoad NULLs callback1 and sets CB2_LoadMap, which should override any menu state. The game engine handles this — CB2_LoadMap doesn't care what was running before, it reinitializes everything from scratch. |
| **Duel during battle** | inBattle tracking should prevent duel trigger (duel.lua proximity check won't fire in battle rooms). If somehow triggered, the direct warp will still work (CB2_LoadMap overrides CB2_BattleMain). |
| **Duel during another warp (transition)** | warpPhase is set, so new duel_warp messages are ignored (State.duelPending already set). |
| **Return warp fails (sWarpData lost)** | sWarpData should never be lost (it's cached). If somehow nil, performDirectWarp retries findSWarpData. If still fails, force unlock and log error — player is stuck in duel room but can save and restart. |
| **Script reload during duel** | Fresh state = no duelPending. Player is in duel room but system is clean. They'd need to warp out manually (save/restart). Same as current behavior. |

### 8. What to Keep vs Remove from Golden State System

#### KEEP:
- `HAL.findSWarpData()` — core scanner, needed to locate sWarpDestination
- `HAL.writeWarpData()` — writes destination
- `HAL.triggerMapLoad()` — triggers the map load
- `HAL.blankScreen()` — visual polish
- `HAL.isWarpComplete()` / `HAL.readCallback2()` — completion detection
- `HAL.trackCallback2()` — simplified (sWarpData tracking only)
- `HAL.hasSWarpData()` — status check
- `sWarpDataOffset` variable — cached scanner result
- `prevTrackedCb2` variable — for transition detection

#### REMOVE:
- `goldenWarpState` variable
- `HAL.captureGoldenState()`
- `HAL.loadGoldenState()`
- `HAL.hasGoldenState()`
- `HAL.setupWarpWatchpoint()`
- `HAL.checkWarpWatchpoint()`
- `warpWatchpointId` variable
- `warpWatchpointFired` variable
- `HAL.saveGameData()` — not needed with direct warp (WRAM preserved)
- `HAL.restoreGameData()` — not needed with direct warp (WRAM preserved)
- `SAVEBLOCK1_BASE` / `SAVEBLOCK1_WORDS` constants — no longer used
- `warpPhase == "waiting_door"` logic in main.lua
- "Walk through any door" overlay UI in main.lua
- Golden state capture in watchpoint handler in main.lua
- `skipGoldenCapture` parameter from `trackCallback2()`

### Summary of Simplification

**Before** (golden state):
- duel_warp → save game data → load golden state → restore game data → write warp → wait
- Fallback: waiting_door → walk through door → capture golden state → then do above
- Return: save game data → load golden state → restore game data → write origin → wait

**After** (direct warp):
- duel_warp → blank screen → write warp → trigger map load → wait
- No fallback needed (sWarpData found at boot or after first natural map change)
- Return: blank screen → write origin → trigger map load → wait

Lines of code removed: ~120+ (golden state functions, watchpoint system, door fallback, save/restore game data)
Lines of code added: ~15 (performDirectWarp convenience function)
Net reduction: ~100+ lines, much simpler state machine.
