# Pokemon Unified Co-op Framework

Co-op ghost sync and PvP battle synchronization for Pokemon GBA ROMs, using:
- `client/`: mGBA Lua runtime
- `server/`: Node.js TCP relay
- `config/`: ROM-specific memory/address profiles

Status: experimental alpha. Primary target ROM is Run & Bun.

## Current Capabilities

- Real-time ghost sync (position + facing + sprite data).
- Hybrid ghost rendering:
  - direct OAM/VRAM injection for sprites,
  - overlay fallback + labels.
- Ghost depth handling:
  - fixed OAM priority for stable engine compatibility,
  - front-forced overlay fallback only when a ghost overlaps the local player
    and is lower on Y (prevents wrong overlap in close contact).
- Seam/cross-map projection using map metadata envelopes (`mapRev`, `metaStable`, `metaHash`).
- Auto reconnect with exponential backoff on the client.
- Duel flow with native in-game textboxes.
- PvP battle sync using buffer relay (GBA-PK style, no physical teleport warp).

## Quick Start

### Requirements

- Node.js 18+
- mGBA dev build with Lua scripting + socket/canvas support
- Supported ROM profile (`config/run_and_bun.lua` or `config/emerald_us.lua`)

### 1) Start server

```bash
cd server
npm install
npm start
```

Default port is `3333` (override with `PORT` env var).

### 2) Start client in mGBA

1. Load ROM in mGBA
2. Open `Tools > Scripting`
3. Load `client/main.lua`

### 3) Verify

- Server logs show register/join/position traffic.
- Overlay shows connection status and player count.
- With 2 instances, each player sees the other ghost.

## Repo Structure

```text
client/      mGBA Lua runtime modules (main loop, HAL, render, duel, battle)
server/      TCP relay server (Node.js net)
config/      ROM profiles (addresses, flags, battle link patches)
docs/        Testing and reverse-engineering docs
scripts/     Scanners, diagnostics, tooling helpers
Tasks/       Backlog/history notes
```

## Protocol Summary

- Transport: raw TCP
- Framing: JSON line-delimited (`\n`)
- Core messages: `register`, `join`, `position`, `sprite_update`, `ping/pong`
- Duel/PvP messages: `duel_request`, `duel_accept`, `duel_decline`, `duel_cancel`,
  `duel_party`, `duel_player_info`, `duel_ready`, `duel_stage`, `duel_buffer*`, `duel_end`

See `server/README.md` for the detailed message reference.

## Main Docs

- `QUICKSTART.md`
- `client/README.md`
- `server/README.md`
- `docs/TESTING.md`
- `docs/MEMORY_GUIDE.md`
- `docs/RUN_AND_BUN.md`
- `docs/CHANGELOG.md`

## Notes

- `config/run_and_bun.lua` is the source of truth for Run & Bun addresses.
- The in-client banner still prints `v0.2.0` in `client/main.lua`; feature set is newer than that banner string.
