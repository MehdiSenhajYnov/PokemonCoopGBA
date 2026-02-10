const net = require('net');
const fs = require('fs');
let data = '';
const s = net.createServer(c => {
  console.log('[TCP] Client connected');
  c.on('data', b => { data += b; process.stdout.write(b.toString()); });
  c.on('end', () => {
    fs.writeFileSync('battle_test_log.txt', data);
    console.log('\n[TCP] Connection closed, log saved to battle_test_log.txt');
  });
});
s.listen(9999, () => console.log('[TCP] Listening on 9999'));
setTimeout(() => {
  if (data) fs.writeFileSync('battle_test_log.txt', data);
  console.log('[TCP] Timeout, shutting down');
  s.close();
  process.exit();
}, 180000);
