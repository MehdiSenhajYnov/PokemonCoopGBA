---
name: GetIdea
description: Analyze the codebase and suggest new features or improvements. Tracks ideas across sessions (good, maybe, dismissed) so suggestions are always fresh. Use with optional arguments like "recall good ideas", "recall dismissed", "recall maybe".
---

# GetIdea - Idea Generator with Memory

You are tasked with generating fresh feature ideas and improvements for KeyToMusic, while maintaining persistent memory of all past ideas across sessions.

**Arguments:** $ARGUMENTS

---

## Idea Tracking Files

All idea tracking lives in `Tasks/ideas/`:

- `Tasks/ideas/good.md` — Ideas the user liked (accepted / wants to implement)
- `Tasks/ideas/maybe.md` — Ideas the user found interesting but isn't sure about yet
- `Tasks/ideas/dismissed.md` — Ideas the user rejected or isn't interested in

Each file uses this format:

```markdown
# [Category] Ideas

| # | Idea | Summary | Date |
|---|------|---------|------|
| 1 | **Short title** | One-line description | YYYY-MM-DD |
| 2 | **Short title** | One-line description | YYYY-MM-DD |
```

---

## Step 1: Check the mode

Parse `$ARGUMENTS` to determine the mode:

### Mode A — Recall mode

If the user says something like:
- "recall good ideas", "rappelle les bonnes idees", "show good", "bonnes idees"
- "recall maybe", "idees a voir", "show maybe"
- "recall dismissed", "idees ecartees", "show dismissed"
- "recall all", "toutes les idees", "show all"

Then:
1. Read the corresponding file(s) from `Tasks/ideas/`
2. Present a clean summary to the user, grouped by category
3. If the user asks about a specific idea, give more details
4. **STOP here. Do not generate new ideas in recall mode.**

### Mode B — Generate new ideas (default)

If no recall keyword is detected, proceed to Step 2.

---

## Step 2: Read existing ideas

Read ALL three files to build the exclusion list:
- `Tasks/ideas/good.md`
- `Tasks/ideas/maybe.md`
- `Tasks/ideas/dismissed.md`

If the files don't exist yet, create them with empty tables. Create the `Tasks/ideas/` directory if needed.

Extract every idea title and summary. These are **excluded** from new suggestions — you must NEVER suggest an idea that already appears in any of the three files.

---

## Step 3: Analyze the codebase

Launch **parallel Explore agents** to understand the current state:

1. **Backend agent** — Explore `src-tauri/src/` for: audio capabilities, key detection features, YouTube integration, discovery system, import/export, error handling, performance patterns
2. **Frontend agent** — Explore `src/` for: UI components, stores, hooks, user workflows, missing UX patterns
3. **Config/Types agent** — Explore `src/types/`, `src/utils/`, `src-tauri/src/types.rs` for: data model gaps, unused fields, missing validations

Also read `CLAUDE.md` for the full architecture overview.

---

## Step 4: Generate 5 fresh ideas

Based on the codebase analysis, generate exactly **5 new ideas** that:
- Are NOT in any of the three tracking files
- Are realistic and implementable within the existing architecture
- Cover a mix of categories (pick from below):
  - **UX** — User experience improvements
  - **Audio** — Audio engine features
  - **Discovery** — Discovery system enhancements
  - **Performance** — Optimization opportunities
  - **Integration** — New integrations or formats
  - **Quality of Life** — Small but impactful improvements
  - **Accessibility** — Accessibility features

For each idea, present:

```
### N. [Category] Idea Title

**What:** One paragraph explaining the feature/improvement.

**Why:** One sentence on why it matters for the user.

**Scope:** Small / Medium / Large (rough implementation scope)

**Key files:** List 2-3 files that would be involved.
```

If `$ARGUMENTS` contains a theme or focus area (e.g., "audio ideas", "UX ideas", "performance"), focus all 5 ideas on that theme.

---

## Step 5: Collect user feedback

After presenting the 5 ideas, ask the user to categorize each one:

- **Good** — Interested, want to implement eventually
- **Maybe** — Interesting but not sure yet
- **Dismissed** — Not interested

Use `AskUserQuestion` to collect feedback efficiently. You can ask about all 5 at once using a multi-select format, or one by one if the user prefers discussion.

---

## Step 6: Save to tracking files

Based on user feedback, append each idea to the appropriate file:
- Accepted ideas → `Tasks/ideas/good.md`
- Maybe ideas → `Tasks/ideas/maybe.md`
- Dismissed ideas → `Tasks/ideas/dismissed.md`

Use today's date. Append to the existing table (don't overwrite). Increment the `#` counter from the last entry in each file.

If the user wants to move an idea between categories (e.g., "actually move idea 3 to good"), update both files accordingly.

---

## Step 7: Summary

Show the user:
- How many ideas were added to each category
- Current totals in each file (e.g., "Good: 12 | Maybe: 8 | Dismissed: 15")
- Remind them they can use `/GetIdea recall good` to review saved ideas anytime

---

## Rules

- **NEVER suggest an idea that's already tracked** in any of the three files
- **NEVER implement anything** — this skill only generates and tracks ideas
- **Use French** for idea content (matching project convention), unless the user writes in English
- **Be specific** — "Ajouter un mode shuffle cross-track qui enchaine les sons de tracks differents" not "ameliorer l'audio"
- **Reference real code** — mention actual files, functions, or components when describing scope
- **Keep ideas grounded** — only suggest things that make sense for a manga-reading soundboard app
