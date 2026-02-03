/**
 * Pokémon Co-op Framework - File-to-TCP Proxy
 *
 * Bridges the gap between mGBA Lua (file I/O) and TCP server (sockets)
 * - Watches client_outgoing.json → sends to server
 * - Receives from server → writes to client_incoming.json
 */

const net = require('net');
const fs = require('fs');
const path = require('path');

// Configuration
const SERVER_HOST = process.env.SERVER_HOST || '127.0.0.1';
const SERVER_PORT = process.env.SERVER_PORT || 8080;
const POLL_INTERVAL = 50; // Check files every 50ms

// File paths
const OUTGOING_FILE = path.join(__dirname, 'client_outgoing.json');
const INCOMING_FILE = path.join(__dirname, 'client_incoming.json');
const STATUS_FILE = path.join(__dirname, 'client_status.json');

// State
let tcpClient = null;
let connected = false;
let reconnectTimer = null;
let playerId = null;
let messageQueue = []; // Queue for incoming messages
let cachedRegister = null; // Cache register message for reconnects
let cachedJoin = null;     // Cache join message for reconnects

/**
 * Connect to TCP server
 */
function connectToServer() {
  if (tcpClient) {
    tcpClient.destroy();
  }

  console.log(`[Proxy] Connecting to ${SERVER_HOST}:${SERVER_PORT}...`);

  tcpClient = new net.Socket();
  let buffer = '';

  tcpClient.connect(SERVER_PORT, SERVER_HOST, () => {
    console.log('[Proxy] Connected to server!');
    connected = true;

    // Replay cached register+join on reconnect
    if (cachedRegister) {
      sendToServer(cachedRegister);
    }
    if (cachedJoin) {
      sendToServer(cachedJoin);
    }
  });

  // Receive data from server
  tcpClient.on('data', (data) => {
    buffer += data.toString();

    // Process complete lines
    let lineEnd;
    while ((lineEnd = buffer.indexOf('\n')) !== -1) {
      const line = buffer.substring(0, lineEnd).trim();
      buffer = buffer.substring(lineEnd + 1);

      if (line.length > 0) {
        try {
          const message = JSON.parse(line);
          handleServerMessage(message);
        } catch (err) {
          console.error('[Proxy] Failed to parse message:', err.message);
        }
      }
    }
  });

  tcpClient.on('close', () => {
    console.log('[Proxy] Connection closed');
    connected = false;

    // Reconnect after 2 seconds
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectToServer();
      }, 2000);
    }
  });

  tcpClient.on('error', (err) => {
    console.error('[Proxy] Connection error:', err.message);
    connected = false;
  });
}

/**
 * Send message to TCP server
 */
function sendToServer(message) {
  if (!connected || !tcpClient) {
    return false;
  }

  try {
    const jsonStr = JSON.stringify(message) + '\n';
    tcpClient.write(jsonStr);
    return true;
  } catch (err) {
    console.error('[Proxy] Failed to send:', err.message);
    return false;
  }
}

/**
 * Handle message from server
 */
function handleServerMessage(message) {
  // Add to queue (flushed to file on next poll interval)
  messageQueue.push(message);

  // Log important messages
  if (message.type === 'registered') {
    console.log(`[Proxy] Registered with ID: ${message.playerId}`);
  } else if (message.type === 'joined') {
    console.log(`[Proxy] Joined room: ${message.roomId}`);
  }
}

/**
 * Flush queued incoming messages to file for Lua to read
 */
function flushIncomingQueue() {
  if (messageQueue.length === 0) return;

  try {
    fs.writeFileSync(INCOMING_FILE, JSON.stringify(messageQueue));
    messageQueue = [];
  } catch (err) {
    console.error('[Proxy] Failed to write incoming file:', err.message);
  }
}

/**
 * Poll outgoing file for messages from Lua
 */
function pollOutgoingFile() {
  try {
    if (!fs.existsSync(OUTGOING_FILE)) {
      return;
    }

    const content = fs.readFileSync(OUTGOING_FILE, 'utf8').trim();

    if (content) {
      // Clear file immediately to avoid re-reading
      fs.writeFileSync(OUTGOING_FILE, '');

      try {
        const parsed = JSON.parse(content);

        // Support both single message and array of messages
        const messages = Array.isArray(parsed) ? parsed : [parsed];

        if (connected) {
          for (const message of messages) {
            // Cache register/join for reconnects
            if (message.type === 'register') cachedRegister = message;
            if (message.type === 'join') cachedJoin = message;
            sendToServer(message);
          }
        }
      } catch (err) {
        // Ignore parse errors (file might be mid-write)
      }
    }
  } catch (err) {
    // Ignore read errors (file might not exist yet)
  }
}

/**
 * Check status file for control commands
 */
function checkStatusFile() {
  try {
    if (!fs.existsSync(STATUS_FILE)) {
      return;
    }

    const content = fs.readFileSync(STATUS_FILE, 'utf8').trim();
    if (!content) return;

    const status = JSON.parse(content);

    if (status.action === 'disconnect') {
      console.log('[Proxy] Disconnect requested');
      if (tcpClient) {
        tcpClient.end();
      }
      process.exit(0);
    }
  } catch (err) {
    // Ignore errors
  }
}

/**
 * Initialize and start proxy
 */
function start() {
  console.log('╔═══════════════════════════════════════════════════════╗');
  console.log('║   Pokémon Co-op Framework - File Proxy (Client 2)    ║');
  console.log('╚═══════════════════════════════════════════════════════╝');
  console.log(`[Proxy] Server: ${SERVER_HOST}:${SERVER_PORT}`);
  console.log('[Proxy] Poll interval: ' + POLL_INTERVAL + 'ms');
  console.log('[Proxy] Outgoing file: ' + OUTGOING_FILE);
  console.log('[Proxy] Incoming file: ' + INCOMING_FILE);
  console.log('');

  // Create empty files if they don't exist
  [OUTGOING_FILE, INCOMING_FILE].forEach(file => {
    if (!fs.existsSync(file)) {
      fs.writeFileSync(file, '');
    }
  });

  // Connect to server
  connectToServer();

  // Start polling
  setInterval(() => {
    pollOutgoingFile();
    flushIncomingQueue();
    checkStatusFile();
  }, POLL_INTERVAL);

  console.log('[Proxy] Started successfully!');
  console.log('[Proxy] Waiting for mGBA client...\n');
}

// Cleanup on exit
process.on('SIGINT', () => {
  console.log('\n[Proxy] Shutting down...');
  if (tcpClient) {
    tcpClient.end();
  }
  process.exit(0);
});

// Start
start();
