# Pokemon Co-op Server

Node.js TCP relay used by mGBA Lua clients.

- Transport: raw TCP (`net`)
- Framing: one JSON payload per line (`\n`)
- Default port: `3333`

## Run

```bash
npm install
npm start
```

Dev/watch mode:

```bash
npm run dev
```

Smoke test (server must already be running):

```bash
npm test
```

## Environment

- `PORT`: listening port (default `3333`)
- `HEARTBEAT_INTERVAL_MS`: heartbeat period in ms (default `30000`, minimum `1000`)
- `DUEL_STAGE_VERBOSE`: set to `1` for full duel stage diagnostics in server logs (default compact logs)

## Client Lifecycle

1. Client connects via TCP
2. Sends `register` (`playerId` optional, `characterName` optional)
3. Sends `join` (`roomId`, defaults to `"default"`)
4. Streams `position` and `sprite_update`
5. Exchanges duel/battle messages when duel starts
6. If duel request is pending too long, server expires it (`PENDING_DUEL_TTL_MS = 20000`)

If requested `playerId` is already used, server reassigns a unique suffix.

## Core Messages

### Client -> Server

- `register`
- `join`
- `position`
- `sprite_update`
- `ping` / `pong`
- `duel_request`
- `duel_accept`
- `duel_decline`
- `duel_cancel`
- `duel_party`
- `duel_player_info`
- `duel_ready`
- `duel_choice`
- `duel_buffer`
- `duel_buffer_cmd`
- `duel_buffer_resp`
- `duel_buffer_ack`
- `duel_stage`
- `duel_end`

### Server -> Client

- `registered`
- `joined`
- `position` (relayed with optional `t`, `dur`, `mapRev`, `metaStable`, `metaHash`, `characterName`)
- `sprite_update`
- `player_disconnected`
- `ping` / `pong`
- duel validation replies may include `duel_declined` with `reason` when request cannot proceed
- duel relay messages:
  - `duel_request`, `duel_declined`, `duel_cancelled`, `duel_warp`
  - `duel_party`, `duel_player_info`, `duel_ready`, `duel_choice`
  - `duel_buffer`, `duel_buffer_cmd`, `duel_buffer_resp`, `duel_buffer_ack`
  - `duel_stage`, `duel_end`, `duel_opponent_disconnected`

Note: `duel_warp` currently carries empty `coords` and starts battle flow without physical map warp.

## Minimal Payload Examples

Register:

```json
{"type":"register","playerId":"player_abc","characterName":"RED"}
```

Join:

```json
{"type":"join","roomId":"default"}
```

Position:

```json
{
  "type":"position",
  "data":{"x":10,"y":15,"mapGroup":0,"mapId":3,"facing":1},
  "t":123456,
  "dur":240,
  "mapRev":4,
  "metaStable":true,
  "metaHash":"0:3@4"
}
```

## Runtime Behavior

- Room-based broadcast (`rooms` map).
- Per-client cached last position/sprite for late joiners.
- Heartbeat every 30s by default (`ping` from server; inactive clients are dropped).
  - Server marks a client alive on either `pong` or `ping`.
- Disconnect cleanup includes duel cancellation and opponent notification.
