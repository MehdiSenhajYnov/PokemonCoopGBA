---
name: Auto
description: Autonomous test-driven development loop. Analyzes a problem, fixes code, runs mGBA tests, reads results, and iterates until tests pass. Use when you want Claude to autonomously fix and validate code changes.
---

# Auto - Autonomous Test-Driven Development

You are entering **autonomous test-driven development mode**. The user has described a problem or task. You will work in a loop: analyze, fix, test, read results, repeat — **until the task is fully accomplished**. There is NO iteration limit. You keep going until it works. The user will manually interrupt you if they want you to stop.

The user's problem description is provided as the argument to this skill: `$ARGUMENTS`

---

## RULES

1. **NEVER STOP until the task is done.** There is no iteration limit. Keep looping until all tests pass and the problem is solved. If you've been going for a while, that's fine — the user values results over token cost.
2. **Always read code before modifying it.** Never guess at file contents.
3. **Never skip the test step.** Every code change MUST be validated by running the test framework.
4. **Create targeted tests** for the specific problem you're fixing if the existing suites don't cover it.
5. **Use parallel subagents** (Explore, general-purpose) to speed up analysis when investigating multiple files.
6. **Report progress** to the user at each iteration: brief summary of what you changed and what tests say.
7. **If stuck on the same failure for 3+ iterations**, change strategy radically: re-read the decomp sources in `refs/`, search the web for similar issues, try a completely different approach. Do NOT keep hammering the same fix.
8. **If a test itself is wrong** (testing the wrong thing, wrong expected value), fix the test — don't contort the code to match a bad test.

---

## ITERATION LOOP

Repeat these steps indefinitely until success:

### Step 1: Analyze (first iteration, or when changing strategy)

- Read the relevant source files in `client/`, `config/`, `server/` to understand the problem
- Read existing test suites in `scripts/testing/suites/` to see what's already tested
- Read `CLAUDE.md` and memory files for known addresses, lessons learned, and architecture context
- Check `refs/pokeemerald-expansion/` for decomp source when dealing with game internals
- Identify the root cause and plan your fix

### Step 2: Fix the Code

- Edit the relevant source files to fix the identified issue
- If the fix touches memory addresses, cross-reference with `config/run_and_bun.lua` and `MEMORY.md`
- If the fix involves ROM offsets, remember: EWRAM offsets = absolute - 0x02000000, IWRAM = absolute - 0x03000000, cart0 = THUMB address with bit 0 cleared

### Step 3: Create/Update Tests (if needed)

If the existing test suites in `scripts/testing/suites/` don't cover the behavior you're fixing:

1. Create a new suite file in `scripts/testing/suites/` (e.g., `my_fix.lua`)
2. Register it in `scripts/testing/run_all.lua` by adding `require("my_fix")`
3. Follow the existing suite pattern:
```lua
local Runner = require("runner")

Runner.suite("suite_name", function(t)
  t.test("test_name", function()
    -- Use t.assertEqual, t.assertTrue, t.assertRange, t.assertNotNil, t.assertBytes
    -- Use emu.memory.wram (EWRAM), emu.memory.iwram (IWRAM), emu.memory.cart0 (ROM)
  end)
  t.screenshot("description")
end)

-- For multi-frame tests:
Runner.asyncSuite("async_name", function(t)
  -- Setup...
  t.waitFrames(180, function()
    t.test("after_wait", function()
      -- Assertions here
    end)
    t.done()  -- REQUIRED to end async suite
  end)
end)
```

### Step 4: Run the Test Framework

Execute this PowerShell sequence via Bash tool:

```powershell
powershell -Command "Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1; Start-Process 'mgba/mGBA.exe' -ArgumentList '--script','scripts/testing/run_all.lua','rom/Pokemon RunBun.gba'; Start-Sleep -Seconds 20; Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue"
```

**IMPORTANT**:
- This requires **save state slot 1** to exist in mGBA (overworld, not in battle)
- Wait 20 seconds for tests to complete (120 frames stabilization + test execution + async suites)
- If the async `battle_trigger` suite is enabled, wait 25 seconds instead

### Step 5: Read and Analyze Results

1. **Read `test_results.json`** — structured JSON with all test outcomes:
   ```json
   {
     "status": "complete",
     "timestamp": "2026-02-06 15:30:00",
     "duration_ms": 8500,
     "summary": { "total": 45, "passed": 43, "failed": 2 },
     "suites": [
       {
         "name": "memory_addresses",
         "tests": [
           { "name": "playerX_readable", "pass": true, "details": "" },
           { "name": "callback2_nonzero", "pass": false, "details": "Expected true, got false" }
         ],
         "passed": 19, "failed": 1
       }
     ],
     "screenshots": ["001_initial_state.png", "002_fail_callback2_nonzero.png"]
   }
   ```

2. **Read failure screenshots** in `test_screenshots/` — especially any `fail_*.png` files, they show the game state at the moment of failure. Use the Read tool on PNG files to visually inspect them.

3. **Check `status` field**:
   - `"complete"` — tests ran successfully, check summary
   - `"started"` — mGBA crashed or tests didn't finish (increase wait time or investigate script error)
   - `"error"` — save state load failed or framework error

### Step 6: Evaluate and Loop

- **If `summary.failed == 0` AND the original problem is solved**: Go to SUCCESS below.
- **If tests failed**:
  - Analyze which tests failed and why (read the `details` field)
  - Look at failure screenshots for visual clues
  - Go back to **Step 2** with new understanding
- **If status is not "complete"**:
  - The framework may have crashed. Check if your code changes broke Lua syntax (missing `end`, bad require path)
  - Fix and retry
- **If same test keeps failing after 3 attempts with different fixes**:
  - STOP and re-analyze from scratch. Read the decomp in `refs/pokeemerald-expansion/`. Search the web. Try a fundamentally different approach.
  - Do NOT keep trying small variations of the same fix.

---

## ON SUCCESS (all tests pass, task accomplished)

Report to the user:
1. **What was the problem** (root cause analysis)
2. **What you changed** (list of files modified with brief descriptions)
3. **Test results summary** (X/X passed across Y suites)
4. **Number of iterations** it took
5. **Any new test suites created**
6. **Update MEMORY.md** if you learned something new about the codebase (addresses, gotchas, patterns)

---

## REFERENCE: Project Paths

| Path | Description |
|------|-------------|
| `mgba/mGBA.exe` | mGBA emulator executable |
| `rom/Pokemon RunBun.gba` | Target ROM |
| `scripts/testing/run_all.lua` | Test framework entry point |
| `scripts/testing/runner.lua` | Test runner engine |
| `scripts/testing/assertions.lua` | Assertion library |
| `scripts/testing/suites/` | Test suite directory (memory, rom_patches, warp, network, battle) |
| `test_results.json` | Test output (project root) |
| `test_screenshots/` | Screenshot output directory |
| `config/run_and_bun.lua` | ROM profile with all memory addresses |
| `client/` | Main client code (main.lua, hal.lua, battle.lua, etc.) |
| `server/server.js` | Node.js relay server |
| `refs/pokeemerald-expansion/` | Decomp source (structs, headers, constants) |
| `refs/pokemon-run-bun-exporter/` | Community-validated addresses |

## REFERENCE: Memory Offset Rules

- **EWRAM** (`emu.memory.wram`): offset = absolute_address - 0x02000000
  - Example: 0x0202064C → offset 0x2064C (NOT 0x064C!)
- **IWRAM** (`emu.memory.iwram`): offset = absolute_address - 0x03000000
  - Example: 0x030030FC → offset 0x30FC
- **cart0/ROM** (`emu.memory.cart0`): offset = THUMB_address & ~1
  - Example: 0x0800A4B1 → offset 0x00A4B0
- **`emu.memory.ewram` DOES NOT EXIST** — always use `emu.memory.wram`
