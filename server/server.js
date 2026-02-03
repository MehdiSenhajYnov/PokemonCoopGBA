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

// Client storage
const clients = new Map();
const rooms = new Map();

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
        break;

      case 'position':
        // Position update
        if (!client.roomId) {
          console.warn(`[Position] Client ${client.id} not in a room`);
          return;
        }

        client.lastPosition = message.data;

        // Relay to other clients in room (include timestamp for interpolation)
        broadcastToRoom(client.roomId, client.id, {
          type: 'position',
          playerId: client.id,
          data: message.data,
          t: message.t
        });
        break;

      case 'duel_request':
        // Duel warp request
        if (!client.roomId) return;

        broadcastToRoom(client.roomId, client.id, {
          type: 'duel_request',
          playerId: client.id,
          targetId: message.targetId
        });

        console.log(`[Duel] Request from ${client.id} to ${message.targetId}`);
        break;

      case 'duel_accept':
        // Duel warp accepted
        if (!client.roomId) return;

        broadcastToRoom(client.roomId, client.id, {
          type: 'duel_accept',
          playerId: client.id,
          requesterId: message.requesterId
        });

        console.log(`[Duel] ${client.id} accepted duel from ${message.requesterId}`);
        break;

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
 * Server shutdown handler
 */
process.on('SIGINT', () => {
  console.log('\n[Shutdown] Closing server...');
  clearInterval(heartbeatInterval);

  clients.forEach((client) => {
    client.socket.end();
  });

  server.close(() => {
    console.log('[Shutdown] Server closed');
    process.exit(0);
  });
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
  console.log('[Server] Ready to accept connections\n');
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
