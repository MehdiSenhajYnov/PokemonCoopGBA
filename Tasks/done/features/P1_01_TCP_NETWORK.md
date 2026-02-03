# Phase 1 - Implémentation Réseau TCP

> **Statut:** ✅ Completed (2026-02-02)
> **Type:** Feature — Module réseau TCP + Intégration client
> **Objectif:** Permettre la communication TCP entre le client mGBA Lua et le serveur Node.js pour échanger les positions des joueurs en temps réel.

---

## Vue d'ensemble

Cette tâche complète la Phase 1 du projet en implémentant la couche réseau manquante. Le serveur TCP (server.js) est déjà fonctionnel et attend les connexions. Il faut maintenant créer le module client Lua qui utilisera `socket.tcp()` de mGBA pour établir la connexion et échanger des messages JSON ligne-délimités.

**Contexte technique:**
- mGBA Lua supporte `socket.tcp()` via LuaSocket
- Protocole: JSON délimité par `\n` (pas de WebSocket)
- Mode non-bloquant requis pour ne pas freezer l'émulateur
- Buffering nécessaire pour messages incomplets

**Fichiers concernés:**
- `client/main.lua` (lignes 101-103) — TODO: Connect to TCP server
- `client/main.lua` (ligne 143) — TODO: Implement TCP send
- `server/server.js` (lignes 210-260) — Serveur TCP déjà implémenté

---

## Implementation

### Partie 1 - Créer le module network.lua

**Fichier à créer:** `client/network.lua`

**Responsabilités du module:**
1. Connexion TCP au serveur
2. Envoi de messages JSON
3. Réception non-bloquante avec buffer
4. Gestion erreurs et déconnexions

**API publique à implémenter:**

```lua
-- Module Network
local Network = {}

-- État interne
local client = nil
local connected = false
local messageBuffer = ""

-- Network.connect(host, port) -> boolean
-- Établit connexion TCP au serveur
-- Retourne true si succès, false si échec
function Network.connect(host, port)
  -- Utiliser socket.tcp() de LuaSocket
  -- Configurer settimeout(0) pour mode non-bloquant
  -- Retourner status de connexion
end

-- Network.send(message) -> boolean
-- Envoie un message JSON au serveur
-- message: table Lua à encoder en JSON
-- Ajoute automatiquement \n à la fin
-- Retourne true si envoyé, false si erreur
function Network.send(message)
  -- Encoder en JSON
  -- Ajouter \n
  -- client:send()
end

-- Network.receive() -> table | nil
-- Reçoit un message du serveur (non-bloquant)
-- Retourne table Lua décodée ou nil si aucun message
function Network.receive()
  -- client:receive() non-bloquant
  -- Gérer buffer pour messages incomplets
  -- Décoder JSON quand ligne complète
end

-- Network.isConnected() -> boolean
-- Vérifie si la connexion est active
function Network.isConnected()
  return connected
end

-- Network.disconnect()
-- Ferme la connexion proprement
function Network.disconnect()
  if client then
    client:close()
  end
end

return Network
```

**Détails d'implémentation:**

- [x] **1.1** Importer LuaSocket au début du fichier:
  ```lua
  local socket = require("socket")
  local json = require("dkjson") -- ou autre lib JSON pour Lua
  ```

- [x] **1.2** Dans `Network.connect()`:
  ```lua
  client = socket.tcp()
  client:settimeout(0) -- Mode non-bloquant CRITIQUE
  local success, err = client:connect(host, port)
  if success or err == "timeout" then -- timeout est normal en non-bloquant
    connected = true
    return true
  end
  return false
  ```

- [x] **1.3** Dans `Network.send()`:
  ```lua
  if not connected or not client then
    return false
  end

  local jsonStr = json.encode(message)
  local success, err = client:send(jsonStr .. "\n")

  if err == "closed" then
    connected = false
    return false
  end

  return success ~= nil
  ```

- [x] **1.4** Dans `Network.receive()` avec buffering:
  ```lua
  if not connected or not client then
    return nil
  end

  -- Lire données disponibles
  local data, err = client:receive("*l") -- Lire jusqu'à \n

  if err == "closed" then
    connected = false
    return nil
  end

  if data then
    -- Décoder JSON
    local message, pos, decodeErr = json.decode(data)
    if message then
      return message
    end
  end

  return nil
  ```

- [x] **1.5** Ajouter gestion d'erreurs robuste dans toutes les fonctions

- [x] **1.6** Tester le module isolément avec `server/test-connection.js`

---

### Partie 2 - Intégrer network.lua dans main.lua

**Fichier à modifier:** `client/main.lua`

**Modifications requises:**

- [x] **2.1** Ajouter require au début du fichier (après ligne 10):
  ```lua
  local Network = require("network")
  ```

- [x] **2.2** Modifier fonction `initialize()` (lignes 84-106):

  Remplacer les lignes 101-103:
  ```lua
  -- TODO: Connect to TCP server
  log("TCP connection not yet implemented")
  log("Server: " .. SERVER_HOST .. ":" .. SERVER_PORT)
  ```

  Par:
  ```lua
  -- Connect to TCP server
  log("Connecting to server " .. SERVER_HOST .. ":" .. SERVER_PORT .. "...")

  local success = Network.connect(SERVER_HOST, SERVER_PORT)

  if success then
    State.connected = true
    log("Connected to server!")

    -- Send registration message
    Network.send({
      type = "register",
      playerId = State.playerId
    })

    -- Join default room
    Network.send({
      type = "join",
      roomId = State.roomId
    })
  else
    log("Failed to connect to server")
    log("Make sure server is running on " .. SERVER_HOST .. ":" .. SERVER_PORT)
  end
  ```

- [x] **2.3** Modifier fonction `sendPositionUpdate()` (lignes 143-150):

  Remplacer:
  ```lua
  -- TODO: Implement TCP send
  -- For now, just log the data
  if ENABLE_DEBUG and State.frameCounter % 180 == 0 then
    log(string.format("Position: X=%d Y=%d Map=%d:%d Facing=%d",
      position.x, position.y, position.mapGroup, position.mapId, position.facing))
  end
  ```

  Par:
  ```lua
  -- Send position to server if connected
  if State.connected then
    Network.send({
      type = "position",
      data = position
    })
  end

  -- Debug log occasionally
  if ENABLE_DEBUG and State.frameCounter % 180 == 0 then
    log(string.format("Position: X=%d Y=%d Map=%d:%d Facing=%d",
      position.x, position.y, position.mapGroup, position.mapId, position.facing))
  end
  ```

- [x] **2.4** Ajouter réception messages dans fonction `update()` (après ligne 176):

  Insérer après `local currentPos = readPlayerPosition()`:
  ```lua
  -- Receive messages from server
  if State.connected then
    while true do
      local message = Network.receive()
      if not message then break end

      -- Handle different message types
      if message.type == "position" then
        -- Update other player's position
        State.otherPlayers[message.playerId] = message.data

      elseif message.type == "registered" then
        log("Registered with ID: " .. message.playerId)
        State.playerId = message.playerId

      elseif message.type == "joined" then
        log("Joined room: " .. message.roomId)

      elseif message.type == "ping" then
        -- Respond to heartbeat
        Network.send({ type = "ping" })

      end
    end
  end
  ```

- [x] **2.5** Ajouter cleanup à la fin du script (après ligne 219):
  ```lua
  -- Cleanup on exit
  callbacks.add("shutdown", function()
    if State.connected then
      log("Disconnecting from server...")
      Network.disconnect()
    end
  end)
  ```

- [x] **2.6** Améliorer fonction `drawOtherPlayers()` (lignes 155-167):

  Remplacer par:
  ```lua
  local function drawOtherPlayers()
    local playerCount = 0
    for playerId, position in pairs(State.otherPlayers) do
      playerCount = playerCount + 1

      -- Display player count and IDs
      gui.drawText(5, 5 + (playerCount * 10),
        string.format("%s: X=%d Y=%d", playerId, position.x or 0, position.y or 0),
        0xFFFFFF, 0x000000)
    end

    if playerCount > 0 then
      gui.drawText(5, 5, string.format("Players: %d", playerCount + 1), 0x00FF00, 0x000000)
    end
  end
  ```

---

## Protocole réseau

**Messages Client → Server:**

1. **Registration:**
   ```json
   {"type": "register", "playerId": "player_12345_abc"}
   ```

2. **Join Room:**
   ```json
   {"type": "join", "roomId": "default"}
   ```

3. **Position Update:**
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

4. **Ping (Heartbeat):**
   ```json
   {"type": "ping"}
   ```

**Messages Server → Client:**

1. **Registered:**
   ```json
   {"type": "registered", "playerId": "player_12345_abc"}
   ```

2. **Joined:**
   ```json
   {"type": "joined", "roomId": "default"}
   ```

3. **Position Broadcast:**
   ```json
   {
     "type": "position",
     "playerId": "player_67890_def",
     "data": {"x": 20, "y": 25, "mapId": 3, "mapGroup": 0, "facing": 2}
   }
   ```

4. **Ping:**
   ```json
   {"type": "ping"}
   ```

---

## Tests à effectuer

- [x] **Test 1:** Module network.lua se charge sans erreur
- [x] **Test 2:** Connexion au serveur réussit (serveur actif)
- [x] **Test 3:** Gestion connexion échouée (serveur inactif)
- [x] **Test 4:** Envoi message registration
- [x] **Test 5:** Réception message registered
- [x] **Test 6:** Envoi positions périodique
- [x] **Test 7:** Mode non-bloquant (pas de freeze mGBA)
- [x] **Test 8:** Buffering messages corrects
- [x] **Test 9:** Décodage JSON sans crash
- [x] **Test 10:** Logs debug affichés correctement

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `client/network.lua` | Module de communication TCP avec API Network.connect(), send(), receive() |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `client/main.lua:10` | Ajouter `require("network")` |
| `client/main.lua:84-106` | Remplacer TODO TCP par appel Network.connect() + messages register/join |
| `client/main.lua:143-150` | Remplacer TODO send par Network.send() |
| `client/main.lua:176+` | Ajouter boucle Network.receive() pour traiter messages serveur |
| `client/main.lua:155-167` | Améliorer drawOtherPlayers() pour afficher positions reçues |
| `client/main.lua:219+` | Ajouter callback shutdown pour Network.disconnect() |

---

## Dépendances

**Lua Libraries requises:**
- `socket` (LuaSocket) — Disponible dans mGBA
- `dkjson` ou `cjson` — Encoder/décoder JSON

**Note:** Vérifier disponibilité JSON lib dans mGBA. Si indisponible, implémenter encoder/decoder JSON simple manuellement.

---

## Critères de succès

✅ Phase 1 complète quand:
- Client mGBA se connecte au serveur
- Messages register/join envoyés et confirmés
- Positions du joueur envoyées toutes les 60 frames (1 sec à 60fps)
- Positions des autres joueurs reçues et stockées dans State.otherPlayers
- Aucun freeze de l'émulateur (mode non-bloquant fonctionne)
- Logs montrent échanges de messages

---

## Prochaine étape

Après cette tâche → **PHASE1_TESTING.md** (Tests bout en bout avec 2 clients)
