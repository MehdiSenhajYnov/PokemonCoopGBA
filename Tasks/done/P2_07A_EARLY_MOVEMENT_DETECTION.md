# Phase 2 - Detection Anticipee de Mouvement + Duration Timestamps

> **Statut:** Termine (2026-02-03)
> **Type:** Update — Refactoring du systeme de detection de mouvement et d'interpolation
> **Priorite:** Haute
> **Objectif:** Eliminer le retard de ~266ms sur les ghosts en detectant le debut du mouvement (double validation KEYINPUT + camera delta) au lieu d'attendre la fin de l'animation de marche (changement de tile RAM). Remplacer le `BASE_DURATION` fixe par la duree reelle mesuree via timestamps.

---

## Probleme actuel

### Symptome
Le ghost d'un autre joueur se met a bouger **~266ms** apres que le joueur source ait commence a marcher. Ce retard est inherent a l'architecture actuelle et s'ajoute a toute latence reseau.

### Cause racine
Dans le moteur Pokemon GBA, quand le joueur appuie sur une direction:
1. **Frame 0**: Input detecte, animation de marche commence
2. **Frame 1-15**: Animation joue, camera scrolle progressivement
3. **Frame 16**: La position tile en RAM change (ex: `0x02024CBC` passe de X a X+1)

Le code actuel (`client/main.lua:498-504`) ne detecte le mouvement qu'au **frame 16** (changement de tile RAM). Le message part a la fin de l'animation, puis le recepteur interpole sur un `BASE_DURATION` fixe.

**Latence totale percue = animation de marche (~266ms) + interpolation recepteur**

### Second probleme: BASE_DURATION fixe
`client/interpolate.lua:25` definit `BASE_DURATION = 50` (anciennement 250). Cette valeur fixe ne correspond pas a la vitesse reelle du joueur (marche vs course vs velo vs speedhack). Le ghost interpole a une vitesse arbitraire au lieu de reproduire le timing reel.

### Impact
- Ghost toujours en retard d'un cycle complet de marche
- Vitesse du ghost decouple de la vitesse reelle du joueur
- Saccades a certaines vitesses quand BASE_DURATION ne correspond pas

---

## Solution: Double Validation Input+Camera + Duration Timestamps + Idle Sends

### Principe
Deux signaux hardware sont disponibles **des le frame 0-1** du mouvement:
1. **KEYINPUT** (registre I/O `0x04000130`): detecte l'appui directionnel immediatement
2. **Camera delta** (`HAL.readCameraX/Y`): la camera commence a scroller des le frame 1

**Quand les deux signaux concordent** (meme direction, ecart <= 3 frames), le joueur est en mouvement. On envoie la destination predite immediatement, ~15 frames avant le changement de tile.

### Tableau de validation

| Input | Camera | Resultat | Cas |
|-------|--------|----------|-----|
| Oui | Non | Pas d'envoi | Mur, bloque par NPC |
| Non | Oui | Pas d'envoi | Cutscene, camera scriptee |
| Oui | Oui (meme dir) | **ENVOI** | Mouvement reel confirme |

### Correction naturelle (pas de rollback explicite)

Au lieu d'un systeme de rollback complexe, on utilise les **idle sends** : quand le joueur est immobile, sa position reelle est envoyee periodiquement (~2x/sec). Si une prediction etait fausse, la prochaine mise a jour idle corrige naturellement le ghost via l'interpolation normale.

```
Cas nominal (>95% du temps):
  Frame 1:   Prediction (x, y+1) envoyee
  Frame 16:  Tile confirme (x, y+1) → match, pas de doublon

Cas erreur rare (ex: mur avec micro-scroll camera):
  Frame 1:   Prediction (x, y+1) envoyee
  Frame 16:  Tile toujours (x, y) → lastSentPosition != currentPos
  Frame 46:  Idle send → envoie (x, y) comme position normale
             Recepteur: (x, y) != (x, y+1) → enqueue waypoint
             Ghost smooth-move de (x, y+1) vers (x, y) → correction douce

Cas ledge jump:
  Frame 1:   Prediction (x, y+1) envoyee
  Frame 32:  Tile passe a (x, y+2) → envoie (x, y+2) normalement
             Recepteur: ghost va a y+1 puis continue vers y+2 → fluide
```

**Avantage:** Pas de flag `rollback` dans le protocole, pas de handling special dans `Interpolate.update()`, pas de modification du serveur. La deduplication existante (`interpolate.lua:128`) ignore les positions identiques, donc les idle sends quand tout va bien ne generent aucun waypoint superflu.

### Flow complet

```
Frame 0:   Joueur appuie DOWN
           HAL.readKeyInput() = "down", inputFrame = 0
           Camera delta = 0 (pas encore de scroll)
           → Pas encore confirme

Frame 1:   Camera delta Y > 0 (scroll commence)
           cameraDeltaToDir() = "down"
           input == camera == "down", gap = 1 frame (<=3)
           → CONFIRME: destination = (x, y+1)
           → Envoi immediat

Frame 2-15: Animation de marche continue
            Prediction en attente de confirmation

Frame 16:  Tile RAM passe a (x, y+1)
           → Match prediction → confirme, pas de doublon

LATENCE GAGNEE: ~15 frames = ~250ms
```

---

## Implementation

### Partie 1 — `client/hal.lua`: Ajouter `HAL.readKeyInput()`

**Fichier:** `client/hal.lua`
**Insertion:** Apres `HAL.readFacing()` (ligne 276), avant `toSigned16()` (ligne 282)

Utilise `HAL.readIOReg16(0x0130)` existant (ligne 467-475). Le registre KEYINPUT est active-low (bit = 0 signifie appuye).

Bits direction:
- Bit 4: Right (`0x0010`)
- Bit 5: Left (`0x0020`)
- Bit 6: Up (`0x0040`)
- Bit 7: Down (`0x0080`)

- [x] **1.1** Creer `HAL.readKeyInput()`:
  ```lua
  function HAL.readKeyInput()
    local raw = HAL.readIOReg16(0x0130)
    if not raw then return nil end
    local pressed = (~raw) & 0x00F0  -- inverser active-low, masquer bits 4-7
    if (pressed & 0x0080) ~= 0 then return "down" end
    if (pressed & 0x0040) ~= 0 then return "up" end
    if (pressed & 0x0020) ~= 0 then return "left" end
    if (pressed & 0x0010) ~= 0 then return "right" end
    return nil
  end
  ```
- [x] **1.2** Tester dans la console mGBA: `print(HAL.readKeyInput())` en appuyant sur les directions

**Risque:** Zero. Lecture seule d'un registre I/O. L'infrastructure `readIOReg16` est deja testee pour les registres BG.

---

### Partie 2 — `client/interpolate.lua`: Duration par waypoint

**Fichier:** `client/interpolate.lua`

#### 2a. Nouvelles constantes

Remplacer `BASE_DURATION = 50` (ligne 25) par:

- [x] **2.1** Definir les nouvelles constantes:
  ```lua
  local DEFAULT_DURATION = 266   -- Fallback 1er message (~16 frames de marche a 60fps)
  local MIN_DURATION = 10        -- Clamp minimum (ms)
  local MAX_DURATION = 2000      -- Clamp maximum (ms)
  ```

#### 2b. Etat joueur

- [x] **2.2** Ajouter `lastTimestamp = nil` dans la structure player (lignes 102-108):
  ```lua
  players[playerId] = {
    current = copyPos(newPosition),
    queue = {},
    animFrom = nil,
    animProgress = 0,
    state = "idle",
    lastTimestamp = nil,  -- NOUVEAU: timestamp du dernier message recu
  }
  ```

#### 2c. Modifier `Interpolate.update()`

**Fonction actuelle:** lignes 95-149. Signature: `Interpolate.update(playerId, newPosition, timestamp)`

**Signature inchangee** — pas de parametre `rollback` necessaire.

- [x] **2.3** Calcul duration a partir des timestamps (avant l'enqueue, apres la deduplication):
  ```lua
  local duration = DEFAULT_DURATION
  if timestamp and player.lastTimestamp then
    local dt = timestamp - player.lastTimestamp
    if dt > 0 then
      duration = math.max(MIN_DURATION, math.min(MAX_DURATION, dt))
    end
  end
  player.lastTimestamp = timestamp
  ```

- [x] **2.4** Stocker `duration` dans chaque waypoint enqueue (remplacer ligne 137):
  ```lua
  -- Avant: table.insert(player.queue, copyPos(newPosition))
  -- Apres:
  local wp = copyPos(newPosition)
  wp.duration = duration
  table.insert(player.queue, wp)
  ```

#### 2d. Modifier `Interpolate.step()`

- [x] **2.5** Ligne 177, utiliser la duration du waypoint:
  ```lua
  -- Avant:
  local segDuration = BASE_DURATION / math.max(1, #player.queue)
  -- Apres:
  local wpDuration = player.queue[1].duration or DEFAULT_DURATION
  local segDuration = wpDuration / math.max(1, #player.queue)
  ```

**Impact:** Chaque waypoint porte sa propre duree. La formule adaptative est preservee (division par queue length) mais la base vient du timing reel, pas d'une constante.

---

### Partie 3 — `client/main.lua`: Detection anticipee + idle sends

C'est le changement principal. Toutes les modifications sont dans la fonction `update()` (ligne 379+).

#### 3a. Modifier SEND_RATE_IDLE

- [x] **3.1** Changer `SEND_RATE_IDLE` (ligne 34):
  ```lua
  -- Avant:
  local SEND_RATE_IDLE = 0       -- 0 = no sends when idle
  -- Apres:
  local SEND_RATE_IDLE = 30      -- Envoyer toutes les 30 frames (~2x/sec) en idle
  ```

  Ce changement est la cle de la correction naturelle. La deduplication dans `Interpolate.update()` (ligne 128) ignore les positions identiques, donc les idle sends ne generent pas de waypoints inutiles. Mais si la position reelle differe de la derniere envoyee (prediction fausse), la correction est envoyee automatiquement.

  **Note:** L'envoi idle existant (lignes 507-511) envoie deja quand `lastSentPosition != currentPos`. Avec `SEND_RATE_IDLE = 30`, ce check se fait toutes les 30 frames en idle au lieu de jamais.

#### 3b. Nouvelles variables State

- [x] **3.2** Ajouter a la table `State` (apres ligne 58):
  ```lua
  -- Early movement detection
  earlyDetect = {
    inputDir = nil,         -- direction KEYINPUT ("up"/"down"/"left"/"right")
    inputFrame = 0,         -- frame de detection input
    prevCameraX = nil,      -- camera X du frame precedent
    prevCameraY = nil,      -- camera Y du frame precedent
    predictedPos = nil,     -- position predite envoyee (pour eviter doublons)
    predictedFrame = 0,     -- frame d'envoi de la prediction
  },
  ```

#### 3c. Helpers

- [x] **3.3** Ajouter pres des constantes (apres ligne 37):
  ```lua
  local DIR_DELTA = {
    up    = { dx = 0, dy = -1 },
    down  = { dx = 0, dy =  1 },
    left  = { dx = -1, dy = 0 },
    right = { dx =  1, dy = 0 },
  }

  local function cameraDeltaToDir(dcx, dcy)
    if dcy < 0 then return "up" end
    if dcy > 0 then return "down" end
    if dcx < 0 then return "left" end
    if dcx > 0 then return "right" end
    return nil
  end
  ```

#### 3d. Constantes de timing

- [x] **3.4** Ajouter les constantes:
  ```lua
  local INPUT_CAMERA_MAX_GAP = 3     -- frames max entre input et camera pour validation
  local INPUT_TIMEOUT = 5            -- frames avant abandon input sans camera
  ```

#### 3e. Restructuration du frame loop

**IMPORTANT:** Actuellement la camera est lue a la ligne 516, APRES la detection de mouvement. Il faut la lire AVANT pour utiliser le delta dans la detection.

- [x] **3.5** Deplacer la lecture camera. Apres `readPlayerPosition()` (ligne 387):
  ```lua
  local currentPos = readPlayerPosition()
  local cameraX = HAL.readCameraX()  -- DEPLACE: etait ligne 516
  local cameraY = HAL.readCameraY()  -- DEPLACE: etait ligne 516
  ```

- [x] **3.6** Modifier l'appel `Render.updateCamera` (ancienne ligne 516) pour utiliser les variables locales:
  ```lua
  Render.updateCamera(currentPos.x, currentPos.y, cameraX, cameraY)
  ```

#### 3f. Algorithme de detection (inserer entre lecture camera et detection mouvement existante)

- [x] **3.7** Detection input chaque frame:
  ```lua
  local ed = State.earlyDetect
  local inputDir = HAL.readKeyInput()

  -- Enregistrer nouvelle direction (seulement si pas de prediction en cours)
  if inputDir and not ed.predictedPos then
    if ed.inputDir ~= inputDir then
      ed.inputDir = inputDir
      ed.inputFrame = State.frameCounter
    end
  elseif not inputDir and not ed.predictedPos then
    ed.inputDir = nil
    ed.inputFrame = 0
  end
  ```

- [x] **3.8** Detection camera delta et double validation:
  ```lua
  -- Camera delta
  local cameraDir = nil
  if ed.prevCameraX and cameraX and cameraY then
    local dcx = cameraX - ed.prevCameraX
    local dcy = cameraY - ed.prevCameraY
    if dcx ~= 0 or dcy ~= 0 then
      cameraDir = cameraDeltaToDir(dcx, dcy)
    end
  end
  ed.prevCameraX = cameraX
  ed.prevCameraY = cameraY

  -- Double validation: input + camera meme direction, gap <= 3 frames
  if ed.inputDir and cameraDir and not ed.predictedPos then
    if ed.inputDir == cameraDir then
      local gap = State.frameCounter - ed.inputFrame
      if gap <= INPUT_CAMERA_MAX_GAP then
        -- CONFIRME: calculer destination et envoyer
        local delta = DIR_DELTA[ed.inputDir]
        if delta and currentPos then
          ed.predictedPos = {
            x = currentPos.x + delta.dx,
            y = currentPos.y + delta.dy,
            mapId = currentPos.mapId,
            mapGroup = currentPos.mapGroup,
            facing = currentPos.facing
          }
          ed.predictedFrame = State.frameCounter

          if State.connected then
            Network.send({
              type = "position",
              data = ed.predictedPos,
              t = State.timeMs
            })
            State.lastSentPosition = ed.predictedPos
          end
        end
      end
    end
  end

  -- Timeout input sans confirmation camera (mur/bloque)
  if ed.inputDir and not ed.predictedPos then
    if State.frameCounter - ed.inputFrame > INPUT_TIMEOUT then
      ed.inputDir = nil
      ed.inputFrame = 0
    end
  end
  ```

#### 3g. Modifier la detection de changement de tile (lignes 498-511)

- [x] **3.9** Quand une tile change, verifier contre la prediction en cours:
  ```lua
  if ed.predictedPos and positionChanged(currentPos, State.lastPosition) then
    -- Tile a change: verifier si la prediction etait correcte
    if currentPos.x == ed.predictedPos.x
      and currentPos.y == ed.predictedPos.y
      and currentPos.mapId == ed.predictedPos.mapId
      and currentPos.mapGroup == ed.predictedPos.mapGroup then
      -- MATCH: prediction correcte, pas de doublon a envoyer
      State.lastPosition = currentPos
      State.lastSentPosition = currentPos
    else
      -- MISMATCH (ex: ledge jump): envoyer la position reelle comme update normal
      sendPositionUpdate(currentPos)
      State.lastPosition = currentPos
      State.lastSentPosition = currentPos
    end
    -- Reset detection dans tous les cas
    ed.inputDir = nil
    ed.predictedPos = nil
  elseif not ed.predictedPos then
    -- Pas de prediction: comportement existant (lignes 498-511)
    local sendRate = State.isMoving and SEND_RATE_MOVING or SEND_RATE_IDLE
    if sendRate > 0 and State.sendCooldown <= 0 then
      if positionChanged(currentPos, State.lastPosition) then
        sendPositionUpdate(currentPos)
        State.lastPosition = currentPos
        State.lastSentPosition = currentPos
        State.sendCooldown = sendRate
      end
    end
  end
  ```

  **Note sur le cas mismatch (ledge):** On envoie la position reelle comme un message normal (pas de flag rollback). Le recepteur avait deja recu la prediction (x, y+1) et recoit maintenant (x, y+2). L'interpolation les traite comme deux waypoints consecutifs: ghost va a y+1 puis continue vers y+2. Visuellement c'est fluide.

#### 3h. Idle sends (correction naturelle)

L'envoi idle existant (lignes 507-511) gere deja ce cas:
```lua
if not State.isMoving and State.lastSentPosition and positionChanged(currentPos, State.lastSentPosition) then
  sendPositionUpdate(currentPos)
  State.lastSentPosition = currentPos
end
```

Avec `SEND_RATE_IDLE = 30`, ce code s'execute toutes les 30 frames en idle. Si une prediction etait fausse et la tile n'a jamais change, `currentPos != lastSentPosition` (car lastSentPosition = predictedPos). L'idle send envoie la correction automatiquement.

- [x] **3.10** Verifier que l'envoi idle respecte le cooldown (`State.sendCooldown`). Le code existant (lignes 496-504) utilise deja `sendRate` et `sendCooldown`. Avec `SEND_RATE_IDLE = 30`, le cooldown sera de 30 frames entre envois idle. S'assurer que le check idle final (lignes 507-511) est aussi soumis au cooldown pour eviter des envois redondants.

#### 3i. Reset sur changement de map

- [x] **3.11** Dans le bloc map change existant (lignes 477-485), ajouter le reset:
  ```lua
  if mapChanged then
    sendPositionUpdate(currentPos)
    State.lastPosition = currentPos
    State.lastSentPosition = currentPos
    State.sendCooldown = SEND_RATE_MOVING
    Occlusion.clearCache()
    -- Reset early detection
    State.earlyDetect.inputDir = nil
    State.earlyDetect.predictedPos = nil
  end
  ```

---

## Edge cases detailles

| # | Scenario | Input | Camera | Prediction | Tile | Resultat |
|---|----------|-------|--------|------------|------|----------|
| 1 | Marche normale | DOWN | delta Y>0 | (x, y+1) | (x, y+1) | Match, ghost synchrone |
| 2 | Mur/bloque | DOWN | aucun delta | Aucune | Inchangee | Double-check previent l'envoi |
| 3 | Cutscene | Aucun | delta Y>0 | Aucune | Variable | Double-check previent l'envoi |
| 4 | Ledge jump | DOWN | delta Y>0 | (x, y+1) | (x, y+2) | Ghost passe par y+1 puis continue vers y+2 (fluide) |
| 5 | Course | DOWN | delta Y>0 | (x, y+1) | (x, y+1) | Match, duration plus courte (~133ms) via timestamp |
| 6 | Velo | DOWN | delta Y>0 | (x, y+1) | (x, y+1) | Match, duration encore plus courte (~66ms) |
| 7 | Speedhack 2x | DOWN | delta Y>0 | (x, y+1) | (x, y+1) | Match, duration /2 via timestamp, ghost suit |
| 8 | Demi-tour rapide | DOWN puis LEFT | delta Y>0 puis X<0 | (x, y+1) | (x, y+1) puis... | 1ere prediction confirmee, 2eme cycle demarre |
| 9 | Changement de map | N/A | N/A | N/A | N/A | Teleport existant, prediction reset |
| 10 | Surf | DOWN | delta Y>0 | (x, y+1) | (x, y+1) | Match, duration de surf |
| 11 | Tourner sur place | LEFT | aucun delta | Aucune | Inchangee | Facing update existant (pas de waypoint) |
| 12 | Prediction fausse rare | DOWN | micro-delta | (x, y+1) | (x, y) | Idle send corrige en ~0.5s, ghost smooth-move retour |

---

## Configuration

| Constante | Valeur | Fichier | Description |
|-----------|--------|---------|-------------|
| `DEFAULT_DURATION` | 266 ms | interpolate.lua | Fallback pour 1er message (~16 frames de marche) |
| `MIN_DURATION` | 10 ms | interpolate.lua | Clamp minimum (protection speedhack extreme) |
| `MAX_DURATION` | 2000 ms | interpolate.lua | Clamp maximum (protection lag) |
| `INPUT_CAMERA_MAX_GAP` | 3 frames | main.lua | Ecart max entre input et camera pour validation |
| `INPUT_TIMEOUT` | 5 frames | main.lua | Abandon input sans confirmation camera |
| `SEND_RATE_IDLE` | 30 frames | main.lua | Frequence envoi idle (~2x/sec, correction naturelle) |

---

## Tests a effectuer

### Test 1: HAL.readKeyInput()
- [ ] Appeler `print(HAL.readKeyInput())` dans la console mGBA
- [ ] Verifier retour "down"/"up"/"left"/"right" selon bouton appuye
- [ ] Verifier `nil` quand aucun bouton directionnel appuye
- [ ] Verifier pas de crash

### Test 2: Duration timestamp (avant activation detection anticipee)
- [ ] 2 instances connectees, marche normale → ghost bouge fluidement
- [ ] Speedhack 2x → ghost accelere automatiquement
- [ ] Speedhack 4x → ghost suit la vitesse
- [ ] Velo → ghost plus rapide que la marche

### Test 3: Detection anticipee
- [ ] 2 instances cote a cote → ghost bouge quasi-simultanement (pas de retard ~266ms)
- [ ] Mouvement en L (droite-droite-bas) → parcours correct, pas de diagonale
- [ ] Marcher contre un mur → aucune prediction envoyee (verifier console debug)
- [ ] Appuyer direction sans bouger (tourner) → pas de fausse prediction

### Test 4: Correction naturelle (idle sends)
- [ ] Provoquer une fausse prediction (si possible) → verifier correction dans les ~0.5s
- [ ] Joueur immobile: verifier que les idle sends n'ajoutent pas de waypoints (deduplication)
- [ ] Joueur immobile apres mouvement: ghost s'arrete proprement a la bonne position

### Test 5: Ledge jump
- [ ] Sauter un ledge → ghost passe par tile intermediaire puis continue (pas de snap)
- [ ] Visuellement fluide (mouvement continu, pas de saccade)

### Test 6: Edge cases
- [ ] Cutscene avec mouvement camera → pas de fausse prediction
- [ ] Changement de map → prediction reset, ghost teleporte normalement
- [ ] Deconnexion/reconnexion → detection reset proprement
- [ ] Direction rapide alternee → pas de predictions en conflit

---

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `client/hal.lua` | Ajouter `HAL.readKeyInput()` (~15 lignes, apres ligne 276) |
| `client/interpolate.lua` | Remplacer `BASE_DURATION` par `DEFAULT_DURATION`, ajouter duration par waypoint, modifier `segDuration` dans `step()` |
| `client/main.lua` | Changer `SEND_RATE_IDLE` de 0 a 30, ajouter `State.earlyDetect`, helpers direction, restructurer frame loop (camera avant detection), algorithme double validation, confirmation tile |

## Fichiers NON modifies (simplification vs design initial)

| Fichier | Raison |
|---------|--------|
| `server/server.js` | Pas de flag `rollback` a relayer — correction via idle sends |
| `client/network.lua` | Transporte les messages — pas de modification necessaire |
| `client/render.lua` | Utilise `Interpolate.getPosition()` — API inchangee |
| `client/sprite.lua` | Independant du systeme de position |
| `client/occlusion.lua` | Independant du systeme de position |

---

## Ordre d'implementation recommande

1. **`hal.lua`** — `readKeyInput()` (standalone, testable immediatement)
2. **`interpolate.lua`** — Duration par waypoint (retrocompatible: messages existants fonctionnent toujours)
3. **`main.lua`** — `SEND_RATE_IDLE = 30` (1 ligne, active la correction naturelle)
4. **`main.lua`** — Detection anticipee complete (state, helpers, algorithme, confirmation tile)

Chaque etape est testable independamment. Le systeme existant (envoi sur changement de tile) reste actif comme fallback.

---

## Criteres de succes

1. Le ghost commence a bouger dans les 1-2 frames apres le joueur source (au lieu de ~16 frames)
2. La vitesse du ghost correspond exactement a la vitesse reelle (marche/course/velo/speedhack)
3. Aucune fausse prediction envoyee quand le joueur est bloque (mur, NPC)
4. Aucune fausse prediction pendant les cutscenes
5. Les ledge jumps sont geres fluidement (ghost passe par tile intermediaire)
6. Les erreurs rares sont corrigees naturellement par les idle sends (~0.5s)
7. Le fallback (envoi sur tile change) fonctionne toujours si la detection anticipee echoue
8. Performance: 1 lecture I/O supplementaire par frame (negligeable) + ~2 messages/sec idle (negligeable)

---

## Prochaine etape

Apres cette tache → `Tasks/todo/P2_07_OPTIMIZATION.md` (optimisations restantes: batch socket, cache occlusion, etc.)
