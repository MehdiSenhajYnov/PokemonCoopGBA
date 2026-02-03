---
name: CreateTask
description: Generate a detailed task file in Tasks/ based on user description. Use when the user wants to plan work without implementing it.
---

# CreateTask - Generate a Task File

You are tasked with creating a detailed task file in the `Tasks/` directory based on the user's description: $ARGUMENTS

## Process

### Step 1: Understand the request

Analyze what the user wants. The input can be:
- A vague idea ("improve audio performance")
- A specific feature ("add a volume fade-in on track start")
- A bug to fix ("crossfade causes audio glitch")
- A brainstorm summary or conversation context
- A refactoring goal ("refactor the key detection system")

### Step 2: Explore the codebase

Use Explore agents to understand the current state of the relevant code. You MUST read the actual source files to write accurate task descriptions with real file paths, real function names, and real line numbers. Don't guess.

### Step 3: Determine the task type and format

Choose the appropriate format based on the task nature:

**Feature / Update** (new functionality):
```
# Feature Name

> **Statut:** En attente d'implementation
> **Type:** Update — [brief description]
> **Objectif:** [1-2 sentences]

---

## Vue d'ensemble

[Context: why this feature matters, what problem it solves]

## Implementation

### Section N - [Sub-feature]

**Fichiers concernes:**
- `path/to/file.rs` — [what changes]
- `path/to/component.tsx` — [what changes]

**Details:**
[Precise description of what to implement, with code references when relevant]

## Fichiers a creer

| Fichier | Description |
|---------|-------------|
| `path/to/new_file` | ... |

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `path/to/existing` | ... |
```

**Bug Fix / Optimization** (fixing existing behavior):
```
# Problem Title

## Probleme

[Description of the issue]

---

## Causes identifiees (par priorite)

### P0 - CRITIQUE

#### 1. [Root cause]
**Fichier:** `path/to/file.rs:line_number`

[Code snippet showing the problem]

**Impact:** [What goes wrong]
**Fix:** [Proposed solution]

---

## Plan d'implementation

### Phase 1 : [Group name]
- [ ] Task 1
- [ ] Task 2

## Fichiers concernes

| Fichier | Modifications |
|---------|--------------|
| `path` | ... |
```

**Phase / Milestone** (large multi-step work):
```
# Phase N - Title

> **Statut:** En attente

---

## N.1 Section Name

- [ ] **N.1.1** Task description
  - [ ] Sub-task detail
  - [ ] Sub-task detail

- [ ] **N.1.2** Task description
  - [ ] Sub-task detail

## N.2 Section Name
...
```

### Step 4: Choose file name and location

- **Feature/update tasks** go in `Tasks/updates/{Feature_Name}/` with a main file and optional sub-files
- **Bug fixes** go in `Tasks/updates/{Fix_Name}/`
- **Phase-level tasks** go in `Tasks/` as `PHASE_N.md` or a descriptive `UPPER_SNAKE_CASE.md`
- File names use UPPER_SNAKE_CASE (e.g., `AUDIO_BUFFER_REFACTOR.md`)

### Step 5: Write the task file

Write the task file with:
- **Real file paths and line numbers** from the codebase (not made up)
- **Real function/struct/component names** (exact spelling, exact casing)
- **Concrete implementation details** — not vague "improve X" but specific "change Y in Z to do W"
- **Checkboxes** (`- [ ]`) for all actionable items
- **Priority levels** when there are multiple items (P0/P1/P2 or Haute/Moyenne/Faible)
- **Files table** listing every file that will be created or modified

### Step 6: Update Tasks/README.md

Add an entry for the new task in `Tasks/README.md` in the appropriate section.

## Rules

- **NEVER create the task file without reading the relevant source code first** — the task must reference real code
- **Use French** for task content (matching the existing convention), unless the user writes in English
- **Be specific** — "modifier `engine.rs:299` pour pre-creer la source" not "improve audio engine"
- **Include effort estimates** only if you can base them on the actual complexity of the code you read
- **Don't implement anything** — only create the task documentation
- **Show the user** the path of the created file(s) when done
