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
const PORT = process.env.PORT || 3333;
const HEARTBEAT_INTERVAL = 30000; // 30s
const PENDING_DUEL_TTL_MS = 20000; // stale pending request guard
const FACING_TO_DELTA = {
  1: { dx: 0, dy: 1 },   // down
  2: { dx: 0, dy: -1 },  // up
  3: { dx: -1, dy: 0 },  // left
  4: { dx: 1, dy: 0 }    // right
};

// Duel: no physical warp — battle starts from overworld (GBA-PK style)

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
 * Notify requester that duel request cannot proceed.
 */
function sendDuelDeclined(requester, targetId, reason) {
  if (!requester) return;
  sendToClient(requester, {
    type: 'duel_declined',
    playerId: targetId || null,
    reason: reason || 'declined'
  });
}

function clearExpiredPendingDuel(client) {
  if (!client || !client.pendingDuel) return false;
  const createdAt = client.pendingDuel.createdAt;
  if (!createdAt || (Date.now() - createdAt) > PENDING_DUEL_TTL_MS) {
    client.pendingDuel = null;
    return true;
  }
  return false;
}

function toFiniteNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Duel requests are allowed only when players are adjacent and facing each other.
 */
function validateFaceToFaceDuel(requester, target) {
  const requesterPos = requester && requester.lastPosition;
  const targetPos = target && target.lastPosition;
  if (!requesterPos || !targetPos) {
    return { ok: false, reason: 'position_unknown', detail: 'missing_position' };
  }

  const rx = toFiniteNumber(requesterPos.x);
  const ry = toFiniteNumber(requesterPos.y);
  const tx = toFiniteNumber(targetPos.x);
  const ty = toFiniteNumber(targetPos.y);
  const requesterMapId = toFiniteNumber(requesterPos.mapId);
  const requesterMapGroup = toFiniteNumber(requesterPos.mapGroup);
  const targetMapId = toFiniteNumber(targetPos.mapId);
  const targetMapGroup = toFiniteNumber(targetPos.mapGroup);
  if (
    rx === null || ry === null || tx === null || ty === null
    || requesterMapId === null || requesterMapGroup === null
    || targetMapId === null || targetMapGroup === null
  ) {
    return { ok: false, reason: 'position_unknown', detail: 'invalid_position_fields' };
  }

  if (requesterMapId !== targetMapId || requesterMapGroup !== targetMapGroup) {
    return { ok: false, reason: 'different_map', detail: 'map_mismatch' };
  }

  const dx = tx - rx;
  const dy = ty - ry;
  const manhattan = Math.abs(dx) + Math.abs(dy);
  if (manhattan !== 1) {
    return { ok: false, reason: 'not_face_to_face', detail: `manhattan=${manhattan}` };
  }

  const requesterFacing = toFiniteNumber(requesterPos.facing);
  const targetFacing = toFiniteNumber(targetPos.facing);
  const requesterDelta = FACING_TO_DELTA[requesterFacing];
  const targetDelta = FACING_TO_DELTA[targetFacing];
  if (!requesterDelta || !targetDelta) {
    return { ok: false, reason: 'not_face_to_face', detail: 'invalid_facing' };
  }

  const requesterLooksAtTarget = requesterDelta.dx === dx && requesterDelta.dy === dy;
  const targetLooksAtRequester = targetDelta.dx === -dx && targetDelta.dy === -dy;
  if (!requesterLooksAtTarget || !targetLooksAtRequester) {
    return { ok: false, reason: 'not_face_to_face', detail: `dx=${dx},dy=${dy}` };
  }

  return { ok: true };
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
 * Resolve a requested player ID to a unique ID.
 * If requested ID is already used by another live client, append a short suffix.
 */
function resolveUniqueClientId(requestedId, client) {
  const baseId = requestedId || generateId();
  let resolvedId = baseId;
  let suffix = 1;

  while (clients.has(resolvedId) && clients.get(resolvedId) !== client) {
    const existing = clients.get(resolvedId);
    if (existing && existing.socket && existing.socket.destroyed) {
      clients.delete(resolvedId);
      break;
    }
    resolvedId = `${baseId}_${suffix.toString(36)}`;
    suffix += 1;
  }

  return { baseId, resolvedId };
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
        const previousId = client.id;
        const { baseId, resolvedId } = resolveUniqueClientId(message.playerId, client);
        client.id = resolvedId;
        client.characterName = message.characterName || null;

        // If this socket re-registers with a different ID, clean old mapping.
        if (previousId && previousId !== client.id && clients.get(previousId) === client) {
          clients.delete(previousId);
        }

        clients.set(client.id, client);

        sendToClient(client, {
          type: 'registered',
          playerId: client.id
        });

        if (baseId !== resolvedId) {
          console.warn(`[Register] Requested ID '${baseId}' already in use, reassigned to '${resolvedId}'`);
        }
        console.log(`[Register] Client registered: ${client.id}${client.characterName ? ` (${client.characterName})` : ''}`);
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
                  const joinPosMsg = {
                    type: 'position',
                    playerId: existingId,
                    data: existing.lastPosition
                  };
                  if (existing.lastPositionMeta) {
                    joinPosMsg.mapRev = existing.lastPositionMeta.mapRev;
                    joinPosMsg.metaStable = existing.lastPositionMeta.metaStable;
                    if (existing.lastPositionMeta.metaHash) {
                      joinPosMsg.metaHash = existing.lastPositionMeta.metaHash;
                    }
                  }
                  if (existing.characterName) joinPosMsg.characterName = existing.characterName;
                  sendToClient(client, joinPosMsg);
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
        client.lastPositionMeta = {
          mapRev: Number.isFinite(Number(message.mapRev)) ? Number(message.mapRev) : 0,
          metaStable: message.metaStable === true,
          metaHash: typeof message.metaHash === 'string' ? message.metaHash : null
        };

        // Relay to other clients in room (include timestamp + duration hint for interpolation)
        const posMsg = {
          type: 'position',
          playerId: client.id,
          data: message.data,
          t: message.t,
          dur: message.dur,
          mapRev: client.lastPositionMeta.mapRev,
          metaStable: client.lastPositionMeta.metaStable
        };
        if (client.lastPositionMeta.metaHash) posMsg.metaHash = client.lastPositionMeta.metaHash;
        if (client.characterName) posMsg.characterName = client.characterName;
        broadcastToRoom(client.roomId, client.id, posMsg);
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
        if (!client.roomId) {
          console.log(`[Duel] DROPPED: ${client.id} not in a room`);
          sendDuelDeclined(client, message.targetId, 'requester_not_in_room');
          return;
        }
        if (!message.targetId || message.targetId === client.id) {
          console.log(`[Duel] DROPPED: invalid target '${message.targetId}' from ${client.id}`);
          sendDuelDeclined(client, message.targetId, 'invalid_target');
          break;
        }
        if (client.duelOpponent) {
          console.log(`[Duel] DROPPED: requester ${client.id} already in duel with ${client.duelOpponent}`);
          sendDuelDeclined(client, message.targetId, 'requester_in_duel');
          break;
        }

        console.log(`[Duel] Request from ${client.id} to ${message.targetId} (registered clients: ${[...clients.keys()].join(', ')})`);
        clearExpiredPendingDuel(client);
        const targetClient = clients.get(message.targetId);
        clearExpiredPendingDuel(targetClient);
        if (!targetClient) {
          console.log(`[Duel] DROPPED: target ${message.targetId} not found in clients map`);
          sendDuelDeclined(client, message.targetId, 'target_not_found');
        } else if (targetClient.roomId !== client.roomId) {
          console.log(`[Duel] DROPPED: target in room ${targetClient.roomId}, requester in room ${client.roomId}`);
          sendDuelDeclined(client, message.targetId, 'different_room');
        } else if (targetClient.duelOpponent) {
          console.log(`[Duel] DROPPED: target ${message.targetId} already in duel with ${targetClient.duelOpponent}`);
          sendDuelDeclined(client, message.targetId, 'target_in_duel');
        } else if (targetClient.pendingDuel) {
          console.log(`[Duel] DROPPED: target ${message.targetId} has outgoing pending duel`);
          sendDuelDeclined(client, message.targetId, 'target_busy');
        } else {
          const duelPositioning = validateFaceToFaceDuel(client, targetClient);
          if (!duelPositioning.ok) {
            console.log(
              `[Duel] DROPPED: invalid positioning ${client.id} -> ${message.targetId} `
              + `(reason=${duelPositioning.reason}, detail=${duelPositioning.detail || 'n/a'})`
            );
            sendDuelDeclined(client, message.targetId, duelPositioning.reason);
          } else {
            // If requester had another pending target, clear it first.
            if (client.pendingDuel && client.pendingDuel.targetId !== message.targetId) {
              const previousTarget = clients.get(client.pendingDuel.targetId);
              if (previousTarget && previousTarget.roomId === client.roomId) {
                sendToClient(previousTarget, {
                  type: 'duel_cancelled',
                  requesterId: client.id
                });
              }
            }
            // Store pending duel on the requester
            client.pendingDuel = { targetId: message.targetId, createdAt: Date.now() };

            sendToClient(targetClient, {
              type: 'duel_request',
              requesterId: client.id,
              requesterName: client.characterName || client.id
            });

            console.log(`[Duel] Forwarded to ${message.targetId}`);
          }
        }
        break;

      case 'duel_accept': {
        // Duel warp accepted — coordinate teleportation for both players
        if (!client.roomId) return;

        const requester = clients.get(message.requesterId);
        clearExpiredPendingDuel(requester);
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

        // Send duel start to both players — no warp, battle starts from overworld (GBA-PK style)
        sendToClient(requester, {
          type: 'duel_warp',
          coords: {},
          isMaster: true
        });

        sendToClient(client, {
          type: 'duel_warp',
          coords: {},
          isMaster: false
        });

        console.log(`[Duel] Starting battle: ${requester.id} (master) vs ${client.id} (slave) — no warp`);
        break;
      }

      case 'duel_decline': {
        // Duel declined — notify requester
        if (!client.roomId) return;

        const declinedRequester = clients.get(message.requesterId);
        clearExpiredPendingDuel(declinedRequester);
        if (!declinedRequester || !declinedRequester.pendingDuel) {
          break;
        }

        // Verify the decline matches an actual pending request targeting this client
        if (declinedRequester.pendingDuel.targetId !== client.id
          || declinedRequester.roomId !== client.roomId) {
          break;
        }

        declinedRequester.pendingDuel = null;
        sendToClient(declinedRequester, {
          type: 'duel_declined',
          playerId: client.id
        });

        console.log(`[Duel] ${client.id} declined duel from ${message.requesterId}`);
        break;
      }

      case 'duel_cancel': {
        // Requester cancelled waiting state (timeout/manual cancel)
        if (!client.roomId || !client.pendingDuel) return;
        clearExpiredPendingDuel(client);
        if (!client.pendingDuel) break;

        const pendingTargetId = client.pendingDuel.targetId;
        if (message.targetId && message.targetId !== pendingTargetId) {
          break;
        }

        const pendingTarget = clients.get(pendingTargetId);
        client.pendingDuel = null;

        if (pendingTarget && pendingTarget.roomId === client.roomId) {
          sendToClient(pendingTarget, {
            type: 'duel_cancelled',
            requesterId: client.id
          });
        }

        console.log(`[Duel] ${client.id} cancelled duel request to ${pendingTargetId}`);
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

      case 'duel_player_info': {
        // Relay player name/gender/trainerId to duel opponent (for VS screen)
        if (!client.roomId || !client.duelOpponent) return;
        const piOpponent = clients.get(client.duelOpponent);
        if (piOpponent) {
          sendToClient(piOpponent, {
            type: 'duel_player_info',
            playerId: client.id,
            name: message.name,
            gender: message.gender,
            trainerId: message.trainerId
          });
          console.log(`[Duel] Player info relayed from ${client.id} to ${client.duelOpponent}`);
        }
        break;
      }

      case 'duel_ready': {
        // Relay ready signal to duel opponent (handshake before battle start)
        if (!client.roomId || !client.duelOpponent) return;
        const readyOpponent = clients.get(client.duelOpponent);
        if (readyOpponent) {
          sendToClient(readyOpponent, {
            type: 'duel_ready',
            playerId: client.id
          });
          console.log(`[Duel] Ready signal relayed from ${client.id} to ${client.duelOpponent}`);
        }
        break;
      }

      case 'duel_choice': {
        // Relay PvP move choice to opponent (Real PvP synchronization)
        if (!client.roomId || !client.duelOpponent) return;

        const choiceOpponent = clients.get(client.duelOpponent);
        if (choiceOpponent) {
          sendToClient(choiceOpponent, {
            type: 'duel_choice',
            playerId: client.id,
            action: message.action,
            move: message.move,
            target: message.target,
            playerSlot: message.playerSlot
          });
          console.log(`[Duel] Move choice relayed from ${client.id} to ${client.duelOpponent} (action=${message.action}, move=${message.move}, target=${message.target})`);
        }
        break;
      }

      case 'duel_buffer': {
        // Relay battle buffer data to opponent (GBA-PK exec flag protocol)
        if (!client.roomId || !client.duelOpponent) return;

        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
          // Relay all fields — just forward the entire message with sender ID
          const relay = { type: 'duel_buffer', playerId: client.id };
          if (message.bufA) relay.bufA = message.bufA;
          if (message.bufB) relay.bufB = message.bufB;
          if (message.ef) relay.ef = message.ef;
          if (message.bufID !== undefined) relay.bufID = message.bufID;
          if (message.sendID !== undefined) relay.sendID = message.sendID;
          if (message.p !== undefined) relay.p = message.p;
          if (message.attacker !== undefined) relay.attacker = message.attacker;
          if (message.target !== undefined) relay.target = message.target;
          if (message.absent !== undefined) relay.absent = message.absent;
          if (message.effect !== undefined) relay.effect = message.effect;
          sendToClient(opponent, relay);
        }
        break;
      }

      case 'duel_buffer_cmd':
      case 'duel_buffer_resp':
      case 'duel_buffer_ack': {
        // Relay buffer command/response to duel opponent (GBA-PK protocol)
        if (!client.roomId || !client.duelOpponent) return;

        const bufOpponent = clients.get(client.duelOpponent);
        if (bufOpponent) {
          const relay = { type: message.type, playerId: client.id };
          if (message.battler !== undefined) relay.battler = message.battler;
          if (message.bufA) relay.bufA = message.bufA;
          if (message.bufB) relay.bufB = message.bufB;
          if (message.ctx) relay.ctx = message.ctx;
          sendToClient(bufOpponent, relay);
          console.log(`[Duel] ${message.type} relayed from ${client.id} to ${client.duelOpponent} (battler=${message.battler})`);
        }
        break;
      }

      case 'duel_stage': {
        // Relay battle stage sync to opponent (with diagnostic data)
        const diagParts = [`Stage from ${client.id}: ${message.stage}`];
        if (message.reason) diagParts.push(`reason=${message.reason}`);
        if (message.bmf) diagParts.push(`bmf=${message.bmf}`);
        if (message.ef) diagParts.push(`ef=${message.ef}`);
        if (message.comm) diagParts.push(`comm=[${message.comm}]`);
        if (message.ctrl0) diagParts.push(`ctrl0=${message.ctrl0}`);
        if (message.ctrl1) diagParts.push(`ctrl1=${message.ctrl1}`);
        if (message.end0) diagParts.push(`end0=${message.end0}`);
        if (message.end1) diagParts.push(`end1=${message.end1}`);
        if (message.btf) diagParts.push(`btf=${message.btf}`);
        if (message.cb2) diagParts.push(`cb2=${message.cb2}`);
        if (message.comm0) diagParts.push(`comm0=${message.comm0}`);
        if (message.hsb) diagParts.push(`hsb=${message.hsb}`);
        if (message.ib) diagParts.push(`ib=${message.ib}`);
        if (message.relayBufID !== undefined) diagParts.push(`rbuf=${message.relayBufID}`);
        if (message.relayP !== undefined) diagParts.push(`rP=${message.relayP}`);
        if (message.relayE !== undefined) diagParts.push(`rE=${message.relayE}`);
        if (message.relaySendID !== undefined) diagParts.push(`rsnd=${message.relaySendID}`);
        if (message.remoteRcvd !== undefined) diagParts.push(`rcvd=${message.remoteRcvd}`);
        if (message.bufA0) diagParts.push(`bufA0=${message.bufA0}`);
        if (message.btf_change) diagParts.push(`BTF_CHANGE=${message.btf_change}`);
        if (message.context) diagParts.push(`ctx=${message.context}`);
        if (message.patches) diagParts.push(`patches=[${message.patches}]`);
        if (message.iState !== undefined) diagParts.push(`iState=${message.iState}`);
        if (message.sPtr) diagParts.push(`sPtr=${message.sPtr}`);
        if (message.bs) diagParts.push(`bs=${message.bs}`);
        if (message.br) diagParts.push(`br=${message.br}`);
        if (message.bufA) diagParts.push(`bufA=${message.bufA}`);
        if (message.brSS) diagParts.push(`brSS=${message.brSS}`);
        if (message.maxIS !== undefined) diagParts.push(`maxIS=${message.maxIS}`);
        if (message.dmaZ !== undefined) diagParts.push(`dmaZ=${message.dmaZ}`);
        if (message.taskCount !== undefined) diagParts.push(`tasks=${message.taskCount}`);
        if (message.killed !== undefined) diagParts.push(`killed=${message.killed}`);
        if (message.tasks) diagParts.push(`taskList=${message.tasks}`);
        if (message.vblank1) diagParts.push(`vb1=${message.vblank1}`);
        if (message.vblank2) diagParts.push(`vb2=${message.vblank2}`);
        if (message.intro !== undefined) diagParts.push(`intro=${message.intro}`);
        if (message.htass !== undefined) diagParts.push(`htass=${message.htass}`);
        if (message.turnPhase) diagParts.push(`tp=${message.turnPhase}`);
        console.log(`[Duel] ${diagParts.join(' ')}`);
        if (!client.roomId || !client.duelOpponent) return;

        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
          sendToClient(opponent, {
            type: 'duel_stage',
            playerId: client.id,
            stage: message.stage
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
    lastPositionMeta: null,
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
