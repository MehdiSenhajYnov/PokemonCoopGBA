# Pokemon Co-op Client (Lua)

Lua runtime loaded by mGBA (`client/main.lua`).

## Requirements

- mGBA build with Lua scripting + TCP socket + canvas/Painter support
- Server running (`server/server.js`)
- ROM profile present in `config/`

## Core Modules

- `main.lua`: orchestrator (init, frame loop, network routing, duel/battle state).
- `hal.lua`: safe low-level memory/hardware access (EWRAM/IWRAM/VRAM/OAM/IO).
- `network.lua`: TCP JSON line protocol + reconnect backoff.
- `interpolate.lua`: waypoint queue interpolation with seam-transition support.
- `sprite.lua`: local sprite capture from OAM/VRAM/palette + remote sprite cache.
- `render.lua`: hybrid ghost renderer (OAM injection + overlay labels/fallback).
  - Fixed reserved OAM slots by default (`oamStrategy = "fixed"`).
  - OAM sprites stay active each frame (anti-flash baseline path).
  - Optional overlap-front correction draws a front overlay layer with
    hysteresis (`forceOverlayFront*`) to avoid frame-to-frame toggling.
  - Projection/OAM grace windows (`projectionCacheTTLFrames`,
    `oamMissGraceFrames`) keep ghosts stable during transient misses.
- `duel.lua`: duel request/accept state machine.
- `textbox.lua`: native Pokemon textbox flow via script injection.
- `battle.lua`: PvP synchronization logic (buffer relay, ROM patch lifecycle).
- `occlusion.lua`: optional/experimental BG occlusion module (not wired by default in `main.lua`).

## Runtime Defaults (`main.lua`)

```lua
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 3333
local SEND_RATE_MOVING = 1
local SEND_RATE_IDLE = 30
local POSITION_HEARTBEAT_IDLE = 60
local SPRITE_HEARTBEAT = 120
local SPRITE_MIN_BROADCAST_CONFIDENCE = 0.35
local ENABLE_DEBUG = true
```

## Render Tuning (`config/*.lua` -> `render`)

Common keys used by current client:

- `oamStrategy`, `oamReservedCount`, `oamBaseIndex`
- `oamPriorityBack`, `oamPriorityFront`
- `vramRefreshIntervalFrames`
- `projectionCacheTTLFrames`, `projectionSettleGraceFrames`
- `oamMissGraceFrames`
- `forceOverlayFront`, `forceOverlayFrontConfirmFrames`,
  `forceOverlayFrontReleaseGraceFrames`
- `preferNativePalBank`
- `spriteCandidateMaxDist`, `spriteCandidateStabilityFrames`,
  `spriteCaptureConfidenceMin`, `spriteBroadcastConfidenceMin`

## Message Flow (Client Side)

Incoming:
- `registered`, `joined`
- `position`, `sprite_update`, `player_disconnected`
- `ping/pong`
- duel/battle messages (`duel_*`)

Outgoing:
- `register`, `join`, `position`, `sprite_update`, `pong`
- duel/battle messages (`duel_request`, `duel_accept`, `duel_party`, `duel_buffer*`, ...)

## ROM / Config Loading

- `main.lua` detects ROM header/title and loads profile from `../config/`.
- Primary path today defaults BPEE to `run_and_bun.lua`.
- Fallback profile is `emerald_us.lua` if detection/loading fails.

## Auto-Duel Wrappers

- `auto_duel_requester.lua`
- `auto_duel_accepter.lua`
- `auto_duel_requester_diag.lua`
- `auto_duel_accepter_diag.lua`
- `auto_duel_requester_ss.lua`
- `auto_duel_accepter_ss.lua`

These wrappers currently use local absolute paths and may need adaptation per machine.

## Quick Troubleshooting

- No connection: verify server on `127.0.0.1:3333`.
- No ghosts: ensure both clients joined same room/map and are receiving `position`.
- Battle issues: verify `config/run_and_bun.lua` battle + battle_link addresses/patches.
- Health check helper in mGBA console: `HAL.testMemoryAccess()`.
