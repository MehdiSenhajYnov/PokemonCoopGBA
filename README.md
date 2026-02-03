# Pokémon Unified Co-op Framework

**Seamless multiplayer for Pokémon GBA ROMs using mGBA + Lua + TCP**

![Status](https://img.shields.io/badge/status-alpha-orange)
![Version](https://img.shields.io/badge/version-0.1.0-blue)
![Platform](https://img.shields.io/badge/platform-mGBA-green)

## Features

- **Ghosting**: See other players in real-time on your map
- **Duel Warp**: Synchronized teleportation to Link Battle room
- **Generic Architecture**: Multi-ROM support via config profiles
- **Safe Memory Access**: Protected HAL with crash prevention
- **TCP Sync**: Low-latency position updates via raw TCP sockets

## Quick Start

### Prerequisites
- [Node.js 18+](https://nodejs.org/)
- [mGBA 0.10.0+](https://mgba.io/downloads.html)
- Pokémon Run & Bun ROM (primary target)

### Step 1: Start the Server

```bash
cd server
npm install
npm start
```

You should see:
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - TCP Server               ║
╚═══════════════════════════════════════════════════════╝
[Server] Listening on port 8080
```

### Step 2: Load the Lua Script

1. Open mGBA
2. Load your Pokémon ROM
3. Go to **Tools → Scripting**
4. Click **File → Load Script...**
5. Navigate to `client/main.lua` and load it

### Step 3: Verify

You should see in the mGBA console:
```
======================================
Pokémon Co-op Framework v0.1.0
======================================
[PokéCoop] Initializing...
[PokéCoop] Detected ROM: [ROM_ID]
[PokéCoop] Player ID: player_xxxxx
[PokéCoop] Initialization complete!
```

In-game overlay will show your coordinates and map info.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete project documentation and instructions
- **[client/README.md](client/README.md)** - Lua client API reference
- **[server/README.md](server/README.md)** - TCP server protocol
- **[docs/TESTING.md](docs/TESTING.md)** - Testing procedures
- **[docs/MEMORY_GUIDE.md](docs/MEMORY_GUIDE.md)** - Memory offset scanning guide
- **[docs/CHANGELOG.md](docs/CHANGELOG.md)** - Version history

## Project Structure

```
PokemonCoop/
├── CLAUDE.md              # Full project specs & instructions
├── server/                # TCP relay server (Node.js)
│   ├── server.js
│   └── README.md
├── client/                # mGBA Lua scripts
│   ├── main.lua           # Main entry point
│   ├── hal.lua            # Hardware abstraction layer
│   └── README.md
├── config/                # ROM-specific profiles
│   └── emerald_us.lua     # Pokémon Emerald US config
└── docs/                  # Additional documentation
```

## Current Status

**Phase 1: Foundation** (In Progress)
- ✅ TCP server skeleton
- ✅ Lua HAL with safe memory access
- ✅ Position reading (Emerald reference)
- ⏳ Run & Bun offset discovery (CRITICAL - see docs/MEMORY_GUIDE.md)
- ⏳ TCP client integration

**Phase 2: Ghosting** (Planned)
- Position synchronization
- Ghost rendering overlay
- Movement interpolation

**Phase 3: Duel Warp** (Planned)
- Trigger system
- Synchronized teleportation
- Battle initiation

## Tech Stack

- **Client**: Lua (mGBA scripting API with socket.tcp())
- **Server**: Node.js + TCP (net library)
- **Communication**: JSON over raw TCP sockets
- **Target**: Game Boy Advance ROMs

**Note**: TCP used instead of WebSocket because mGBA Lua only supports `socket.tcp()`

## Troubleshooting

### Script won't load
- Ensure mGBA has Lua scripting support
- Check file paths are correct
- Verify directory structure is intact

### No position data
- Verify ROM is supported (Emerald US currently)
- Try walking around to trigger position updates
- Check console for error messages

### Server won't start
- Check if port 8080 is in use
- Try changing PORT in server.js

For detailed troubleshooting, see [docs/TESTING.md](docs/TESTING.md)

## Contributing

This is an early-stage project. Areas needing help:
- Memory offset discovery for Run & Bun
- Lua TCP client optimization
- Additional ROM profiles
- Ghost sprite rendering

## Resources

- [mGBA Scripting Documentation](https://mgba.io/docs/scripting.html)
- [Pokémon Emerald Decomp](https://github.com/pret/pokeemerald) (reference for base engine)
- [Node.js TCP/Net](https://nodejs.org/api/net.html)
- [GBA Memory Map](https://problemkaputt.de/gbatek.htm)

## License

MIT License - See LICENSE file for details

---

**For complete documentation, see [CLAUDE.md](CLAUDE.md)**

Built with ❤️ for the Pokémon ROM hacking community
