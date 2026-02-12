# Testing Guide

Reference checklist for validating the current client/server behavior.

## Prerequisites

- Node.js 18+
- mGBA build with Lua scripting + sockets + canvas/Painter
- A ROM matching an existing profile in `config/`

## 1) Server Startup

```bash
cd server
npm start
```

Expected:
- banner appears
- `[Server] Listening on port 3333` (unless `PORT` override)
- ready line appears

## 2) TCP Smoke Test

Keep server running, then:

```bash
cd server
npm test
```

Expected:
- connection established
- `registered` received
- `joined` received
- position packet accepted
- test exits cleanly

## 3) Client Boot Test (Single Instance)

1. Open mGBA
2. Load ROM
3. `Tools > Scripting`
4. Load `client/main.lua`

Expected in mGBA log:
- framework banner
- ROM detection logs
- config load log (`Run & Bun` or fallback profile)
- `Connecting to server 127.0.0.1:3333...`

Expected behavior:
- overlay status visible
- no immediate Lua errors

## 4) Two-Client Ghost Sync

1. Start server
2. Launch two mGBA instances with same ROM/profile
3. Load `client/main.lua` in both

Expected:
- each client registers and joins room
- each sees the other ghost
- movement interpolation is smooth
- sprite updates propagate (`sprite_update`)
- no one-frame ghost flash during idle, walk, or close overlap transitions
- overlap depth is coherent:
  - if remote ghost is below local player on Y and sprites overlap, remote should render in front
  - if remote ghost is above local player on Y, local should stay in front

## 4B) Ghost Stability / Depth Cohabitation

1. Place both players on same map near each other.
2. Alternate quickly between:
   - standing still,
   - 1-tile steps,
   - overlap crossings (one passes above/below the other).
3. Repeat while camera moves slightly (walk back/forth near same spot).

Expected:
- no intermittent blink/flicker of remote ghost
- remote remains visible (not hidden behind map layer unexpectedly)
- front/back ordering remains coherent during overlap crossings

## 5) Reconnect Behavior

1. Run two clients connected
2. Stop server abruptly
3. Restart server

Expected:
- clients switch to reconnecting mode
- reconnect attempts happen automatically
- after reconnect: clients re-register, re-join room, and resume sync

## 6) Duel Flow (Manual)

1. Put two players near each other in same map
2. Trigger duel request from one client (A near ghost)
3. Accept from target client

Expected:
- requester gets waiting state then accepted
- accepter receives native textbox prompt (or fallback overlay prompt if textbox injection is unavailable)
- server relays `duel_warp` to both
- party/player-info handshake starts (`duel_party`, `duel_player_info`, `duel_ready`)
- battle module transitions into active stage

## 7) Auto-Duel Smoke (Optional)

Load wrappers instead of `main.lua`:
- requester: `client/auto_duel_requester.lua`
- accepter: `client/auto_duel_accepter.lua`
- optional SS variants: `client/auto_duel_requester_ss.lua`, `client/auto_duel_accepter_ss.lua`

Expected:
- auto request/accept sequence runs without manual input

## Useful Runtime Checks

mGBA console:

```lua
HAL.testMemoryAccess()
```

Run & Bun direct checks:

```lua
print(string.format("X: %d", emu.memory.wram:read16(0x00024CBC)))
print(string.format("Y: %d", emu.memory.wram:read16(0x00024CBE)))
```

## Common Failures

### Port already in use

Server error `EADDRINUSE`:
- change `PORT` env var, or
- stop process bound to port `3333`

### Script path/module issues

- Ensure `client/main.lua` is loaded from this repository layout
- Ensure `config/` exists at repository root (used by `main.lua`)

### No ghost visible

- verify both players are connected
- verify same room and compatible map metadata
- check server logs for `position` / `sprite_update`

## Evidence to Capture for Bugs

- exact commit/hash or local diff context
- server logs (connect/register/join/duel events)
- mGBA Lua logs
- reproduction steps
- screenshot/video when visual sync is involved
- include active `render` block from profile (`config/run_and_bun.lua` or `config/emerald_us.lua`)
