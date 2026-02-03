# Changelog

All notable changes to the Pokémon Unified Co-op Framework will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Phase 2 - Ghosting System (In Progress)
- [x] Camera offset discovery for Run & Bun (IWRAM 0x03005DFC, 0x03005DF8)
- [x] Ghost overlay rendering (render.lua) with Painter API
- [x] Ghost positioning fixed (relative to screen center)
- [x] Movement interpolation (interpolate.lua)
- [x] Animate-toward-target interpolation (replaced buffered render-behind + dead reckoning)
- [x] Adaptive send rate (zero sends idle, send on every tile change, immediate on map change)
- [x] Sub-tile camera correction for smooth ghost scrolling during walk animations
- [x] Smooth sub-tile rendering + direction marker + state debug colors
- [x] Direct TCP networking (replaced file-based proxy with mGBA built-in socket API)
- [x] Auto-generated player IDs (no more hardcoded IDs or client2/ copies)
- [x] Removed proxy.js and client2/ (no longer needed)
- [x] Disconnection handling (auto-reconnect, server broadcast, UI status)

## [0.2.8-alpha] - 2026-02-03

### Added - Network Polish: Disconnection & Reconnection (P2_05)
- **network.lua**: Disconnection detection
  - Socket "error" callback sets `connected = false` on socket failures
  - `sock:receive()` error handling marks connection as lost
  - `Network.flush()` wraps `sock:send()` in pcall — detects send failures
- **network.lua**: Automatic reconnection with exponential backoff
  - `Network.tryReconnect(timeMs)` — call once per frame, handles timing internally
  - Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
  - Max 10 attempts before giving up
  - Resets on successful reconnection
  - `Network.isReconnecting()` / `Network.getReconnectAttempts()` for UI
  - `Network.resetReconnect()` to manually reset backoff state
- **main.lua**: Reconnection in update loop
  - Detects `State.connected` vs `Network.isConnected()` desync each frame
  - Calls `Network.tryReconnect()` when disconnected
  - Re-registers and re-joins room on successful reconnect
  - Sends current position immediately after reconnect
- **main.lua**: Enhanced connection status UI
  - ONLINE (green) / RECONNECTING #N (yellow) / OFFLINE (red)
  - Status bar always visible when disconnected (not just in debug mode)
- **server.js**: Disconnect broadcast
  - `handleDisconnect()` now broadcasts `player_disconnected` to room before cleanup
  - Heartbeat timeout also broadcasts before destroying client
  - Guard against double-disconnect (end + close both fire on same socket)

## [0.2.7-alpha] - 2026-02-03

### Changed - Interpolation Rewrite & Camera Correction
- **interpolate.lua**: Complete rewrite — replaced "render behind" buffered interpolation + dead reckoning with "animate toward target" approach
  - When a new position snapshot arrives, ghost lerps from current visual position to new position
  - Animation duration estimated from interval between consecutive snapshots (auto-adapts to walk/run/bike/surf)
  - Removed: ring buffer, clock offset remapping, render delay, buffer purging, velocity tracking, extrapolation, smooth correction
  - Removed: `setRenderDelay()`, `setLocalTime()` APIs
  - Only two states remain: "interpolating" and "idle" (removed "extrapolating" and "correcting")
  - Constants: DEFAULT_ANIM_DURATION=250ms, MIN=50ms, MAX=500ms, TELEPORT_THRESHOLD=10 tiles
- **render.lua**: Sub-tile camera correction for smooth ghost scrolling
  - Added `Render.updateCamera(playerX, playerY, cameraX, cameraY)` — tracks camera offset deltas between frames
  - `ghostToScreen()` now uses tile-delta + sub-tile correction: `PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE + subTileX`
  - Visual continuity on tile change: compensates for tile-delta jump before camera catches up
  - Clamped to ±1 tile as safety net; resets on teleport (delta > 2 tiles)
  - Removed "extrapolating" and "correcting" from STATE_COLORS/STATE_OUTLINES (only interpolating/idle remain)
- **main.lua**: Tuned send rate and removed render delay
  - `SEND_RATE_MOVING` changed from 6 to 1 (send on exact frame position changes)
  - Removed `RENDER_DELAY` constant and `Interpolate.setRenderDelay()` / `Interpolate.setLocalTime()` calls
  - Added `Render.updateCamera()` call each frame before drawing overlay

## [0.2.6-alpha] - 2026-02-03

### Added - Smooth Rendering & Visual Improvements (P2_04D)
- **render.lua**: Sub-tile pixel-perfect ghost rendering
  - `ghostToScreen()` uses `math.floor` to prevent sub-pixel flickering
  - Interpolated float coordinates (from lerp) now render at exact pixel positions
- **render.lua**: Facing direction marker on each ghost
  - 4x4 white square indicator on the edge corresponding to facing direction
  - Supports all 4 directions: Down (1), Up (2), Left (3), Right (4)
- **render.lua**: State-based debug coloring
  - STATE_COLORS/STATE_OUTLINES tables for debug coloring by interpolation state
  - `drawGhost()` accepts optional `state` parameter for debug coloring
  - Falls back to default green when no state provided
  - `drawAllGhosts()` supports new `{pos=..., state=...}` format with backward compatibility
- **main.lua**: Passes interpolation state to render pipeline
  - `interpolatedPlayers` structure now includes `Interpolate.getState(playerId)`

## [0.2.5-alpha] - 2026-02-03

### Added - Dead Reckoning & Prediction (P2_04C) — *Superseded in 0.2.7*
- **interpolate.lua**: Dead reckoning when buffer is exhausted
  - Velocity tracking from buffer snapshots (tiles/ms)
  - Extrapolation: ghost continues moving using last known velocity when no new network data
  - Bounded extrapolation: max 500ms time, max 5 tiles distance
  - Smooth correction: when real position arrives after extrapolation, blend smoothly instead of snapping
  - State tracking: each ghost reports "interpolating", "extrapolating", "correcting", or "idle"
  - `Interpolate.getState(playerId)` API for debug overlay integration
  - Velocity/movement state reset on teleport detection
- *Note: Dead reckoning was removed in 0.2.7 — caused overshoot when player stops. Replaced by animate-toward-target approach.*

## [0.2.4-alpha] - 2026-02-03

### Changed - Adaptive Send Rate (P2_04B)
- **main.lua**: Replaced fixed `UPDATE_RATE` with adaptive send rate system
  - `SEND_RATE_MOVING = 6` (~10 sends/sec while moving) — *Changed to 1 in 0.2.7*
  - `SEND_RATE_IDLE = 0` (zero sends when idle)
  - `IDLE_THRESHOLD = 30` (~0.5sec to consider player idle)
  - Movement detection via `positionChanged()` comparison each frame
  - Cooldown-based send throttling (resets after each send)
  - Immediate send on map/warp change (bypasses cooldown)
  - Final position update when player stops (ensures ghost lands at exact position)
  - Added `State.isMoving`, `State.lastMoveFrame`, `State.sendCooldown`, `State.lastSentPosition`
  - Removed `UPDATE_RATE` constant and its validation in `initialize()`

## [0.2.3-alpha] - 2026-02-03

### Changed - Buffered Interpolation (P2_04A) — *Superseded in 0.2.7*
- **interpolate.lua**: Complete rewrite with temporal ring buffer
  - Ring buffer of timestamped position snapshots per player
  - Render delay system (~150ms behind real-time) for guaranteed smooth interpolation
  - Clock offset remapping: sender timestamps converted to receiver's local timeline
  - Teleport detection uses last raw buffer entry (not stale interpolated position)
  - Configurable render delay via `setRenderDelay(ms)`
  - Buffer purging to prevent memory leaks (snapshots older than 500ms past render time)
  - Max buffer size cap (20 entries per player)
- **main.lua**: Integration with buffered interpolation
  - Added `State.timeMs` elapsed time counter (incremented ~16.67ms/frame)
  - Timestamps (`t`) included in all outgoing position messages
  - `Interpolate.setLocalTime()` called each frame for clock sync
  - `Interpolate.step(16.67)` receives frame delta time
  - `Interpolate.update()` receives `message.t` timestamp
  - `UPDATE_RATE` reduced from 60 to 10 (~6 updates/sec for better interpolation)
  - `RENDER_DELAY` config constant (150ms default)
- **server.js**: Relays `t` (timestamp) field in position broadcasts
- *Note: Ring buffer + render delay approach was superseded in 0.2.7 by "animate toward target" — tile-based Pokemon data is too infrequent for render-behind to produce smooth results.*

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

- **0.2.8-alpha** (2026-02-03): Network polish — disconnection detection, auto-reconnect with backoff, ghost timeout, server broadcast
- **0.2.7-alpha** (2026-02-03): Interpolation rewrite — animate-toward-target, camera correction, removed dead reckoning
- **0.2.6-alpha** (2026-02-03): Smooth rendering — sub-tile pixel-perfect, direction marker, state debug colors
- **0.2.5-alpha** (2026-02-03): Dead reckoning — extrapolation, smooth correction, state tracking (superseded in 0.2.7)
- **0.2.4-alpha** (2026-02-03): Adaptive send rate (zero idle, ~10/sec moving, immediate on map change)
- **0.2.3-alpha** (2026-02-03): Buffered interpolation with temporal ring buffer
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
- [x] Movement interpolation (interpolate.lua)
- [x] Disconnection handling and ghost cleanup
- [x] Connection status improvements

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
