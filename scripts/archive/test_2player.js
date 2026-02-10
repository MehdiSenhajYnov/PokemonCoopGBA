/**
 * 2-Player PvP Battle Test Orchestrator
 *
 * Launches the server + 2 mGBA instances with auto-duel wrappers.
 * Instance 1 (requester): auto-sends duel_request after seeing the other player
 * Instance 2 (accepter): auto-accepts incoming duel requests
 *
 * Usage: node scripts/ToUse/test_2player.js
 * Press Ctrl+C to stop and clean up.
 */

const { spawn, execSync } = require('child_process');
const path = require('path');

const BASE = path.resolve(__dirname, '../..');
const MGBA = path.join(BASE, 'mgba', 'mGBA.exe');
const ROM = path.join(BASE, 'rom', 'Pokemon RunBun.gba');
const SS1 = path.join(BASE, 'rom', 'Pokemon RunBun.ss1');
const REQUESTER_LUA = path.join(BASE, 'client', 'auto_duel_requester.lua');
const ACCEPTER_LUA = path.join(BASE, 'client', 'auto_duel_accepter.lua');
const SERVER_JS = path.join(BASE, 'server', 'server.js');

const PORT = 8080;
const BATTLE_MONITOR_DURATION = 180; // seconds to monitor battle

let serverProc, mgba1, mgba2;
const registeredPlayers = [];
let battlePhaseDetected = false;

const sleep = ms => new Promise(r => setTimeout(r, ms));

function timestamp() {
  return new Date().toISOString().substr(11, 12);
}

function log(tag, msg) {
  console.log(`[${timestamp()}] [${tag}] ${msg}`);
}

// Kill existing processes
function killExisting() {
  try { execSync('taskkill /F /IM mGBA.exe 2>nul', { stdio: 'ignore' }); } catch {}
  // Don't kill node processes indiscriminately — just specific server on port 8080
  try {
    const result = execSync('netstat -ano | findstr :8080 | findstr LISTEN', { encoding: 'utf8' });
    const pid = result.trim().split(/\s+/).pop();
    if (pid && pid !== '0') {
      execSync(`taskkill /F /PID ${pid}`, { stdio: 'ignore' });
    }
  } catch {}
}

async function main() {
  console.log('');
  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║   2-Player PvP Battle Test                               ║');
  console.log('╠═══════════════════════════════════════════════════════════╣');
  console.log('║   Instance 1: auto_duel_requester (master)               ║');
  console.log('║   Instance 2: auto_duel_accepter  (slave)                ║');
  console.log('║   Battle should start automatically after ~5 seconds     ║');
  console.log('╚═══════════════════════════════════════════════════════════╝');
  console.log('');

  // Step 0: Kill existing processes
  log('SETUP', 'Killing existing mGBA and server processes...');
  killExisting();
  await sleep(1000);

  // Step 1: Start server
  log('SETUP', 'Starting server...');
  serverProc = spawn('node', [SERVER_JS], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, PORT: PORT.toString() }
  });

  serverProc.stdout.on('data', d => {
    const lines = d.toString().split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      log('SERVER', trimmed);

      // Detect player registrations
      const regMatch = trimmed.match(/\[Register\] Client registered: (\S+)/);
      if (regMatch && !registeredPlayers.includes(regMatch[1])) {
        registeredPlayers.push(regMatch[1]);
        log('TEST', `>>> Player ${registeredPlayers.length}/2 connected: ${regMatch[1]}`);
      }

      // Detect duel events
      if (trimmed.includes('[Duel]')) {
        log('TEST', `>>> ${trimmed}`);
      }

      // Detect battle phase
      if (trimmed.includes('duel_party') || trimmed.includes('Party data')) {
        battlePhaseDetected = true;
        log('TEST', '>>> BATTLE PHASE DETECTED — party data exchanged!');
      }
    }
  });

  serverProc.stderr.on('data', d => {
    const trimmed = d.toString().trim();
    if (trimmed) log('SERVER-ERR', trimmed);
  });

  await sleep(2000);

  // Step 2: Launch mGBA instance 1 (requester / master)
  log('SETUP', 'Launching mGBA #1 (requester/master)...');
  mgba1 = spawn(MGBA, ['-t', SS1, '--script', REQUESTER_LUA, ROM], {
    stdio: 'ignore',
    detached: true
  });
  mgba1.unref();
  log('SETUP', `mGBA #1 PID: ${mgba1.pid}`);

  await sleep(2000);

  // Step 3: Launch mGBA instance 2 (accepter / slave)
  log('SETUP', 'Launching mGBA #2 (accepter/slave)...');
  mgba2 = spawn(MGBA, ['-t', SS1, '--script', ACCEPTER_LUA, ROM], {
    stdio: 'ignore',
    detached: true
  });
  mgba2.unref();
  log('SETUP', `mGBA #2 PID: ${mgba2.pid}`);

  // Step 4: Wait for both to connect
  log('TEST', 'Waiting for both players to connect (up to 15s)...');
  const deadline = Date.now() + 15000;
  while (registeredPlayers.length < 2 && Date.now() < deadline) {
    await sleep(500);
  }

  if (registeredPlayers.length < 2) {
    log('FAIL', `Only ${registeredPlayers.length}/2 players connected within 15s`);
    log('FAIL', 'Check that mGBA instances started correctly');
    cleanup();
    return;
  }

  log('TEST', `Both players connected! IDs: ${registeredPlayers.join(', ')}`);
  log('TEST', '');
  log('TEST', 'Auto-duel should trigger in ~3 seconds (180 frames)...');
  log('TEST', 'Watch both mGBA windows for battle progression.');
  log('TEST', '');
  log('TEST', `Monitoring for ${BATTLE_MONITOR_DURATION}s... (Ctrl+C to stop)`);

  // Step 5: Monitor
  const startTime = Date.now();
  while (Date.now() - startTime < BATTLE_MONITOR_DURATION * 1000) {
    await sleep(5000);
    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    log('TEST', `[${elapsed}s/${BATTLE_MONITOR_DURATION}s] Players: ${registeredPlayers.length}, Battle phase: ${battlePhaseDetected}`);
  }

  log('TEST', 'Test monitoring complete.');
  log('TEST', 'Check both mGBA windows to verify battle worked for both players.');

  // Don't auto-cleanup — let user inspect the windows
  log('TEST', 'Press Ctrl+C to clean up processes.');
}

function cleanup() {
  log('CLEANUP', 'Stopping processes...');
  if (serverProc && !serverProc.killed) {
    serverProc.kill();
  }
  // mGBA instances are detached, kill them via taskkill
  try { execSync('taskkill /F /IM mGBA.exe 2>nul', { stdio: 'ignore' }); } catch {}
  log('CLEANUP', 'Done');
  process.exit(0);
}

process.on('SIGINT', cleanup);
process.on('SIGTERM', cleanup);

main().catch(e => {
  console.error(e);
  cleanup();
});
