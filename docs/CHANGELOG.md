# Changelog

All notable changes to the Pokémon Unified Co-op Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed - 2026-02-02 (Update 5: Task Files Reorganization)
- **TASK FILES REORGANIZED**: Complete overhaul of task management system
  - **Renamed all tasks**: Old format `PHASE1_TCP_NETWORK.md` → New format `P1_01_TCP_NETWORK.md`
  - **Organized into folders**:
    - `Tasks/todo/` - All pending tasks (11 files currently)
    - `Tasks/done/` - Completed tasks (empty for now)
    - `Tasks/updates/` - Future updates and improvements
  - **Benefits**:
    - Clear global order: 00 → 01 → 02 → ... → 10
    - Phase visible: P0, P1, P2, P3, P4, P5
    - Easy to track progress: move from todo/ to done/
    - Easy to insert tasks: use decimals (P1_01.5) or renumber
    - Automatic correct sorting in file explorers
  - **Created P0_00_MEMORY_OFFSET_DISCOVERY.md**: Critical Phase 0 task (blocks Phase 1)
  - **Updated Tasks/README.md**: New organization structure documented

### Changed - 2026-02-02 (Update 4: Documentation Cleanup)
- **MAJOR DOCUMENTATION REORGANIZATION**: Reduced markdown files from 12 to 8 (-33%)
  - Merged MEMORY_SCANNING_GUIDE.md + RUN_AND_BUN.md → docs/MEMORY_GUIDE.md (consolidated all memory scanning info)
  - Integrated QUICKSTART.md into README.md (eliminated redundancy)
  - Moved PHASE2_PLAN.md → Tasks/PHASE2_DETAILED_PLAN.md (belongs with task files)
  - Deleted INDEX.md (unnecessary navigation file)
  - Deleted PROJECT_STRUCTURE.md (redundant with CLAUDE.md)
  - Simplified README.md to focus on quick start and essential links
  - Result: Cleaner structure, less confusion, easier to navigate

### Changed - 2026-02-02 (Update 3)
- **CRITICAL FIX**: Memory scanning methodology completely revised
  - Identified issue: addresses can be dynamic (via pointers) or static
  - Changed from Cheat Engine to mGBA Lua debugger (recommended)
  - Added MEMORY_SCANNING_GUIDE.md with comprehensive strategies
  - Updated code to handle both static offsets and dynamic pointers
  - HAL.readSafePointer() exists but not used - will be activated if needed

### Added - 2026-02-02 (Update 3)
- MEMORY_SCANNING_GUIDE.md - Complete memory scanning guide
  - Static vs Dynamic addresses explained
  - mGBA Lua debugger scripts (ready to copy-paste)
  - SaveBlock1/2 pointer detection methods
  - 3-phase testing strategy
  - Code adaptation examples for both modes

### Changed - 2026-02-02 (Update 2)
- **Documentation Update**: Clarified Run & Bun as primary target
  - Run & Bun heavily modifies Emerald base ROM
  - Emerald offsets are reference only, NOT directly usable
  - Added RUN_AND_BUN.md with offset scanning methodology
  - Updated CLAUDE.md with memory scanning guide
  - Added Phase 1 task: scan and find Run & Bun specific offsets
  - Updated all documentation to reflect Run & Bun focus

### Added - 2026-02-02 (Update 2)
- RUN_AND_BUN.md - Comprehensive guide for Run & Bun specifics
  - Memory offset scanning methodology (updated to reference new guide)
  - Offset validation procedures
  - ROM profile template
  - Development checklist

### Changed - 2026-02-02 (Update 1)
- **BREAKING CHANGE**: Switched from WebSocket to raw TCP sockets
  - Reason: mGBA Lua only supports `socket.tcp()`, no native WebSocket
  - Protocol: JSON messages delimited by `\n` over TCP
  - Server now uses Node.js `net` module instead of `ws`
  - Simplified communication layer
  - All documentation updated to reflect TCP usage

### Planned - Immediate Priority
- **CRITICAL**: Scan and find Run & Bun memory offsets (PlayerX, PlayerY, MapID, MapGroup, Facing)
- Create config/run_and_bun.lua with discovered offsets
- Validate offsets in mGBA Lua

### Planned - Phase 2
- Lua TCP client implementation
- Ghost overlay rendering system
- Movement interpolation
- Duel warp trigger UI
- Additional ROM profiles (Radical Red, Unbound)

## [0.1.0-alpha] - 2026-02-02

### Added - Phase 1: Foundation
- Initial project structure and documentation
- TCP relay server skeleton (Node.js + net)
  - Room-based multiplayer sessions (protocol defined)
  - Position broadcast system (protocol defined)
  - Heartbeat/keepalive mechanism (protocol defined)
  - Duel request/accept protocol (protocol defined)
- Lua client framework for mGBA
  - Hardware Abstraction Layer (HAL) with safe memory access
  - ROM detection from game header
  - Position reading (X, Y, MapID, MapGroup, Facing)
  - Frame-based update loop
  - Debug overlay display
- Pokémon Emerald (US) configuration profile
  - Complete memory offset mapping
  - Position validation functions
  - Map location database
- Comprehensive documentation
  - CLAUDE.md (full project specs)
  - README.md (project overview)
  - QUICKSTART.md (setup guide)
  - PROJECT_STRUCTURE.md (architecture)
- Development tools
  - .gitignore (ROM protection)
  - test-connection.js (server testing)
  - Modular code architecture

### Technical Details
- Safe memory access using pcall protection
- WRAM range validation (0x02000000-0x0203FFFF)
- Position update throttling (60 frames default)
- Console logging for debugging
- Generic config system for multi-ROM support

### Known Limitations
- TCP connection not yet implemented in Lua client
- Server still uses old WebSocket code (needs TCP rewrite)
- Ghost rendering not yet implemented
- Duel warp system not yet implemented
- Only Pokémon Emerald (US) configuration available
- No GUI for configuration

### Development Environment
- Node.js 18+ (with built-in `net` module)
- mGBA 0.10.0+ (with `socket.tcp()` support)
- Lua 5.4 (mGBA embedded)

---

## Version History

- **0.1.0-alpha** (2026-02-02): Initial framework foundation
- **0.0.0** (Concept): Project planning and specification

## Upcoming Versions

### 0.2.0 - Ghosting System
- [ ] Lua TCP client integration
- [ ] Server rewrite for TCP protocol
- [ ] Network position synchronization
- [ ] Ghost sprite overlay rendering
- [ ] Movement interpolation
- [ ] Connection status indicators

### 0.3.0 - Duel Warp System
- [ ] Click/button trigger system
- [ ] RAM write implementation
- [ ] Input locking during warp
- [ ] Battle room teleportation
- [ ] Duel acceptance UI

### 0.4.0 - Multi-ROM Support
- [ ] Run & Bun configuration (PRIMARY TARGET - Phase 1)
- [ ] Radical Red configuration (future)
- [ ] Unbound configuration (future)
- [ ] Automatic ROM detection
- [ ] Dynamic config loading

### 0.5.0 - Polish & Release Candidate
- [ ] Error handling improvements
- [ ] Performance optimization
- [ ] Complete API documentation
- [ ] Configuration UI/tool
- [ ] Unit tests
- [ ] Integration tests

### 1.0.0 - Stable Release
- [ ] All core features complete
- [ ] Multi-ROM fully tested
- [ ] Production-ready
- [ ] Complete documentation
- [ ] Tutorial videos

---

**Maintainers**: See [CLAUDE.md](CLAUDE.md) for development roadmap
