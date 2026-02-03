# Phase 3 - Système Duel Warp

> **Statut:** En attente (dépend de PHASE2_FINAL_TESTING.md)
> **Type:** Feature — Téléportation synchronisée pour combat
> **Objectif:** Implémenter le système de "Duel Warp" permettant à deux joueurs de se téléporter dans une salle de combat Link.

---

## Vue d'ensemble

Le **Duel Warp** est la feature signature du framework. Deux joueurs peuvent initier un duel en appuyant sur A près du ghost de l'autre, accepter l'invitation, puis se téléporter simultanément dans une salle de combat.

**Référence:** `CLAUDE.md` lignes 230-247

---

## Workflow complet

```
1. Joueur A près du ghost de Joueur B
2. Joueur A appuie sur bouton A
3. → Envoi duel_request au serveur
4. → Serveur broadcast à Joueur B
5. Joueur B voit prompt "Duel [PlayerA]?"
6. Joueur B appuie sur A pour accepter
7. → Envoi duel_accept au serveur
8. → Serveur coordonne téléportation
9. Les deux joueurs écrivent en RAM (mapId, X, Y)
10. Lock inputs pendant 2-3 secondes
11. Téléportation effective
12. Unlock inputs devant NPC Colisée
```

---

## Partie 1 - Module duel.lua (Trigger)

**Fichier à créer:** `client/duel.lua`

### API

```lua
local Duel = {}

-- Duel.checkTrigger(playerPos, otherPlayers, keys)
-- Vérifie si bouton A pressé près d'un ghost
-- Retourne playerId cible ou nil
function Duel.checkTrigger(playerPos, otherPlayers, keys)
end

-- Duel.request(targetPlayerId)
-- Envoie demande duel au serveur
function Duel.request(targetPlayerId)
end

-- Duel.handleRequest(requesterId, requesterName)
-- Affiche prompt acceptation duel
function Duel.handleRequest(requesterId, requesterName)
end

-- Duel.accept(requesterId)
-- Accepte duel et envoie au serveur
function Duel.accept(requesterId)
end

-- Duel.drawUI()
-- Affiche UI demande duel en cours
function Duel.drawUI()
end

return Duel
```

### Implémentation

- [ ] **1.1** Détection proximité:
  ```lua
  function Duel.checkTrigger(playerPos, otherPlayers, keys)
    if not keys.A then
      return nil
    end

    -- Chercher ghost proche (< 2 tiles)
    for playerId, ghostPos in pairs(otherPlayers) do
      if ghostPos.mapId == playerPos.mapId and
         ghostPos.mapGroup == playerPos.mapGroup then

        local distance = math.abs(ghostPos.x - playerPos.x) +
                         math.abs(ghostPos.y - playerPos.y)

        if distance <= 2 then
          return playerId
        end
      end
    end

    return nil
  end
  ```

- [ ] **1.2** UI prompt duel:
  ```lua
  local pendingRequest = nil

  function Duel.handleRequest(requesterId, requesterName)
    pendingRequest = {
      id = requesterId,
      name = requesterName,
      time = os.time()
    }
  end

  function Duel.drawUI()
    if not pendingRequest then return end

    -- Afficher box au centre de l'écran
    gui.drawRectangle(60, 60, 120, 40, 0xFFFFFFFF, 0xFF000000)
    gui.drawText(70, 65, "Duel Request", 0xFFFFFF, 0x000000)
    gui.drawText(70, 75, "From: " .. pendingRequest.name, 0xFFFFFF)
    gui.drawText(70, 85, "Press A to accept", 0x00FF00)
    gui.drawText(70, 95, "Press B to decline", 0xFF0000)
  end
  ```

---

## Partie 2 - Téléportation (HAL + Serveur)

**Fichiers à modifier:**
- `client/hal.lua` (déjà a writePlayerPosition - ligne 183)
- `server/server.js` (gérer coordination)

### Workflow serveur

- [ ] **2.1** Dans `server.js`, ajouter gestion duel_accept:

  ```javascript
  case 'duel_accept':
    // Both players accepted
    const requester = clients.get(message.requesterId);
    const accepter = client;

    if (!requester) {
      break;
    }

    // Get duel warp coordinates (from config)
    const duelCoords = {
      mapGroup: 7,
      mapId: 4,
      x: 10,
      y: 15
    };

    // Send warp command to both players
    sendToClient(requester, {
      type: 'duel_warp',
      coords: duelCoords
    });

    sendToClient(accepter, {
      type: 'duel_warp',
      coords: duelCoords
    });

    console.log(`[Duel] Warping ${requester.id} and ${accepter.id}`);
    break;
  ```

### Téléportation client

- [ ] **2.2** Dans `main.lua`, gérer message duel_warp:

  ```lua
  elseif message.type == "duel_warp" then
    log("Warping to duel room...")

    -- Lock inputs
    State.inputsLocked = true

    -- Perform warp
    local coords = message.coords
    local success = HAL.writePlayerPosition(
      coords.x,
      coords.y,
      coords.mapId,
      coords.mapGroup
    )

    if success then
      log("Warp successful!")
    else
      log("Warp failed!")
    end

    -- Unlock after 3 seconds (180 frames)
    State.unlockFrame = State.frameCounter + 180
  ```

- [ ] **2.3** Lock inputs pendant warp:

  ```lua
  -- Dans update(), début de fonction
  if State.inputsLocked then
    if State.frameCounter >= State.unlockFrame then
      State.inputsLocked = false
      log("Inputs unlocked")
    else
      -- Bloquer inputs ici si possible
      return  -- Skip rest of update
    end
  end
  ```

---

## Partie 3 - Coordonnées Duel Room

- [ ] **3.1** Rechercher Battle Frontier / Link room dans Émeraude:
  - Consulter pokeemerald decomp
  - Trouver map avec NPC Link Cable
  - Noter mapGroup, mapId, X, Y

- [ ] **3.2** Ajouter dans `config/emerald_us.lua`:
  ```lua
  duelRoom = {
    mapGroup = 7,
    mapId = 4,
    playerAX = 10,
    playerAY = 15,
    playerBX = 12,
    playerBY = 15
  }
  ```

---

## Tests

- [ ] **Test 1:** Détection proximité fonctionne
- [ ] **Test 2:** Prompt duel s'affiche
- [ ] **Test 3:** Acceptation envoie message serveur
- [ ] **Test 4:** Les deux joueurs se téléportent
- [ ] **Test 5:** Téléportation synchronisée (< 1 sec écart)
- [ ] **Test 6:** Inputs lockés pendant warp
- [ ] **Test 7:** Positionnement correct devant NPC
- [ ] **Test 8:** Refus de duel fonctionne

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `client/duel.lua` | Module gestion trigger et UI duel |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `server/server.js` | Ajouter coordination duel_warp |
| `client/main.lua` | Gérer messages duel_warp, lock inputs |
| `config/emerald_us.lua` | Ajouter coords duelRoom |

---

## Prochaine étape

Après cette tâche → **PHASE4_MULTI_ROM.md**
