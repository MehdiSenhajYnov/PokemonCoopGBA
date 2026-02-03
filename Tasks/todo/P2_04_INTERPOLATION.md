# Phase 2 - Interpolation de Mouvement

> **Statut:** En attente (dépend de PHASE2_GHOSTING_RENDER.md)
> **Type:** Feature — Mouvement fluide des ghosts
> **Objectif:** Implémenter l'interpolation linéaire pour rendre les mouvements des ghosts fluides au lieu de saccadés.

---

## Vue d'ensemble

Sans interpolation, les ghosts "téléportent" d'une position à l'autre à chaque mise à jour réseau (toutes les 60 frames = 1 seconde). L'interpolation lisse ce mouvement en calculant des positions intermédiaires entre l'ancienne et la nouvelle position.

**Problème actuel:**
```
Position A (frame 0)  → Position B (frame 60) → Position C (frame 120)
     █                        █                       █
    Saccadé, pas fluide
```

**Avec interpolation:**
```
Position A → ... → ... → ... → Position B → ... → ... → ... → Position C
     █       █      █      █       █         █      █      █       █
                    Fluide et naturel
```

**Référence:** `docs/PHASE2_PLAN.md` lignes 211-242

---

## Partie 1 - Créer Module interpolate.lua

**Fichier à créer:** `client/interpolate.lua`

### API du module

```lua
local Interpolate = {}

-- Interpolate.update(playerId, newPosition)
-- Met à jour la position cible d'un joueur
-- newPosition: {x, y, mapId, mapGroup, facing}
function Interpolate.update(playerId, newPosition)
end

-- Interpolate.getPosition(playerId) -> {x, y, mapId, mapGroup, facing}
-- Retourne la position interpolée actuelle
function Interpolate.getPosition(playerId)
end

-- Interpolate.step()
-- Avance l'interpolation d'un frame (appelé chaque frame)
function Interpolate.step()
end

-- Interpolate.remove(playerId)
-- Retire un joueur de l'interpolation (déconnexion)
function Interpolate.remove(playerId)
end

return Interpolate
```

### Structure de données

Chaque joueur a:
```lua
players[playerId] = {
  current = {x, y, mapId, mapGroup, facing},  -- Position interpolée actuelle
  target = {x, y, mapId, mapGroup, facing},   -- Position cible à atteindre
  progress = 0.0,  -- Progression 0.0 à 1.0
  speed = 0.15     -- Vitesse d'interpolation (0.15 = 15% par frame)
}
```

### Implémentation complète

- [ ] **1.1** Créer fichier `client/interpolate.lua`:

  ```lua
  --[[
    Interpolation Module
    Provides smooth movement for ghost players
  ]]

  local Interpolate = {}

  -- Configuration
  local INTERPOLATION_SPEED = 0.15  -- 15% progress per frame (~6-7 frames pour transition)
  local TELEPORT_THRESHOLD = 10     -- Distance en tiles considérée comme téléportation

  -- Player data storage
  local players = {}

  --[[
    Linear interpolation between two values
  ]]
  local function lerp(a, b, t)
    return a + (b - a) * t
  end

  --[[
    Calculate distance between two positions (tiles)
  ]]
  local function distance(pos1, pos2)
    local dx = pos2.x - pos1.x
    local dy = pos2.y - pos1.y
    return math.sqrt(dx * dx + dy * dy)
  end

  --[[
    Check if two positions are on the same map
  ]]
  local function isSameMap(pos1, pos2)
    return pos1.mapId == pos2.mapId and pos1.mapGroup == pos2.mapGroup
  end

  --[[
    Initialize a new player for interpolation
  ]]
  local function initPlayer(playerId, position)
    players[playerId] = {
      current = {
        x = position.x,
        y = position.y,
        mapId = position.mapId,
        mapGroup = position.mapGroup,
        facing = position.facing or 1
      },
      target = {
        x = position.x,
        y = position.y,
        mapId = position.mapId,
        mapGroup = position.mapGroup,
        facing = position.facing or 1
      },
      progress = 1.0,  -- Déjà à destination
      speed = INTERPOLATION_SPEED
    }
  end

  --[[
    Update target position for a player
  ]]
  function Interpolate.update(playerId, newPosition)
    -- Validate input
    if not newPosition or not newPosition.x or not newPosition.y then
      return
    end

    -- Initialize if first time seeing this player
    if not players[playerId] then
      initPlayer(playerId, newPosition)
      return
    end

    local player = players[playerId]

    -- Check if map changed (teleportation/warp)
    if not isSameMap(player.current, newPosition) then
      -- Instant teleport (no interpolation)
      player.current.x = newPosition.x
      player.current.y = newPosition.y
      player.current.mapId = newPosition.mapId
      player.current.mapGroup = newPosition.mapGroup
      player.current.facing = newPosition.facing or player.current.facing

      player.target = {
        x = newPosition.x,
        y = newPosition.y,
        mapId = newPosition.mapId,
        mapGroup = newPosition.mapGroup,
        facing = newPosition.facing or player.current.facing
      }
      player.progress = 1.0
      return
    end

    -- Check if distance is too large (teleportation on same map)
    local dist = distance(player.current, newPosition)
    if dist > TELEPORT_THRESHOLD then
      -- Instant teleport
      player.current.x = newPosition.x
      player.current.y = newPosition.y
      player.current.facing = newPosition.facing or player.current.facing

      player.target.x = newPosition.x
      player.target.y = newPosition.y
      player.target.facing = newPosition.facing or player.current.facing
      player.progress = 1.0
      return
    end

    -- Normal update: set new target and reset progress
    player.target.x = newPosition.x
    player.target.y = newPosition.y
    player.target.facing = newPosition.facing or player.target.facing
    player.progress = 0.0  -- Start interpolation
  end

  --[[
    Get current interpolated position
  ]]
  function Interpolate.getPosition(playerId)
    if not players[playerId] then
      return nil
    end

    return players[playerId].current
  end

  --[[
    Step interpolation for all players (called every frame)
  ]]
  function Interpolate.step()
    for playerId, player in pairs(players) do
      -- Skip if already at target
      if player.progress >= 1.0 then
        goto continue
      end

      -- Increment progress
      player.progress = player.progress + player.speed
      if player.progress > 1.0 then
        player.progress = 1.0
      end

      -- Interpolate position
      player.current.x = lerp(player.current.x, player.target.x, player.progress)
      player.current.y = lerp(player.current.y, player.target.y, player.progress)

      -- Facing direction changes instantly (no interpolation)
      if player.progress >= 0.5 then  -- Change facing halfway through movement
        player.current.facing = player.target.facing
      end

      ::continue::
    end
  end

  --[[
    Remove a player from interpolation
  ]]
  function Interpolate.remove(playerId)
    players[playerId] = nil
  end

  --[[
    Get all player IDs being interpolated
  ]]
  function Interpolate.getPlayers()
    local list = {}
    for playerId, _ in pairs(players) do
      table.insert(list, playerId)
    end
    return list
  end

  --[[
    Get interpolation statistics (debug)
  ]]
  function Interpolate.getStats(playerId)
    if not players[playerId] then
      return nil
    end

    local player = players[playerId]
    return {
      progress = player.progress,
      speed = player.speed,
      current = player.current,
      target = player.target
    }
  end

  return Interpolate
  ```

- [ ] **1.2** Tester module isolément:

  ```lua
  local Interpolate = require("interpolate")

  -- Init player at position A
  Interpolate.update("test", {x=10, y=10, mapId=1, mapGroup=0, facing=1})

  -- Move to position B
  Interpolate.update("test", {x=15, y=12, mapId=1, mapGroup=0, facing=2})

  -- Simulate frames
  for i = 1, 20 do
    Interpolate.step()
    local pos = Interpolate.getPosition("test")
    print(string.format("Frame %d: x=%.2f y=%.2f", i, pos.x, pos.y))
  end
  ```

  **Sortie attendue:** Position passe progressivement de (10,10) à (15,12)

---

## Partie 2 - Intégrer dans main.lua

**Fichier à modifier:** `client/main.lua`

- [ ] **2.1** Ajouter require (ligne 12):
  ```lua
  local Interpolate = require("interpolate")
  ```

- [ ] **2.2** Modifier réception positions réseau dans `update()`:

  **Actuellement (après PHASE1):**
  ```lua
  if message.type == "position" then
    -- Update other player's position
    State.otherPlayers[message.playerId] = message.data
  ```

  **Modifier en:**
  ```lua
  if message.type == "position" then
    -- Update interpolation target
    Interpolate.update(message.playerId, message.data)

    -- Also store raw data (backup)
    State.otherPlayers[message.playerId] = message.data
  ```

- [ ] **2.3** Avancer interpolation chaque frame dans `update()` (ligne 173):

  **Ajouter au début de la fonction `update()`:**
  ```lua
  -- Step interpolation for smooth movement
  Interpolate.step()
  ```

- [ ] **2.4** Créer fonction pour obtenir positions interpolées:

  **Ajouter nouvelle fonction (après `drawOtherPlayers()`):**
  ```lua
  --[[
    Get interpolated positions for rendering
  ]]
  local function getInterpolatedPlayers()
    local result = {}

    for playerId, rawPosition in pairs(State.otherPlayers) do
      local interpolated = Interpolate.getPosition(playerId)
      if interpolated then
        result[playerId] = interpolated
      else
        -- Fallback to raw position if not interpolated yet
        result[playerId] = rawPosition
      end
    end

    return result
  end
  ```

- [ ] **2.5** Modifier `drawOtherPlayers()` pour utiliser positions interpolées:

  **Ligne actuelle:**
  ```lua
  Render.drawAllGhosts(State.otherPlayers, cameraX, cameraY, currentMap)
  ```

  **Remplacer par:**
  ```lua
  local interpolatedPlayers = getInterpolatedPlayers()
  Render.drawAllGhosts(interpolatedPlayers, cameraX, cameraY, currentMap)
  ```

- [ ] **2.6** Gérer déconnexions (nettoyer interpolation):

  **Dans la gestion des messages serveur, ajouter:**
  ```lua
  elseif message.type == "player_disconnected" then
    -- Remove from interpolation
    Interpolate.remove(message.playerId)

    -- Remove from state
    State.otherPlayers[message.playerId] = nil

    log("Player " .. message.playerId .. " disconnected")
  ```

---

## Partie 3 - Améliorer render.lua (Optionnel)

**Fichier à modifier:** `client/render.lua`

Pour rendre l'interpolation plus visible, on peut ajouter des détails visuels:

- [ ] **3.1** Ajouter indicateur de direction avec flèche:

  **Dans `Render.drawGhost()`, après le rectangle:**
  ```lua
  -- Draw direction arrow
  local arrowOffsetX = 0
  local arrowOffsetY = 0

  if position.facing == 1 then       -- Down
    arrowOffsetX, arrowOffsetY = 7, 16
    gui.drawText(screenX + arrowOffsetX, screenY + arrowOffsetY, "▼", TEXT_COLOR)
  elseif position.facing == 2 then   -- Up
    arrowOffsetX, arrowOffsetY = 7, -8
    gui.drawText(screenX + arrowOffsetX, screenY + arrowOffsetY, "▲", TEXT_COLOR)
  elseif position.facing == 3 then   -- Left
    arrowOffsetX, arrowOffsetY = -8, 7
    gui.drawText(screenX + arrowOffsetX, screenY + arrowOffsetY, "◄", TEXT_COLOR)
  elseif position.facing == 4 then   -- Right
    arrowOffsetX, arrowOffsetY = 16, 7
    gui.drawText(screenX + arrowOffsetX, screenY + arrowOffsetY, "►", TEXT_COLOR)
  end
  ```

- [ ] **3.2** Ajouter trail (ombre de mouvement):

  **Stocker historique positions dans render.lua:**
  ```lua
  local trailHistory = {}

  -- Dans drawGhost(), avant le carré principal:
  if trailHistory[playerId] then
    for i, oldPos in ipairs(trailHistory[playerId]) do
      local alpha = 0.3 - (i * 0.1)  -- Fade progressif
      gui.drawRectangle(oldPos.x, oldPos.y, GHOST_SIZE, GHOST_SIZE,
                        0, alpha * GHOST_COLOR)
    end
  end

  -- Ajouter position actuelle au trail
  if not trailHistory[playerId] then
    trailHistory[playerId] = {}
  end
  table.insert(trailHistory[playerId], {x=screenX, y=screenY})

  -- Limiter taille trail (3 dernières positions)
  while #trailHistory[playerId] > 3 do
    table.remove(trailHistory[playerId], 1)
  end
  ```

---

## Configuration et Tuning

L'interpolation peut être ajustée selon les préférences:

- [ ] **4.1** Ajouter paramètres dans `main.lua` (section Configuration):

  ```lua
  -- Interpolation settings
  local INTERPOLATION_SPEED = 0.15  -- 0.1 = lent, 0.3 = rapide
  local TELEPORT_THRESHOLD = 10     -- Distance tiles = téléportation
  ```

- [ ] **4.2** Passer paramètres à Interpolate:

  ```lua
  Interpolate.setSpeed(INTERPOLATION_SPEED)
  Interpolate.setTeleportThreshold(TELEPORT_THRESHOLD)
  ```

- [ ] **4.3** Implémenter setters dans `interpolate.lua`:

  ```lua
  function Interpolate.setSpeed(speed)
    INTERPOLATION_SPEED = speed
    -- Update all existing players
    for _, player in pairs(players) do
      player.speed = speed
    end
  end

  function Interpolate.setTeleportThreshold(threshold)
    TELEPORT_THRESHOLD = threshold
  end
  ```

---

## Tests à effectuer

- [ ] **Test 1:** Ghost bouge fluidement entre deux positions
- [ ] **Test 2:** Téléportation longue distance (>10 tiles) = instant
- [ ] **Test 3:** Changement de map = téléportation instant
- [ ] **Test 4:** Direction facing change au milieu du mouvement
- [ ] **Test 5:** Mouvement rapide (joueur qui court) reste fluide
- [ ] **Test 6:** Plusieurs ghosts interpolés simultanément
- [ ] **Test 7:** Pas de lag/stutter visible
- [ ] **Test 8:** Interpolation continue même si updates réseau espacés
- [ ] **Test 9:** Déconnexion nettoie interpolation
- [ ] **Test 10:** Performance OK (< 1% CPU overhead)

---

## Benchmarks de performance

| Métrique | Cible | Mesure |
|----------|-------|--------|
| Frame time overhead | < 1ms | ___ ms |
| CPU usage | < 1% | ___% |
| Mémoire interpolation | < 1KB | ___ KB |
| Ghosts simultanés | 10+ | ___ |

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `client/interpolate.lua` | Module d'interpolation linéaire pour mouvements fluides |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `client/main.lua:12` | Ajouter `require("interpolate")` |
| `client/main.lua:173` | Ajouter `Interpolate.step()` au début de update() |
| `client/main.lua:réception position` | Appeler `Interpolate.update()` au lieu de set direct |
| `client/main.lua:drawOtherPlayers()` | Utiliser `getInterpolatedPlayers()` |
| `client/main.lua:+nouvelle fonction` | Ajouter `getInterpolatedPlayers()` |
| `client/render.lua` (optionnel) | Ajouter flèche direction et trail |

---

## Critères de succès

✅ **Interpolation complète** quand:
- Module `interpolate.lua` fonctionne
- Ghosts bougent fluidement (pas de saccades)
- Téléportations gérées correctement
- Performance acceptable
- Intégré dans la boucle de rendu

---

## Prochaine étape

Après cette tâche → **PHASE2_NETWORK_POLISH.md** (Gestion déconnexion/reconnexion)
