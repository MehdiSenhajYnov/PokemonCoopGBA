# Pokémon Co-op Server

TCP relay server for synchronizing player positions between mGBA clients.

**Note**: Utilise TCP brut au lieu de WebSocket car mGBA Lua ne supporte que `socket.tcp()`

## Installation

```bash
npm install
```

## Usage

```bash
npm start
```

The server will start on port 8080 by default.

## Environment Variables

- `PORT`: Server port (default: 8080)

## TCP Protocol (JSON Line-Delimited)

Messages envoyés en JSON, un par ligne, terminés par `\n`

### Client -> Server

#### Register
```json
{
  "type": "register",
  "playerId": "optional-custom-id"
}
```

#### Join Room
```json
{
  "type": "join",
  "roomId": "room-name"
}
```

#### Position Update
```json
{
  "type": "position",
  "data": {
    "x": 10,
    "y": 15,
    "mapId": 3,
    "mapGroup": 0,
    "facing": 1
  }
}
```

#### Duel Request
```json
{
  "type": "duel_request",
  "targetId": "player-id"
}
```

### Server -> Client

#### Registered
```json
{
  "type": "registered",
  "playerId": "assigned-id"
}
```

#### Position Broadcast
```json
{
  "type": "position",
  "playerId": "sender-id",
  "data": {
    "x": 10,
    "y": 15,
    "mapId": 3,
    "mapGroup": 0,
    "facing": 1
  }
}
```

## Features

- Room-based multiplayer sessions
- Automatic heartbeat/keepalive
- Client disconnection handling
- Position broadcast to room members
- Duel request/accept system

## Architecture

- **Clients Map**: Stores all connected clients
- **Rooms Map**: Organizes clients into game sessions
- **Heartbeat**: 30s interval to detect dead connections

## TCP vs WebSocket

**Pourquoi TCP brut?**
- mGBA Lua n'a pas de support WebSocket natif
- `socket.tcp()` est la seule API réseau disponible
- Protocol JSON simple, ligne par ligne (`\n` delimiter)
- Plus facile à implémenter côté client Lua
