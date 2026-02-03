---
name: CodeAudit
description: Launch parallel agents to perform a full codebase audit - security vulnerabilities, performance optimizations, code quality improvements, and architectural issues.
context: fork
---

# CodeAudit - Full Codebase Audit

You are tasked with performing a comprehensive codebase audit by launching **multiple specialized agents in parallel**. Each agent focuses on a specific domain. At the end, you consolidate all findings into a single structured report.

**IMPORTANT: This is a READ-ONLY audit. Do NOT modify any source code. Only analyze and report.**

Optional user input via args: a focus area (e.g., "security only", "rust backend", "frontend stores"). If provided, narrow the scope accordingly. If empty, audit the entire codebase.

---

## Step 1: Launch all audit agents in parallel

Use the `Task` tool to launch **all 5 agents simultaneously in a single message** (this is critical for speed). Each agent uses `subagent_type=Explore` or `subagent_type=general-purpose` as noted.

### Agent 1: Security Audit (subagent_type=general-purpose)

```
Perform a security audit of this Tauri 2.x app (Rust backend + React/TypeScript frontend).

FOCUS AREAS:
- Command injection: Check all calls to yt-dlp, ffmpeg, and any shell/process spawning in src-tauri/src/youtube/ and src-tauri/src/discovery/
- Path traversal: Check file operations in src-tauri/src/storage/, src-tauri/src/import_export/, src-tauri/src/audio/
- Input validation: Check all Tauri commands in src-tauri/src/commands.rs - are parameters validated before use?
- XSS: Check frontend components that render user-controlled data (sound names, profile names, YouTube titles)
- Unsafe Rust: Check for any `unsafe` blocks and evaluate their necessity
- Tauri permissions: Check capabilities/default.json for overly broad permissions
- Secret exposure: Check for hardcoded secrets, API keys, or sensitive data in source
- Race conditions: Check Mutex/RwLock usage patterns in src-tauri/src/state.rs and concurrent operations
- Deserialization: Check JSON parsing for denial-of-service or injection vectors
- File system: Check atomic write patterns, temp file cleanup, symlink attacks

For each finding, report:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- File and line number
- Description of the vulnerability
- Concrete fix suggestion

Do NOT modify any code. Read and analyze only.
```

### Agent 2: Rust Performance & Optimization (subagent_type=general-purpose)

```
Analyze the Rust backend (src-tauri/src/) for performance issues and optimization opportunities.

FOCUS AREAS:
- Lock contention: Analyze Mutex/RwLock usage in state.rs, commands.rs - are locks held too long? Can they be narrowed?
- Memory: Look for unnecessary cloning, large allocations, missing capacity hints on Vec/HashMap
- Async: Check for blocking operations in async contexts (file I/O, process spawning without tokio::spawn_blocking)
- Audio hot path: Analyze audio/engine.rs, audio/track.rs, audio/symphonia_source.rs for allocations or locks in the audio thread
- Serialization: Check serde usage - are there unnecessary intermediate allocations?
- String handling: Look for excessive String allocations where &str would suffice
- Error handling: Check for unwrap() calls that should be proper error handling
- Unused dependencies: Check Cargo.toml for deps that could be removed or replaced with lighter alternatives
- Compilation: Check for features that could be disabled, or deps that slow compilation
- Thread pool: Evaluate the rayon thread pool usage in audio/analysis.rs

For each finding, report:
- Impact: HIGH / MEDIUM / LOW
- File and line number
- Current code issue
- Suggested optimization with code sketch

Do NOT modify any code. Read and analyze only.
```

### Agent 3: Frontend Performance & React Best Practices (subagent_type=general-purpose)

```
Analyze the React/TypeScript frontend (src/) for performance issues and best practices violations.

FOCUS AREAS:
- Re-renders: Check Zustand store subscriptions in all stores/ files - are selectors granular enough? Look for components subscribing to entire store state
- Memoization: Check components for missing useMemo/useCallback where expensive computations or callbacks are recreated
- Effect dependencies: Check all useEffect hooks for missing or incorrect dependency arrays
- Memory leaks: Check for missing cleanup in useEffect (event listeners, intervals, subscriptions to Tauri events)
- Bundle size: Check imports - are there barrel imports pulling in unused code?
- Component structure: Look for oversized components that should be split (especially DiscoveryPanel.tsx, SettingsModal.tsx, AddSoundModal.tsx, SoundDetails.tsx)
- State management: Is state in the right place? Local vs store? Derived state that should be computed?
- TypeScript: Check for `any` types, missing type guards, loose typing
- Canvas performance: Check WaveformDisplay.tsx for unnecessary redraws or canvas operations
- Event handling: Check useKeyDetection.ts, useAudioEvents.ts for proper cleanup and debouncing

For each finding, report:
- Impact: HIGH / MEDIUM / LOW
- File and line number
- Current issue
- Suggested fix

Do NOT modify any code. Read and analyze only.
```

### Agent 4: Code Quality & Maintainability (subagent_type=general-purpose)

```
Analyze the entire codebase (src-tauri/src/ and src/) for code quality and maintainability issues.

FOCUS AREAS:
- Dead code: Functions, types, imports that are never used
- Duplication: Similar logic repeated across files that should be extracted
- Naming: Inconsistent naming conventions, unclear variable/function names
- Error messages: Unclear or missing error messages for users
- Magic numbers: Hardcoded values that should be constants (check audio timing, cache sizes, UI dimensions)
- Function complexity: Functions that are too long or do too many things (especially commands.rs)
- Module organization: Files that are too large or have unclear responsibilities
- TODOs/FIXMEs: Unresolved code comments that indicate known issues
- API consistency: Tauri command naming and parameter conventions
- Logging: Missing or excessive logging, inconsistent log levels

For each finding, report:
- Priority: HIGH / MEDIUM / LOW
- File and line number
- Issue description
- Suggested improvement

Do NOT modify any code. Read and analyze only.
```

### Agent 5: Architecture & Design Patterns (subagent_type=general-purpose)

```
Analyze the overall architecture and design patterns of this Tauri 2.x app.

FOCUS AREAS:
- Separation of concerns: Is business logic properly separated from UI and data layers?
- State management: Is the split between Rust state (AppState) and frontend stores (Zustand) optimal?
- Event system: Analyze the backend→frontend event flow (main.rs mpsc → Tauri events). Any bottlenecks or missing events?
- Error propagation: How do errors flow from Rust → Frontend? Are all error paths handled?
- Concurrency model: Is the threading model (audio thread, rayon pool, tokio) well-structured?
- Dependency injection: How is AppState passed around? Could it be improved?
- Testing: What's the test coverage situation? What critical paths lack tests?
- Cross-platform: Check for platform-specific code that may cause issues (Windows vs macOS vs Linux paths, key detection)
- Scalability: What would break if the app grows (more tracks, more sounds, more profiles)?
- Data flow: Are there circular dependencies or tangled data flows between stores?

For each finding, report:
- Category: ARCHITECTURE / PATTERN / TESTING / SCALABILITY
- Severity: HIGH / MEDIUM / LOW
- Description
- Recommended change

Do NOT modify any code. Read and analyze only.
```

---

## Step 2: Consolidate the report

Once ALL agents have returned, combine their findings into a single structured report. Present it to the user organized as follows:

### Report Format

```
# Code Audit Report

## Critical & High Priority Issues
[List ALL critical/high findings from all agents, grouped by category]

## Security Vulnerabilities
[All findings from Agent 1, sorted by severity]

## Performance Optimizations
### Rust Backend
[All findings from Agent 2, sorted by impact]
### Frontend
[All findings from Agent 3, sorted by impact]

## Code Quality
[All findings from Agent 4, sorted by priority]

## Architecture & Design
[All findings from Agent 5, sorted by severity]

## Summary
- Total issues found: X
- Critical: X | High: X | Medium: X | Low: X
- Top 5 recommended actions (prioritized by impact)
```

---

## Step 3: Present to user

Output the full consolidated report. Then ask the user if they want to:
1. Create tasks for specific findings
2. Deep-dive into a specific category
3. Start fixing issues by priority
