# Phase 2 - Système de Ghosting (Rendu Visuel)

> **Statut:** En attente (dépend de PHASE1_TESTING.md)
> **Type:** Feature — Affichage overlay des autres joueurs
> **Objectif:** Afficher visuellement les autres joueurs connectés sous forme de "ghosts" sur l'écran avec conversion coordonnées monde→écran et filtrage par map.

---

## Vue d'ensemble

Cette tâche implémente le système de **ghosting** qui permet de voir les autres joueurs en temps réel sur votre écran. Elle regroupe trois sous-tâches:
1. Recherche des offsets caméra (coordonnées viewport)
2. Création du module de rendu (`render.lua`)
3. Intégration dans la boucle de jeu

**Vision produit:**
- Voir un carré coloré représentant chaque autre joueur
- Position calculée relativement à la caméra
- Nom du joueur affiché au-dessus
- Masquer ghosts sur maps différentes

**Référence:** `docs/PHASE2_PLAN.md` lignes 175-209

---

## Partie 1 - Rechercher Offsets Position Caméra

**Objectif:** Trouver les adresses mémoire de cameraX et cameraY dans Pokémon Émeraude

### Contexte technique

Dans Pokémon GBA, le joueur peut être n'importe où sur la map, mais seul un viewport 240x160 pixels (15x10 tiles) est affiché à l'écran. La caméra suit le joueur avec un certain offset.

**Formule de conversion:**
```
screenX = (worldX - cameraX) * 16  // 16 pixels par tile
screenY = (worldY - cameraY) * 16
```

**Plage probable:** 0x02024000 - 0x02025000 (proche des offsets joueur)

### Méthodologie de recherche

- [ ] **1.1** Installer Cheat Engine ou VBA-SDL-H

- [ ] **1.2** Lancer Pokémon Émeraude et noter position initiale:
  - PlayerX: exemple 10
  - PlayerY: exemple 15

- [ ] **1.3** Dans Cheat Engine:
  1. Attacher processus mGBA
  2. Scan type: "2 bytes" (16-bit)
  3. Chercher valeur proche de PlayerX (essayer 10, ou 10-7=3 si offset caméra)
  4. Se déplacer dans le jeu
  5. Next Scan avec nouvelle valeur
  6. Répéter jusqu'à 1-5 résultats

- [ ] **1.4** Méthode alternative (décompilation):
  - Consulter [pokeemerald decomp](https://github.com/pret/pokeemerald)
  - Chercher: `gSaveBlock1Ptr->pos` et viewport structs
  - Vérifier fichiers: `src/field_camera.c`, `src/overworld.c`

- [ ] **1.5** Valeurs attendues:
  ```c
  // Structure probable
  struct {
    s16 cameraX;  // Offset relatif à la map
    s16 cameraY;
  } gCamera;
  ```

- [ ] **1.6** Tester les offsets trouvés avec script Lua temporaire:
  ```lua
  local testCameraX = 0x02024??? -- Adresse trouvée
  local testCameraY = 0x02024???

  callbacks.add("frame", function()
    local camX = memory.read16(testCameraX)
    local camY = memory.read16(testCameraY)
    local playerX = memory.read16(0x02024844)
    local playerY = memory.read16(0x02024846)

    print(string.format("Player: %d,%d | Camera: %d,%d", playerX, playerY, camX, camY))
  end)
  ```

- [ ] **1.7** Valider que:
  - cameraX change quand on se déplace horizontalement
  - cameraY change quand on se déplace verticalement
  - Caméra suit le joueur avec lag (pas instantané)

### Ajouter offsets dans configuration

- [ ] **1.8** Modifier `config/emerald_us.lua` (après ligne 25):

  Ajouter dans la section `offsets`:
  ```lua
  -- Camera/Viewport positions
  cameraX = 0x02024XXX,  -- Adresse trouvée
  cameraY = 0x02024YYY,  -- Adresse trouvée
  ```

- [ ] **1.9** Ajouter fonctions dans `client/hal.lua` (après ligne 173):

  ```lua
  function HAL.readCameraX()
    if not config or not config.offsets.cameraX then
      return nil
    end
    return safeRead(config.offsets.cameraX, 2)
  end

  function HAL.readCameraY()
    if not config or not config.offsets.cameraY then
      return nil
    end
    return safeRead(config.offsets.cameraY, 2)
  end
  ```

- [ ] **1.10** Tester lecture caméra dans `main.lua`:
  ```lua
  local camX = HAL.readCameraX()
  local camY = HAL.readCameraY()
  print("Camera:", camX, camY)
  ```

**Fallback si offsets introuvables:**
Si impossible de trouver cameraX/Y, utiliser position joueur comme approximation:
```lua
cameraX = playerX - 7  -- Centre de l'écran 15 tiles = offset 7
cameraY = playerY - 5  -- Centre de l'écran 10 tiles = offset 5
```

---

## Partie 2 - Créer Module render.lua

**Fichier à créer:** `client/render.lua`

**Responsabilités:**
- Convertir coordonnées monde → coordonnées écran
- Dessiner ghosts avec `gui.drawRectangle()`
- Filtrer par map
- Afficher noms des joueurs

### API du module

```lua
local Render = {}

-- Render.init(config)
-- Initialise le module avec config (pour offsets futurs)
function Render.init(config)
end

-- Render.drawGhost(playerId, position, cameraX, cameraY, currentMap)
-- Dessine un ghost à l'écran
-- position: {x, y, mapId, mapGroup, facing}
-- currentMap: {mapId, mapGroup}
function Render.drawGhost(playerId, position, cameraX, cameraY, currentMap)
end

-- Render.drawAllGhosts(otherPlayers, cameraX, cameraY, currentMap)
-- Dessine tous les ghosts en une fois
function Render.drawAllGhosts(otherPlayers, cameraX, cameraY, currentMap)
end

return Render
```

### Implémentation détaillée

- [ ] **2.1** Créer fichier `client/render.lua`:

  ```lua
  --[[
    Render Module
    Handles ghost player rendering and coordinate conversion
  ]]

  local Render = {}

  -- Configuration
  local TILE_SIZE = 16  -- Pixels per tile
  local GHOST_SIZE = 14 -- Ghost square size
  local GHOST_COLOR = 0x8000FF00  -- Semi-transparent green (ARGB)
  local TEXT_COLOR = 0xFFFFFFFF
  local TEXT_BG = 0x80000000

  -- Screen dimensions (GBA)
  local SCREEN_WIDTH = 240
  local SCREEN_HEIGHT = 160

  function Render.init(config)
    -- Placeholder pour config future (sprites, couleurs custom, etc.)
  end

  --[[
    Convert world coordinates to screen coordinates
  ]]
  local function worldToScreen(worldX, worldY, cameraX, cameraY)
    local screenX = (worldX - cameraX) * TILE_SIZE
    local screenY = (worldY - cameraY) * TILE_SIZE
    return screenX, screenY
  end

  --[[
    Check if position is on same map
  ]]
  local function isSameMap(pos1, pos2)
    return pos1.mapId == pos2.mapId and pos1.mapGroup == pos2.mapGroup
  end

  --[[
    Check if position is visible on screen
  ]]
  local function isOnScreen(screenX, screenY)
    return screenX >= -GHOST_SIZE and screenX <= SCREEN_WIDTH and
           screenY >= -GHOST_SIZE and screenY <= SCREEN_HEIGHT
  end

  --[[
    Draw a single ghost player
  ]]
  function Render.drawGhost(playerId, position, cameraX, cameraY, currentMap)
    -- Validate inputs
    if not position or not position.x or not position.y then
      return
    end

    if not cameraX or not cameraY then
      return
    end

    -- Filter by map (only show ghosts on same map)
    if not isSameMap(position, currentMap) then
      return
    end

    -- Convert world coords to screen coords
    local screenX, screenY = worldToScreen(position.x, position.y, cameraX, cameraY)

    -- Check if on screen
    if not isOnScreen(screenX, screenY) then
      return
    end

    -- Draw ghost square
    gui.drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE,
                      0, GHOST_COLOR)

    -- Draw player ID above ghost
    local shortId = string.sub(playerId, 1, 8) -- Tronquer ID si trop long
    gui.drawText(screenX, screenY - 8, shortId, TEXT_COLOR, TEXT_BG)

    -- Optional: Draw direction indicator (arrow)
    -- TODO: Phase 2 future enhancement
  end

  --[[
    Draw all ghosts from otherPlayers table
  ]]
  function Render.drawAllGhosts(otherPlayers, cameraX, cameraY, currentMap)
    if not otherPlayers then
      return
    end

    for playerId, position in pairs(otherPlayers) do
      Render.drawGhost(playerId, position, cameraX, cameraY, currentMap)
    end
  end

  return Render
  ```

- [ ] **2.2** Tester module isolément avec données mockées:
  ```lua
  local Render = require("render")
  Render.init()

  callbacks.add("frame", function()
    local mockPosition = {x=10, y=15, mapId=3, mapGroup=0}
    local mockCamera = {x=5, y=10}
    local mockCurrentMap = {mapId=3, mapGroup=0}

    Render.drawGhost("test_player", mockPosition, mockCamera.x, mockCamera.y, mockCurrentMap)
  end)
  ```

- [ ] **2.3** Vérifier qu'un carré vert apparaît à la position attendue

---

## Partie 3 - Intégrer dans main.lua

**Fichier à modifier:** `client/main.lua`

- [ ] **3.1** Ajouter require (ligne 11):
  ```lua
  local Render = require("render")
  ```

- [ ] **3.2** Initialiser dans `initialize()` (ligne 95):
  ```lua
  -- Initialize rendering
  Render.init(GameConfig)
  ```

- [ ] **3.3** Modifier fonction `drawOtherPlayers()` (lignes 155-167):

  **Remplacer entièrement par:**
  ```lua
  local function drawOtherPlayers()
    -- Read camera position
    local cameraX = HAL.readCameraX()
    local cameraY = HAL.readCameraY()

    -- Fallback si caméra pas disponible (utiliser position joueur)
    if not cameraX or not cameraY then
      cameraX = State.lastPosition.x - 7
      cameraY = State.lastPosition.y - 5
    end

    -- Current map info
    local currentMap = {
      mapId = State.lastPosition.mapId,
      mapGroup = State.lastPosition.mapGroup
    }

    -- Render all ghosts
    Render.drawAllGhosts(State.otherPlayers, cameraX, cameraY, currentMap)

    -- Draw player count
    local playerCount = 0
    for _ in pairs(State.otherPlayers) do
      playerCount = playerCount + 1
    end

    if playerCount > 0 then
      gui.drawText(5, 5, string.format("Players: %d", playerCount + 1),
                   0x00FF00, 0x000000)
    end
  end
  ```

- [ ] **3.4** S'assurer que `drawOtherPlayers()` est appelé dans `update()` (ligne 189)

- [ ] **3.5** (Optionnel) Ajouter toggle visibilité ghosts avec F3:

  Ajouter dans State (ligne 19):
  ```lua
  showGhosts = true,
  ```

  Ajouter dans `update()` avant `drawOtherPlayers()`:
  ```lua
  -- Toggle ghost visibility with F3
  local f3Pressed = emu:getKey("F3")
  if f3Pressed and not State.f3WasPressed then
    State.showGhosts = not State.showGhosts
    log("Ghosts " .. (State.showGhosts and "enabled" or "disabled"))
  end
  State.f3WasPressed = f3Pressed

  -- Draw ghosts if enabled
  if State.showGhosts then
    drawOtherPlayers()
  end
  ```

---

## Tests à effectuer

- [ ] **Test 1:** Carré vert apparaît quand autre joueur est sur même map
- [ ] **Test 2:** Carré suit le mouvement de l'autre joueur
- [ ] **Test 3:** Carré disparaît si autre joueur change de map
- [ ] **Test 4:** Coordonnées écran correctes (carré au bon endroit)
- [ ] **Test 5:** Nom du joueur affiché au-dessus du carré
- [ ] **Test 6:** Plusieurs ghosts affichés si 3+ joueurs
- [ ] **Test 7:** Ghosts hors écran ne sont pas rendus
- [ ] **Test 8:** Performance OK (pas de drop FPS)
- [ ] **Test 9:** F3 toggle fonctionne (si implémenté)
- [ ] **Test 10:** Fallback caméra fonctionne si offsets introuvables

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `client/render.lua` | Module de rendu des ghosts avec conversion coordonnées |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `config/emerald_us.lua:25+` | Ajouter offsets `cameraX` et `cameraY` |
| `client/hal.lua:173+` | Ajouter `HAL.readCameraX()` et `HAL.readCameraY()` |
| `client/main.lua:11` | Ajouter `require("render")` |
| `client/main.lua:95` | Initialiser `Render.init()` |
| `client/main.lua:155-167` | Remplacer `drawOtherPlayers()` avec rendu complet |
| `client/main.lua:19` | Ajouter `showGhosts = true` dans State (optionnel) |

---

## Amélioration futures (Phase 2+)

- [ ] Extraire sprites joueur depuis ROM VRAM
- [ ] Afficher sprite directionnel (haut/bas/gauche/droite)
- [ ] Animation marche/course
- [ ] Couleurs différentes par joueur
- [ ] Trail/ombre derrière le ghost
- [ ] Indicateur de distance (si trop loin)

---

## Critères de succès

✅ **Ghosting visuel complet** quand:
- Offsets caméra trouvés et ajoutés à config
- Module `render.lua` fonctionne
- Ghosts s'affichent visuellement en jeu
- Conversion coordonnées correcte
- Filtrage par map fonctionne
- Performance acceptable (pas de lag)

---

## Ressources

- [pokeemerald decomp - field_camera.c](https://github.com/pret/pokeemerald/blob/master/src/field_camera.c)
- [mGBA Scripting - gui API](https://mgba.io/docs/scripting.html)
- Cheat Engine: https://www.cheatengine.org/
- VBA-SDL-H: https://github.com/libertyernie/vba-sdl-h

---

## Prochaine étape

Après cette tâche → **PHASE2_INTERPOLATION.md** (Mouvement fluide)
