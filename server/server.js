/**
 * Pokémon Co-op Framework - TCP Relay Server
 *
 * Relays position data between connected mGBA clients via raw TCP
 * Supports multiple game rooms/sessions
 *
 * Protocol: JSON messages delimited by newline (\n)
 */

const net = require('net');

// Configuration
const PORT = process.env.PORT || 8080;
const HEARTBEAT_INTERVAL = 30000; // 30s

// Duel room coordinates — MAP_BATTLE_COLOSSEUM_2P (28:24)
const DUEL_ROOM = {
  mapGroup: 28,
  mapId: 24,
  playerAX: 3,
  playerAY: 5,
  playerBX: 10,
  playerBY: 5
};

// Client storage
const clients = new Map();
const rooms = new Map();

// Active duels tracking (for battle synchronization)
const activeDuels = new Map();  // duelId -> {playerA, playerB, state}

/**
 * Client object structure
 * @typedef {Object} Client
 * @property {net.Socket} socket - TCP socket connection
 * @property {string} id - Unique client ID
 * @property {string} roomId - Current room ID
 * @property {boolean} alive - Heartbeat status
 * @property {Object} lastPosition - Last known position data
 * @property {string} buffer - Incomplete message buffer
 */

/**
 * Broadcast message to all clients in a room except sender
 */
function broadcastToRoom(roomId, senderId, message) {
  const room = rooms.get(roomId);
  if (!room) return;

  const jsonMessage = JSON.stringify(message) + '\n';

  room.forEach(clientId => {
    if (clientId !== senderId) {
      const client = clients.get(clientId);
      if (client && !client.socket.destroyed) {
        client.socket.write(jsonMessage);
      }
    }
  });
}

/**
 * Send message to specific client
 */
function sendToClient(client, message) {
  if (client && !client.socket.destroyed) {
    const jsonMessage = JSON.stringify(message) + '\n';
    client.socket.write(jsonMessage);
  }
}

/**
 * Add client to room
 */
function joinRoom(clientId, roomId) {
  if (!rooms.has(roomId)) {
    rooms.set(roomId, new Set());
  }
  rooms.get(roomId).add(clientId);

  const client = clients.get(clientId);
  if (client) {
    client.roomId = roomId;
  }

  console.log(`[Room] Client ${clientId} joined room ${roomId}`);
}

/**
 * Remove client from room
 */
function leaveRoom(clientId) {
  const client = clients.get(clientId);
  if (!client || !client.roomId) return;

  const room = rooms.get(client.roomId);
  if (room) {
    room.delete(clientId);
    if (room.size === 0) {
      rooms.delete(client.roomId);
      console.log(`[Room] Room ${client.roomId} deleted (empty)`);
    }
  }

  console.log(`[Room] Client ${clientId} left room ${client.roomId}`);
  client.roomId = null;
}

/**
 * Handle incoming messages
 */
function handleMessage(client, messageStr) {
  try {
    const message = JSON.parse(messageStr);

    switch (message.type) {
      case 'register':
        // Client registration
        client.id = message.playerId || generateId();
        clients.set(client.id, client);

        sendToClient(client, {
          type: 'registered',
          playerId: client.id
        });

        console.log(`[Register] Client registered: ${client.id}`);
        break;

      case 'join':
        // Join a room
        const roomId = message.roomId || 'default';
        joinRoom(client.id, roomId);

        sendToClient(client, {
          type: 'joined',
          roomId: roomId
        });

        // Send existing players' last known positions and sprites to the new client
        const room = rooms.get(roomId);
        if (room) {
          room.forEach(existingId => {
            if (existingId !== client.id) {
              const existing = clients.get(existingId);
              if (existing) {
                if (existing.lastPosition) {
                  sendToClient(client, {
                    type: 'position',
                    playerId: existingId,
                    data: existing.lastPosition
                  });
                }
                if (existing.lastSprite) {
                  sendToClient(client, {
                    type: 'sprite_update',
                    playerId: existingId,
                    data: existing.lastSprite
                  });
                }
              }
            }
          });
        }
        break;

      case 'position':
        // Position update
        if (!client.roomId) {
          console.warn(`[Position] Client ${client.id} not in a room`);
          return;
        }

        client.lastPosition = message.data;

        // Relay to other clients in room (include timestamp + duration hint for interpolation)
        broadcastToRoom(client.roomId, client.id, {
          type: 'position',
          playerId: client.id,
          data: message.data,
          t: message.t,
          dur: message.dur
        });
        break;

      case 'sprite_update':
        // Sprite data relay
        if (!client.roomId) return;

        // Cache last sprite for late joiners
        client.lastSprite = message.data;

        broadcastToRoom(client.roomId, client.id, {
          type: 'sprite_update',
          playerId: client.id,
          data: message.data
        });
        break;

      case 'duel_request':
        // Duel warp request — forward to target player only
        if (!client.roomId) return;

        const targetClient = clients.get(message.targetId);
        if (targetClient && targetClient.roomId === client.roomId) {
          // Store pending duel on the requester
          client.pendingDuel = { targetId: message.targetId };

          sendToClient(targetClient, {
            type: 'duel_request',
            requesterId: client.id,
            requesterName: client.id
          });

          console.log(`[Duel] Request from ${client.id} to ${message.targetId}`);
        }
        break;

      case 'duel_accept': {
        // Duel warp accepted — coordinate teleportation for both players
        if (!client.roomId) return;

        const requester = clients.get(message.requesterId);
        if (!requester || !requester.pendingDuel) {
          break;
        }

        // Verify the duel matches (requester targeted this accepter) and same room
        if (requester.pendingDuel.targetId !== client.id
          || requester.roomId !== client.roomId) {
          break;
        }

        // Clear pending duel
        requester.pendingDuel = null;

        // Set up duel opponent relationship (for party/choice relay)
        requester.duelOpponent = client.id;
        client.duelOpponent = requester.id;

        // Send warp command to both players with different spawn positions
        // Requester is player A (master), accepter is player B (slave)
        sendToClient(requester, {
          type: 'duel_warp',
          coords: {
            mapGroup: DUEL_ROOM.mapGroup,
            mapId: DUEL_ROOM.mapId,
            x: DUEL_ROOM.playerAX,
            y: DUEL_ROOM.playerAY
          },
          isMaster: true
        });

        sendToClient(client, {
          type: 'duel_warp',
          coords: {
            mapGroup: DUEL_ROOM.mapGroup,
            mapId: DUEL_ROOM.mapId,
            x: DUEL_ROOM.playerBX,
            y: DUEL_ROOM.playerBY
          },
          isMaster: false
        });

        console.log(`[Duel] Warping ${requester.id} (master) and ${client.id} (slave) to Battle Colosseum`);
        break;
      }

      case 'duel_decline': {
        // Duel declined — notify requester
        if (!client.roomId) return;

        const declinedRequester = clients.get(message.requesterId);
        if (declinedRequester) {
          declinedRequester.pendingDuel = null;
          sendToClient(declinedRequester, {
            type: 'duel_declined',
            playerId: client.id
          });
        }

        console.log(`[Duel] ${client.id} declined duel from ${message.requesterId}`);
        break;
      }

      case 'duel_party': {
        // Player sends their party data for PvP battle
        if (!client.roomId) return;

        // Store party data on client
        client.duelParty = message.data;

        // Relay to duel opponent
        if (client.duelOpponent) {
          const opponent = clients.get(client.duelOpponent);
          if (opponent) {
            sendToClient(opponent, {
              type: 'duel_party',
              playerId: client.id,
              data: message.data
            });
            console.log(`[Duel] Party data relayed from ${client.id} to ${client.duelOpponent}`);
          }
        }
        break;
      }

      case 'duel_choice': {
        // Player sends their battle choice (move/switch)
        if (!client.roomId || !client.duelOpponent) return;

        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
          sendToClient(opponent, {
            type: 'duel_choice',
            playerId: client.id,
            choice: message.choice,
            rng: message.rng
          });
        }
        break;
      }

      case 'duel_rng_sync': {
        // Master sends RNG sync to slave
        if (!client.roomId || !client.duelOpponent) return;

        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
          sendToClient(opponent, {
            type: 'duel_rng_sync',
            rng: message.rng
          });
        }
        break;
      }

      case 'duel_end': {
        // Battle finished, cleanup duel state
        if (client.duelOpponent) {
          const opponent = clients.get(client.duelOpponent);
          if (opponent) {
            sendToClient(opponent, {
              type: 'duel_end',
              playerId: client.id,
              outcome: message.outcome
            });
            opponent.duelOpponent = null;
            opponent.duelParty = null;
          }
        }
        client.duelOpponent = null;
        client.duelParty = null;
        console.log(`[Duel] Battle ended for ${client.id}, outcome: ${message.outcome}`);
        break;
      }

      case 'ping':
        // Client-initiated ping
        client.alive = true;
        sendToClient(client, { type: 'pong' });
        break;

      case 'pong':
        // Heartbeat response from client
        client.alive = true;
        break;

      default:
        console.warn(`[Message] Unknown message type: ${message.type}`);
    }
  } catch (error) {
    console.error('[Error] Failed to parse message:', error);
    console.error('[Error] Message was:', messageStr);
  }
}

/**
 * Generate unique ID
 */
function generateId() {
  return `player_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Handle client disconnection
 */
function handleDisconnect(client) {
  if (client.id) {
    // Guard against double-disconnect (end + close both fire)
    if (!clients.has(client.id)) return;

    // Clean up pending duel where this client was the requester
    if (client.pendingDuel) {
      const target = clients.get(client.pendingDuel.targetId);
      if (target) {
        sendToClient(target, { type: 'duel_cancelled', requesterId: client.id });
      }
      client.pendingDuel = null;
    }

    // Clean up active duel (opponent needs to be notified)
    if (client.duelOpponent) {
      const opponent = clients.get(client.duelOpponent);
      if (opponent) {
        sendToClient(opponent, { type: 'duel_opponent_disconnected', playerId: client.id });
        opponent.duelOpponent = null;
        opponent.duelParty = null;
      }
      client.duelOpponent = null;
      client.duelParty = null;
    }

    // Clean up pending duels targeting this client (other players requested us)
    clients.forEach((otherClient) => {
      if (otherClient.pendingDuel && otherClient.pendingDuel.targetId === client.id) {
        sendToClient(otherClient, { type: 'duel_declined', playerId: client.id });
        otherClient.pendingDuel = null;
      }
    });

    // Broadcast disconnection to room BEFORE removing from room
    if (client.roomId) {
      broadcastToRoom(client.roomId, client.id, {
        type: 'player_disconnected',
        playerId: client.id
      });
    }
    leaveRoom(client.id);
    clients.delete(client.id);
    console.log(`[Disconnect] Client ${client.id} disconnected`);
  } else {
    console.log('[Disconnect] Unregistered client disconnected');
  }
}

/**
 * Create TCP server
 */
const server = net.createServer((socket) => {
  // Create client object
  const client = {
    socket: socket,
    id: null,
    roomId: null,
    alive: true,
    lastPosition: null,
    buffer: ''
  };

  console.log(`[Connect] New client connected from ${socket.remoteAddress}:${socket.remotePort}`);

  // Data handler - process line-delimited JSON
  socket.on('data', (data) => {
    // Add to buffer
    client.buffer += data.toString();

    // Process complete lines
    let lineEnd;
    while ((lineEnd = client.buffer.indexOf('\n')) !== -1) {
      const line = client.buffer.substring(0, lineEnd).trim();
      client.buffer = client.buffer.substring(lineEnd + 1);

      if (line.length > 0) {
        handleMessage(client, line);
      }
    }

    // Prevent buffer overflow
    if (client.buffer.length > 10000) {
      console.warn(`[Warning] Client buffer overflow, clearing`);
      client.buffer = '';
    }
  });

  // End/close handler
  socket.on('end', () => {
    handleDisconnect(client);
  });

  socket.on('close', () => {
    handleDisconnect(client);
  });

  // Error handler
  socket.on('error', (error) => {
    console.error('[Error] Socket error:', error.message);
    handleDisconnect(client);
  });
});

/**
 * Heartbeat check interval
 */
const heartbeatInterval = setInterval(() => {
  clients.forEach((client, id) => {
    if (!client.alive) {
      console.log(`[Heartbeat] Terminating inactive client ${id}`);
      // Broadcast disconnection before cleanup
      if (client.roomId) {
        broadcastToRoom(client.roomId, id, {
          type: 'player_disconnected',
          playerId: id
        });
      }
      client.socket.destroy();
      leaveRoom(id);
      clients.delete(id);
      return;
    }

    client.alive = false;
    // Send ping message
    sendToClient(client, { type: 'ping' });
  });
}, HEARTBEAT_INTERVAL);

/**
 * Graceful shutdown
 */
let shuttingDown = false;

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;

  console.log('\n[Shutdown] Closing server...');
  clearInterval(heartbeatInterval);

  clients.forEach((client) => {
    client.socket.destroy();
  });

  server.close(() => {
    console.log('[Shutdown] Server closed');
    process.exit(0);
  });

  // Force exit if server.close() hangs (e.g. stuck connections)
  setTimeout(() => {
    console.log('[Shutdown] Forced exit');
    process.exit(0);
  }, 2000);
}

// Ctrl+C
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

// stdin: type "q" or "quit" to stop
process.stdin.setEncoding('utf8');
process.stdin.on('data', (data) => {
  const input = data.trim().toLowerCase();
  if (input === 'q' || input === 'quit' || input === 'exit') {
    shutdown();
  }
});

/**
 * Start server
 */
server.listen(PORT, () => {
  console.log('╔═══════════════════════════════════════════════════════╗');
  console.log('║   Pokémon Co-op Framework - TCP Server               ║');
  console.log('╚═══════════════════════════════════════════════════════╝');
  console.log(`[Server] Listening on port ${PORT}`);
  console.log(`[Server] Protocol: TCP with JSON line-delimited messages`);
  console.log(`[Server] Connect to: ${PORT}`);
  console.log('[Server] Ready to accept connections');
  console.log('[Server] Type "q" or "quit" to stop — Ctrl+C also works\n');
});

/**
 * Server error handler
 */
server.on('error', (error) => {
  console.error('[Error] Server error:', error);
  process.exit(1);
});

// Export for testing
module.exports = { server, clients, rooms };
