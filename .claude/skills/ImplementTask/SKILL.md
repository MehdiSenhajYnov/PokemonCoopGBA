---
name: ImplementTask
description: Implement a task from the Tasks/ directory. Handles codebase analysis, planning, implementation, code review, and documentation updates.
---

# ImplementTask - Implement a Task from Tasks/

Implement the task specified by the user: $ARGUMENTS

---

## Step 0: Parse arguments

Extract from `$ARGUMENTS`:
- **Task identifier**: a task name or partial match (e.g., `AUDIO_MICROFREEZE_FIX`, `microfreeze`, `CODE_OPTIMISATION 2.1 2.3`, `PHASE_9`)
- **Item filter** (optional): specific section/item numbers to implement (e.g., `2.1 2.3 3.5`). If present, ONLY implement those items — skip everything else.
- **Flags**: `--plan` or `-p` = stop after plan and wait for user approval

### Finding the task file:

Search in this order:
1. Exact match in `Tasks/` (e.g., `AUDIO_MICROFREEZE_FIX.md`)
2. Exact match in `Tasks/updates/*/` subdirectories
3. Case-insensitive partial match across both locations
4. If multiple matches or zero matches, list all available task files and ask the user to pick one

Once found, store the **full path** to the task file — you'll reference it throughout.

---

## Step 1: Read project context and task

1. **Read `CLAUDE.md`** — this contains the project's architecture, conventions, patterns, and constraints. Every implementation decision must be consistent with it.
2. Read the task file **completely** — every line
3. Build an inventory of actionable items:
   - Checkboxes: `- [ ]` (pending) vs `- [x]` (done — skip these)
   - Numbered fixes (e.g., `### 2.1 Ecriture non-atomique...`)
   - Sections with proposed code changes
4. If an **item filter** was given in Step 0, mark only those items as in-scope. Everything else is out-of-scope for this run.
5. Collect the **list of all files** mentioned in the task (paths in code blocks, "Fichier:" labels, file tables)

---

## Step 1.5: Research external APIs and documentation (MANDATORY)

**⚠️ CRITICAL — DO NOT SKIP THIS STEP.**

Before writing ANY code that uses an external API, library, or tool, you MUST research it first. Never assume you know how an API works — always verify against official documentation.

### Process:

1. **Identify all external APIs/tools** involved in the task:
   - mGBA Lua scripting API (canvas, callbacks, emu, console, etc.)
   - Node.js APIs (net, fs, etc.)
   - LuaSocket API
   - Any other library or tool

2. **For each API, do a web search and read the official docs**:
   - Use `WebSearch` to find the latest documentation
   - Use `WebFetch` to read the actual documentation pages thoroughly
   - Pay attention to **version differences** (e.g., mGBA 0.10 vs 0.11 have completely different APIs)
   - Look for **working examples** in official repos or community posts

3. **Verify specific function signatures**:
   - Don't guess parameter names, types, or return values
   - Don't assume an API exists — confirm it does in the docs
   - Check if the API requires a specific version of the tool/library

4. **Document findings** before proceeding:
   ```
   API RESEARCH:
   - [tool/library] version [X]: [function_name](params) → return_type — confirmed in [source_url]
   - [tool/library]: [feature] NOT available in version [Y], requires version [Z]
   - [tool/library]: working example found at [source_url]
   ```

### Key references for this project:
- **mGBA 0.11+ dev scripting API**: https://mgba.io/docs/dev/scripting.html (canvas, Painter, Image, CanvasLayer)
- **mGBA 0.10 stable scripting API**: https://mgba.io/docs/scripting.html (NO overlay support)
- **mGBA example scripts**: https://github.com/mgba-emu/mgba/tree/master/res/scripts
- **Node.js net module**: https://nodejs.org/api/net.html
- **LuaSocket**: http://w3.impa.br/~diego/software/luasocket/

### Why this matters:
- mGBA's Lua API is NOT standard Lua — it has its own objects (canvas, callbacks, emu, console)
- API functions change between versions (e.g., overlay drawing doesn't exist in 0.10)
- Guessing API calls leads to scripts that crash silently or don't work at all
- 10 minutes of research saves hours of debugging

---

## Step 2: Analyze complexity

Evaluate the in-scope items on these axes:

| Axis | Low | High |
|------|-----|------|
| **Files touched** | 1-2 files | 5+ files |
| **Cross-cutting** | Isolated change | Frontend + Backend + Types |
| **Dependencies** | Steps are independent | Steps depend on each other |
| **Risk** | Additive (new code) | Modifying hot paths / core logic |
| **Scope** | Single fix/feature | Multi-section implementation |

Assign a complexity level:
- **Simple** (mostly Low): implement directly
- **Medium** (mixed): implement sequentially, build-check between sections
- **Complex** (mostly High): break into phases, analyze in parallel, implement section by section

This complexity level determines the depth of Steps 3-5. Refer to it as `{COMPLEXITY}` below.

---

## Step 3: Analyze the codebase

**Goal:** Understand the CURRENT state of every file you'll touch, before writing any code.

### Simple:
Read the target files. Verify the task's code snippets and line numbers still match reality. Also read callers/dependents of any function you'll modify — even "simple" changes can break callers.

### Medium / Complex:
Launch **parallel Explore agents**, one per area of the codebase affected. Each agent must:

1. **Read every source file** referenced by the in-scope task items
2. **Verify task assumptions**: do the file paths, line numbers, function names, and code snippets in the task still match the actual code? Note every discrepancy.
3. **Read the surrounding context**: not just the target line — the whole function, the callers, the module. Understand WHY the code is the way it is.
4. **Find hidden dependencies**: if the task says "change struct X" → grep for every usage of X. If it says "modify function Y" → find every caller of Y. Report these.
5. **Detect conflicts**: will any proposed change break something the task doesn't mention?

### After agents return, compile ANALYSIS RESULTS:

```
ANALYSIS RESULTS:
- [file_path] : task says [X] at line N → actual code is [Y] at line M → DRIFT / MATCH / ALREADY DONE
- [file_path] : function Z is called by [A, B, C] → must update callers: YES / NO
- [file_path] : task item 2.3 is already implemented → SKIP
- Additional files not in task but need changes: [list]
```

This list feeds directly into Step 4.

---

## Step 4: Plan

### Simple:
No formal plan. Proceed to Step 5.

### Medium / Complex:

Using the analysis results from Step 3, build the implementation plan:

1. **Adapt to reality**: for every DRIFT found in Step 3, decide how to adjust the task's proposed fix to work with the current code
2. **Order the work** — respect dependency chains:
   - New crate/npm dependencies first (`Cargo.toml`, `package.json`)
   - Rust types/structs second
   - Backend logic third
   - TypeScript types fourth
   - Frontend stores/hooks fifth
   - Frontend components sixth
   - Wiring last (command registration in `main.rs`, event listeners)
3. **Group into sections**: each section = a set of related changes that can be build-checked together
4. **Mark verification points**: after which sections to run `cargo check` or `npx tsc --noEmit`
5. **Flag risks**: changes that could break existing behavior or deviate from the task

### If `--plan` or `-p` flag:
Present the full plan to the user and enter plan mode. **STOP and wait for approval.** Do not implement anything until the user approves.

### If no flag:
Proceed to Step 5.

---

## Step 5: Implement

### Before starting, create a git checkpoint:

```bash
git stash push -m "ImplementTask checkpoint before [TASK_NAME]" --include-untracked
git stash pop
# Now we have a clean reference point. If things go wrong, we can:
# git diff to see everything we changed
# git checkout -- . to rollback everything
```

If the working tree has uncommitted changes, warn the user and ask whether to proceed or stash first.

### Execution rules:

**For all complexity levels:**

- **Follow the task's intent** — implement what it describes
- **Respect CLAUDE.md conventions** — architecture decisions, patterns, and constraints from CLAUDE.md override the task if they conflict
- **Adapt code snippets from the task** to the actual current code. The task may have been written before recent changes. Use the task's code as the TARGET BEHAVIOR, but write code that fits the current codebase state (as determined in Step 3).
- **If the task provides exact fix code AND Step 3 confirmed it still matches**, use it directly
- **When the task gives direction but not exact code**, write code consistent with the existing style and patterns in the same file
- **New dependencies**: if the task requires a new crate or npm package, add it to `Cargo.toml` / `package.json` FIRST, then use it
- **If a task item is impossible** (code doesn't exist anymore, conflicting with another completed item), skip it and record why

**Do NOT:**
- Refactor code the task doesn't mention
- Add comments, docstrings, or type annotations beyond what the task specifies
- Change formatting of untouched code
- Create new files the task doesn't ask for

### Execution flow by complexity:

**Simple:**
- Edit the files directly, all at once

**Medium:**
- Implement one section at a time (as grouped in Step 4)
- After each section: `cargo check --manifest-path src-tauri/Cargo.toml` (Rust) or `npx tsc --noEmit` (TypeScript)
- If check fails → fix before moving on

**Complex — context refresh + recursive delegation:**

Before EACH section/phase:

1. **Re-read the task file** — previous sections may have changed your understanding
2. **Re-read every file you're about to modify** in this section — previous sections may have changed them. Your Step 3 analysis is now STALE for files touched by earlier sections. Get the fresh version.
3. **Re-evaluate the plan for this section** — does the approach from Step 4 still make sense given what the previous sections changed? Adjust if needed.

Then implement the section.

After EACH section:
- `cargo check` / `npx tsc --noEmit`
- If check fails → fix before moving on
- Update the CHANGES LOG
- **Produce a CONTEXT CHECKPOINT** (see below)

For independent sections that touch DIFFERENT files, implement them in parallel. NEVER let parallel agents edit the same file.

**Sub-task delegation:** If a single section is itself complex (5+ files, cross-cutting, high risk), delegate it to a Task agent. This agent must receive ALL of the following so it can work autonomously:
- The full task file content (or the relevant section extracted verbatim)
- The ANALYSIS RESULTS from Step 3 relevant to this section
- The full CHANGES LOG so far (so the agent knows what was already modified)
- The list of files it must NOT touch (owned by other sections)
- The relevant CLAUDE.md conventions for the area it's working on

**WAIT for the sub-agent to finish completely before continuing.** Never proceed to the next section while a sub-agent is still working. When it returns, merge its CHANGES LOG into yours and produce a CONTEXT CHECKPOINT.

### Rollback:

If at any point the implementation is fundamentally broken (wrong approach, cascading failures, 3+ build failures in a row on the same section):
1. **STOP implementing**
2. Run `git diff` to see all changes made
3. Run `git checkout -- .` to rollback ALL changes
4. Report to the user: what was attempted, why it failed, what needs to change in the task/approach

### CHANGES LOG:

Keep a running list of every file modified and what changed. Log by **function/block name**, not line numbers (line numbers shift as you edit).

```
CHANGES LOG:
- [file_path] > [function_name/struct_name/block] : [what was changed and why]
- [file_path] > [function_name/struct_name/block] : [what was changed and why]
...
```

### CONTEXT CHECKPOINT (Complex only):

After each section, produce a compact summary that captures the full current state. This keeps the critical information FRESH at the end of the context instead of buried in the middle.

```
=== CONTEXT CHECKPOINT after Section N ===
Task: [TASK_NAME] — [item filter if any]
Complexity: Complex
Sections done: [1, 2, 3] — Sections remaining: [4, 5]
Build status: cargo check PASS / npx tsc PASS

Key changes so far:
- [file] > [function]: [1-line summary of change]
- [file] > [function]: [1-line summary of change]

Items skipped: [list with reasons]
Items blocked: [list with reasons]

Next section: [N+1] — [brief description]
Files to touch: [list]
Depends on: [what from previous sections]
===
```

---

## Step 6: Validate

Verify the implementation is **complete and correct** relative to the task. This checks: "did I do everything the task asked?"

1. **Re-read the task file**
2. **For each in-scope item**, check:
   - Was it implemented? Read the actual file to confirm the change is there.
   - Does the implementation match the task's specification? (correct function, correct behavior, correct file)
   - Edge cases the task mentioned — were they handled?
3. **Run build checks**:
   - Rust changes: `cargo check --manifest-path src-tauri/Cargo.toml`
   - TypeScript changes: `npx tsc --noEmit`
   - If tests exist for modified code: `cargo test --manifest-path src-tauri/Cargo.toml`
4. **If anything is missing or wrong**: go back to Step 5 for those items only, then re-validate

After this step, all in-scope items must be implemented and the project must build cleanly.

---

## Step 7: Examine (code review)

This checks: "is the code I wrote correct, well-optimized, and safe?" — a different angle than Step 6.

Launch **3 parallel review agents**. Give each agent:
- The CHANGES LOG (which files and functions were modified)
- The relevant parts of the task (what each change was supposed to do)
- Instructions to READ the actual current files, not rely on the log alone

### Agent 1: "Correctness"
Read the modified files from the CHANGES LOG. For each change, check:
- Logic errors, off-by-one, wrong variable/field names
- Types match between frontend ↔ backend (field names, camelCase vs snake_case, Option vs null, Vec vs array)
- New code follows the same patterns as surrounding existing code
- The change actually achieves what the task item described

### Agent 2: "Safety & Performance"
Read the modified files from the CHANGES LOG. For each change, check:
- `unwrap()` on NEW code that can fail (prefer `unwrap_or_else`, `?`, or `.ok()`) — don't flag pre-existing unwrap() that wasn't part of this task
- Missing error handling on NEW I/O, network, or user input code — don't flag pre-existing code
- Potential deadlocks (Mutex locked across await, nested locks in same scope)
- Resource leaks (files not closed, threads not joined, listeners not unsubscribed)
- Race conditions in concurrent/parallel code
- Unnecessary allocations in hot paths (String cloning in loops, Vec/HashMap rebuilt on every call, format!() where &str would work)
- Unnecessary cloning where a reference or borrow would suffice
- O(n^2) or worse patterns that could be O(n) or O(1) (linear scans inside loops, repeated lookups that should use a HashMap/Set)
- Redundant work (same computation done multiple times, same file read twice, same data serialized repeatedly)
- Frontend: unnecessary re-renders (new objects/arrays created in render path, missing useMemo/useCallback where it matters, Zustand selectors that always return new references)

### Agent 3: "Integration"
Read the modified files from the CHANGES LOG. Check:
- All callers of modified functions still compile and behave correctly
- If Tauri commands were added/changed: they're registered in `main.rs` builder
- Frontend `invoke()` calls match backend command signatures exactly (param names, types)
- Event names and payload shapes match between Rust `emit()` and TypeScript `listen()`
- New imports are correct and not circular

### Collect results:

Merge all agent findings into one list:
- **MUST FIX**: bugs, panics, wrong behavior, build breaks, missing registrations
- **SHOULD FIX**: suboptimal patterns, minor inconsistencies, fragile code
- **NITPICK**: style, naming, readability — **ignore these, don't fix them**

### Scope rule for Safety findings:

The Safety agent may flag issues like "missing error handling." This is valid ONLY for code that was written or modified as part of this task. Pre-existing issues in untouched code are out of scope — note them in the summary as "pre-existing, not part of this task" but do NOT fix them.

---

## Step 8: Resolve

Fix issues from Step 7. **Maximum 3 fix cycles** to avoid infinite loops.

### Cycle:
1. Fix all **MUST FIX** items
2. Fix **SHOULD FIX** items — unless fixing them requires changes outside the task's scope (in that case, note them in the summary as future work)
3. Run build checks: `cargo check`, `npx tsc --noEmit`
4. If the fixes introduced new build errors → fix those (this counts as the next cycle)

### After 3 cycles:
If issues remain, stop and report them to the user in the summary. Don't loop forever.

### False positives:
If an Examine finding is wrong or doesn't apply, skip it and note why.

---

## Step 9: Update documentation

Every documentation file that is affected by the changes MUST be updated. Do NOT skip this step.

### Process:

1. **Identify what changed**: from the CHANGES LOG, determine what aspects of the project were modified:
   - New/changed Tauri commands or signatures
   - New/changed events or payloads
   - New/changed types, structs, interfaces
   - New/changed files or modules
   - New/changed architecture (threading, caching, data flow)
   - New/changed config options, defaults, or limits
   - New/changed dependencies

2. **For each existing doc file**, check if it references anything that changed:

   - **`CLAUDE.md`** — Check every section: Project Structure, Tauri Commands, Backend Events, App State, architecture descriptions, technical limits, known limitations. Update anything that's now stale.
   - **`README.md`** — Check: feature list, setup instructions, project description. Update if affected.
   - **`Tasks/README.md`** — Check: task status table, feature summaries, project structure diagram. Update if affected.
   - **Task files in `Tasks/` and `Tasks/updates/`** — If the implementation changes something a pending task references (e.g., a function that another task plans to modify), note the drift in that task file.

3. **Apply updates** to each affected doc file. Rules:
   - Match the existing style and language of each doc (CLAUDE.md = English concise, Technical Spec = French detailed)
   - Only update sections that are actually stale — don't rewrite sections that are still accurate
   - NEVER create new documentation files — only update existing ones
   - NEVER remove documentation for features that still exist

---

## Step 10: Update task status and move file

1. In the task file: mark every completed item `- [x]`
2. Update the task's status header:
   - All items done → `Completed (YYYY-MM-DD)`
   - Some items done, some skipped/blocked → `Partial`

3. **If fully completed, move the task file** out of `todo/` into the appropriate `done/` subdirectory:

   Determine the destination based on the task's `> **Type:**` header:
   - **Feature / Update** (new functionality) → `Tasks/done/features/`
   - **Fix / Optimization** (bug fix, perf fix, cleanup, debt) → `Tasks/done/fixes/`
   - **Infrastructure** (setup, build, config, tooling) → `Tasks/done/infrastructure/`

   Use `git mv` to move the file:
   ```bash
   git mv Tasks/todo/TASK_NAME.md Tasks/done/{category}/TASK_NAME.md
   ```

   If the task lives in `Tasks/updates/` (subdirectory with multiple files), move the entire directory:
   ```bash
   git mv Tasks/updates/TASK_DIR/ Tasks/done/{category}/TASK_DIR/
   ```

   If `git mv` fails (file not tracked), use regular `mv` instead.

4. **Update `Tasks/README.md`**:
   - Change the status in the Todo table (e.g., `⏳ Planifie` → `✅ Completed`)
   - Update the file link to point to the new location in `done/`
   - Add a row in the appropriate "Done" section (`Done — Features`, `Done — Fixes`, or `Done — Infrastructure`)
   - Add a line in the `Historique` section with today's date and a short description

5. If only **partially** completed, do NOT move the file — leave it in `todo/` with status `Partial`.

---

## Step 11: Summary

Show the user a clear summary:

```
## Implementation Complete: [TASK_NAME]

### Changes made
- `file_path` > `function/block` — [what changed]
- `file_path` > `function/block` — [what changed]

### Items skipped (if any)
- Item X.Y — [reason: already done / code drifted / blocked by Z]

### Issues found & resolved (from Examine)
- [MUST FIX] description — fixed in file_path
- [SHOULD FIX] description — fixed / deferred

### Pre-existing issues noticed (out of scope)
- [description] — in file_path (not touched by this task)

### Verification
- cargo check: PASS/FAIL
- npx tsc --noEmit: PASS/FAIL (if applicable)
- cargo test: PASS/FAIL (if applicable)

### Documentation updated
- `CLAUDE.md` — [sections updated, or "no changes needed"]
- `README.md` — [sections updated, or "no changes needed"]
- `Tasks/README.md` — [what changed]

### Remaining concerns (if any)
- [anything the user should know about]
```
