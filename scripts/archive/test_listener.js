// Tiny TCP listener that receives log data from mGBA Lua scripts
// Usage: node scripts/ToUse/test_listener.js
// Writes received data to battle_init_results.txt

const net = require('net');
const fs = require('fs');
const path = require('path');

const PORT = 9999;
const outFile = path.join(__dirname, '..', '..', 'battle_init_results.txt');
let allData = '';

const server = net.createServer((sock) => {
  console.log('[Listener] Client connected');

  sock.on('data', (data) => {
    const text = data.toString();
    allData += text;
    process.stdout.write(text);
  });

  sock.on('end', () => {
    console.log('\n[Listener] Client disconnected');
    fs.writeFileSync(outFile, allData);
    console.log(`[Listener] Results written to: ${outFile}`);
    server.close();
  });

  sock.on('error', (err) => {
    console.log('[Listener] Socket error:', err.message);
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[Listener] Listening on 127.0.0.1:${PORT}`);
  console.log('[Listener] Waiting for mGBA script to connect...');
});

// Auto-close after 45 seconds if no connection
setTimeout(() => {
  if (allData.length === 0) {
    console.log('[Listener] Timeout - no data received');
  } else {
    fs.writeFileSync(outFile, allData);
    console.log(`[Listener] Timeout - saved ${allData.length} bytes`);
  }
  server.close();
  process.exit(0);
}, 45000);
