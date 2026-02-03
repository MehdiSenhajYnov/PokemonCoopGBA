---
name: UpdateDoc
description: Full documentation sync. Analyzes the entire codebase and updates all documentation files to reflect current state.
---

# UpdateDoc - Full Documentation Sync

You are tasked with analyzing the ENTIRE codebase and updating ALL documentation files to reflect the current state of the code. This is a comprehensive documentation audit and sync.

## Strategy

Use **multiple parallel agents** to maximize speed. The process has 3 phases:

---

### Phase 1: Parallel Codebase Analysis (use Task agents in parallel)

Launch ALL of these agents simultaneously in a single message:

1. **Agent "Rust Backend Core"** (Explore agent, very thorough):
   Analyze all Rust source files in `src-tauri/src/`. For each file, extract:
   - Public structs, enums, their fields and derives
   - All `#[tauri::command]` functions with their full signatures (params + return types)
   - AppState fields and types
   - Audio engine architecture (tracks, crossfade, symphonia, device handling)
   - Key detection system (per-platform implementations, chord detection)
   - Event types emitted to frontend (all `app_handle.emit()` calls)
   - Constants, defaults, limits (max tracks, cache sizes, timeouts)
   - Thread/async architecture (spawned threads, rayon pool, tokio tasks, mpsc channels)
   - Any new modules, files, or features not yet documented

2. **Agent "Frontend Stores & Types"** (Explore agent, very thorough):
   Analyze all TypeScript stores and types in `src/stores/` and `src/types/`. Extract:
   - Every Zustand store: state shape, actions, selectors, subscriptions
   - All TypeScript interfaces and types in `types/index.ts`
   - Store interconnections (which stores reference others)
   - Any new stores or types not yet documented

3. **Agent "Frontend Components & Hooks"** (Explore agent, very thorough):
   Analyze `src/components/` and `src/hooks/`. Extract:
   - Component tree and hierarchy
   - Key component props interfaces
   - Hook signatures, dependencies, and behavior
   - Event listeners (Tauri events, DOM events)
   - UI patterns (modals, toasts, drag-drop, resize)
   - Any new components or hooks not yet documented

4. **Agent "Utils, Commands & Config"** (Explore agent, very thorough):
   Analyze `src/utils/`, `src-tauri/tauri.conf.json`, `src-tauri/Cargo.toml`, `package.json`, and config files. Extract:
   - All tauriCommands.ts wrappers (command names, params, return types)
   - Utility functions and their purposes
   - Cargo dependencies and features
   - npm dependencies
   - Tauri config (permissions, capabilities, window config)
   - Build configuration

5. **Agent "Existing Docs Inventory"** (Explore agent, medium):
   Read and inventory ALL existing documentation:
   - `CLAUDE.md` - full content
   - `KeyToMusic_Technical_Specification.md` - full content
   - `README.md` - full content
   - `Tasks/README.md` - full content
   - All files in `Tasks/` and `Tasks/updates/`
   - Any other `.md` files in the project root or subdirectories
   List every section/heading in each doc and note what it currently says.

---

### Phase 2: Diff Analysis

After ALL Phase 1 agents complete, compare the codebase analysis results against the existing documentation. Identify:

- **Outdated sections**: Code has changed but docs still describe old behavior
- **Missing sections**: New features/modules exist in code but aren't documented
- **Incorrect information**: Docs say one thing, code does another (wrong signatures, wrong defaults, wrong limits, wrong file paths)
- **Removed features**: Docs describe something that no longer exists in code
- **Structural issues**: Docs reference wrong file locations, outdated directory structure

Create a detailed change plan listing every file and every section that needs updating.

---

### Phase 3: Apply Updates (parallel edits where possible)

For each documentation file that needs changes:

#### `CLAUDE.md`
This is the PRIMARY reference doc. It MUST accurately reflect:
- Project structure (every file/directory)
- All Tauri commands (exact signatures)
- All backend events (exact payloads)
- All AppState fields
- Architecture descriptions for every subsystem
- Technical limits and defaults
- Development commands
- Known limitations

#### `KeyToMusic_Technical_Specification.md`
This is the DETAILED technical spec. Update:
- Data model (Rust structs and TS types must match actual code)
- All algorithm pseudocode (must match actual implementations)
- Architecture diagrams
- API/command signatures
- UI component descriptions
- Dependency versions

#### `Tasks/README.md`
Update the task index to reflect current state of all phase files.

#### `README.md`
Update if the feature list, setup instructions, or project description are outdated.

#### Task phase files (`Tasks/*.md`)
Mark completed phases as done. Update any in-progress phases with current status.

---

## Rules

- **NEVER create new documentation files** - only update existing ones
- **NEVER remove documentation for features that still exist in code**
- **NEVER add documentation for features that don't exist in code** (no speculation, no planned features)
- **Match exact function signatures, type names, field names from the code** (case-sensitive, exact spelling)
- **Preserve the existing documentation style and language** (CLAUDE.md is English, Technical Spec is French)
- **Keep CLAUDE.md concise** - it's a quick reference, not a tutorial
- **Keep Technical Spec detailed** - it's the full specification
- **If a section is already accurate, don't touch it** - minimize unnecessary diffs
- **Show a summary at the end** listing every file changed and what was updated
