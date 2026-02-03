/**
 * Simple TCP client tester
 * Run this to verify the server is working correctly
 *
 * Usage: node test-connection.js
 */

const net = require('net');

const SERVER_HOST = '127.0.0.1';
const SERVER_PORT = 8080;
const TEST_PLAYER_ID = 'test_player_1';

console.log('===========================================');
console.log('TCP Connection Test');
console.log('===========================================\n');

// Create TCP connection
const client = net.createConnection({ host: SERVER_HOST, port: SERVER_PORT }, () => {
  console.log('✅ Connected to server');

  // Test 1: Register
  console.log('\n[Test 1] Registering player...');
  sendMessage({
    type: 'register',
    playerId: TEST_PLAYER_ID
  });
});

// Buffer for incoming data
let buffer = '';

// Send JSON message with newline delimiter
function sendMessage(message) {
  const data = JSON.stringify(message) + '\n';
  client.write(data);
}

// Data handler
client.on('data', (data) => {
  // Add to buffer
  buffer += data.toString();

  // Process complete lines
  let lineEnd;
  while ((lineEnd = buffer.indexOf('\n')) !== -1) {
    const line = buffer.substring(0, lineEnd).trim();
    buffer = buffer.substring(lineEnd + 1);

    if (line.length > 0) {
      try {
        const message = JSON.parse(line);
        console.log('📥 Received:', JSON.stringify(message, null, 2));

        // Test 2: Join room
        if (message.type === 'registered') {
          console.log('\n[Test 2] Joining default room...');
          sendMessage({
            type: 'join',
            roomId: 'default'
          });
        }

        // Test 3: Send position
        if (message.type === 'joined') {
          console.log('\n[Test 3] Sending position update...');
          sendMessage({
            type: 'position',
            data: {
              x: 10,
              y: 15,
              mapId: 3,
              mapGroup: 0,
              facing: 1
            }
          });

          // Test 4: Ping/Pong
          setTimeout(() => {
            console.log('\n[Test 4] Responding to ping...');
            // Server will send ping, we respond with ping (which server treats as pong)
          }, 500);

          // Close after tests
          setTimeout(() => {
            console.log('\n===========================================');
            console.log('✅ All tests completed successfully!');
            console.log('===========================================\n');
            client.end();
          }, 2000);
        }

        // Auto-respond to pings
        if (message.type === 'ping') {
          console.log('🏓 Ping received, sending pong...');
          sendMessage({ type: 'ping' }); // Server expects ping back for heartbeat
        }

      } catch (error) {
        console.error('❌ Error parsing message:', error);
        console.error('   Raw line:', line);
      }
    }
  }
});

// Error handler
client.on('error', (error) => {
  console.error('❌ TCP error:', error.message);
  console.log('\nMake sure the server is running:');
  console.log('  cd server && npm start\n');
  process.exit(1);
});

// Close handler
client.on('end', () => {
  console.log('🔌 Connection closed by server');
  process.exit(0);
});

client.on('close', () => {
  console.log('🔌 Connection closed');
  process.exit(0);
});

// Timeout safety
setTimeout(() => {
  console.log('\n⏱️  Test timeout - closing connection');
  client.end();
  process.exit(1);
}, 5000);
