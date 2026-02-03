# Changelog

All notable changes to the Pokémon Unified Co-op Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Phase 2 - Ghosting System (In Progress)
- [x] Camera offset discovery for Run & Bun (IWRAM 0x03005DFC, 0x03005DF8)
- [x] Ghost overlay rendering (render.lua) with Painter API
- [x] Ghost positioning fixed (relative to screen center)
- [ ] Movement interpolation
- [ ] Disconnection handling

## [0.2.2-alpha] - 2026-02-03

### Fixed - Ghost Positioning
- **render.lua**: Replaced camera-based coordinate conversion with relative screen-center positioning
  - Old formula `tile*16 + cameraOffset` was map-dependent (different maps have different origins)
  - New formula: `ghostScreen = (112, 72) + (ghostTile - playerTile) * 16`
  - Player is always at screen center (120, 80), ghost rendered as tile delta
  - No longer depends on camera offsets (IWRAM reads)
  - Works consistently across all maps (overworld, buildings, rooms)
- **main.lua**: Simplified ghost rendering call
  - Passes player position to `Render.drawAllGhosts()` instead of camera offsets
  - Removed camera read + fallback logic from `drawOverlay()`
- **client2/**: Synchronized with client/ fixes

## [0.2.1-alpha] - 2026-02-03

### Added - Phase 2: Ghost Rendering System
- **client/render.lua**: Ghost player rendering module
  - Coordinate conversion (initially camera-based, fixed in 0.2.2)
  - Semi-transparent green rectangles for ghost players
  - Player name labels above ghosts
  - Map-based filtering (only show ghosts on same map)
  - Off-screen culling
- **hal.lua**: IWRAM memory read support
  - `safeReadIWRAM()` for 0x03xxxxxx addresses
  - `HAL.readCameraX()` / `HAL.readCameraY()` with signed s16 conversion
  - `toSigned16()` for u16→s16 conversion (camera offsets are negative)
- **main.lua**: Ghost rendering integration
  - `require("render")` and `Render.init()` in initialization
  - Ghost drawing in `drawOverlay()`
  - `State.showGhosts` toggle flag
  - Fixed forward-declaration bug for `readPlayerPosition()`
  - `drawOverlay()` now receives `currentPos` parameter (avoids duplicate memory reads)

## [0.2.0-alpha] - 2026-02-03

### Added - Phase 1 Complete: TCP Networking
- **network.lua**: File-based TCP communication module for mGBA
  - Custom JSON encoder/decoder (pure Lua, no external dependencies)
  - Three-file architecture: `client_outgoing.json`, `client_incoming.json`, `client_status.json`
  - Non-blocking async communication via file I/O
  - Functions: `connect()`, `send()`, `receive()`, `flush()`, `disconnect()`
- **proxy.js**: File-to-TCP bridge (Node.js)
  - Bridges Lua file I/O to TCP socket communication
  - Automatic reconnection with 2-second backoff
  - Message caching for session recovery (register + join)
  - Watches outgoing file, writes incoming file
- **client2/**: Complete second client for 2-player testing
  - Mirror of client/ with `playerID = "player_2"`
  - Separate proxy.js instance
- **FILE_BASED_SETUP.md**: Architecture documentation for file-based proxy system
- **QUICKSTART.md**: French quick-start guide with 2-player testing instructions

### Changed - 2026-02-03
- **main.lua** upgraded to v0.2.0:
  - Integrated network.lua for TCP communication
  - Canvas overlay with player count, connection status, position display
  - Message handling: register, join, position broadcasts, ping/pong
  - Frame-based update loop with configurable UPDATE_RATE
  - ROM detection defaults to Run & Bun config for BPEE
- **End-to-end connection tested**: Server + Proxy + Lua client working together

### Changed - 2026-02-02 (Update 5: Task Files Reorganization)
- **TASK FILES REORGANIZED**: Complete overhaul of task management system
  - Renamed all tasks: Old format `PHASE1_TCP_NETWORK.md` -> New format `P1_01_TCP_NETWORK.md`
  - Organized into folders: `Tasks/todo/`, `Tasks/done/`, `Tasks/updates/`
  - Created P0_00_MEMORY_OFFSET_DISCOVERY.md: Critical Phase 0 task

### Changed - 2026-02-02 (Update 4: Documentation Cleanup)
- Reduced markdown files from 12 to 8 (-33%)
- Merged scanning guides into docs/MEMORY_GUIDE.md
- Simplified README.md

### Changed - 2026-02-02 (Update 3: Memory Scanning)
- Memory scanning methodology revised for mGBA Lua debugger
- HAL updated to support both static and dynamic offset modes
- Added MEMORY_SCANNING_GUIDE.md

### Changed - 2026-02-02 (Update 1: TCP Migration)
- **BREAKING**: Switched from WebSocket to raw TCP sockets
  - mGBA Lua only supports `socket.tcp()`, no native WebSocket
  - Protocol: JSON messages delimited by `\n` over TCP
  - Server uses Node.js `net` module

## [0.1.1-alpha] - 2026-02-02

### Added - Phase 0 Complete: Memory Offset Discovery
- **Run & Bun offsets discovered and validated**:
  - PlayerX: `0x02024CBC` (16-bit)
  - PlayerY: `0x02024CBE` (16-bit)
  - MapGroup: `0x02024CC0` (8-bit)
  - MapID: `0x02024CC1` (8-bit)
  - Facing: `0x02036934` (8-bit)
- **Offset mode: STATIC** (no dynamic pointers needed)
- **config/run_and_bun.lua** filled with discovered addresses
- Memory scanning scripts used successfully
- docs/RUN_AND_BUN.md updated with results

## [0.1.0-alpha] - 2026-02-02

### Added - Phase 1: Foundation
- Initial project structure and documentation
- TCP relay server (Node.js + net)
  - Room-based multiplayer sessions
  - Position broadcast system
  - Heartbeat/keepalive mechanism (30s)
  - Duel request/accept protocol (prepared)
- Lua client framework for mGBA
  - Hardware Abstraction Layer (HAL) with safe memory access
  - ROM detection from game header
  - Position reading (X, Y, MapID, MapGroup, Facing)
  - Frame-based update loop
  - Debug overlay display
- Pokémon Emerald (US) configuration profile
  - Complete memory offset mapping
  - Position validation functions
- Memory scanning scripts (4 scripts in scripts/)
  - scan_vanilla_offsets.lua
  - scan_wram.lua
  - find_saveblock_pointers.lua
  - validate_offsets.lua
- Comprehensive documentation (CLAUDE.md, README.md, MEMORY_GUIDE.md)
- Development tools (.gitignore, test-connection.js)

### Technical Details
- Safe memory access using pcall protection
- WRAM range validation (0x02000000-0x0203FFFF)
- Position update throttling (60 frames default)
- Generic config system for multi-ROM support
- mGBA dev build #8977 included via Git LFS

---

## Version History

- **0.2.2-alpha** (2026-02-03): Ghost positioning fix (relative screen-center approach)
- **0.2.1-alpha** (2026-02-03): Ghost rendering system (render.lua, IWRAM support)
- **0.2.0-alpha** (2026-02-03): TCP networking complete, file-based proxy, 2-player testing
- **0.1.1-alpha** (2026-02-02): Run & Bun offsets discovered
- **0.1.0-alpha** (2026-02-02): Initial framework foundation
- **0.0.0** (Concept): Project planning and specification

## Upcoming Versions

### 0.3.0 - Ghosting System Complete (Phase 2)
- [x] Camera offset discovery for Run & Bun
- [x] Ghost overlay rendering (render.lua)
- [ ] Movement interpolation (interpolate.lua)
- [ ] Disconnection handling and ghost cleanup
- [ ] Connection status improvements

### 0.4.0 - Duel Warp System (Phase 3)
- [ ] Click/button trigger system
- [ ] RAM write implementation
- [ ] Input locking during warp
- [ ] Battle room teleportation
- [ ] Duel acceptance UI

### 0.5.0 - Multi-ROM Support (Phase 4)
- [ ] Radical Red configuration
- [ ] Unbound configuration
- [ ] Improved ROM auto-detection

### 0.6.0 - Polish & Release Candidate (Phase 5)
- [ ] Error handling improvements
- [ ] Performance optimization
- [ ] Complete API documentation
- [ ] Configuration UI/tool

### 1.0.0 - Stable Release
- [ ] All core features complete
- [ ] Multi-ROM fully tested
- [ ] Production-ready
- [ ] Complete documentation

---

**Maintainers**: See [CLAUDE.md](../CLAUDE.md) for development roadmap
