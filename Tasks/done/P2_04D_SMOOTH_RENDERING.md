# Phase 2 - Rendu Sub-Tile et Améliorations Visuelles

> **Statut:** Completed (2026-02-03) — Updated in 0.2.7 with camera correction
> **Type:** Feature — Rendu pixel-perfect entre les tiles pour un mouvement visuellement fluide
> **Objectif:** Le ghost se déplace pixel par pixel entre les tiles au lieu de sauter de tile en tile, rendant le mouvement interpolé visible et naturel.
>
> **Note 0.2.7:** Ajout de `Render.updateCamera()` pour correction sub-tile via tracking des deltas caméra. Les couleurs d'état debug ont été simplifiées : seuls "interpolating" et "idle" restent (suppression de "extrapolating" et "correcting" suite au retrait du dead reckoning).

---

## Vue d'ensemble

### Problème

Le rendu actuel (`render.lua:48-49`) convertit les coordonnées ghost en pixels via :
```lua
local screenX = PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE
local screenY = PLAYER_SCREEN_Y + (ghostY - playerY) * TILE_SIZE
```

`TILE_SIZE = 16`. Donc si `ghostX = 10.5` (position interpolée entre deux tiles), le calcul donne un offset de `0.5 * 16 = 8 pixels`. Le positionnement sub-tile fonctionne mathématiquement, **mais seulement si les valeurs interpolées sont bien des floats** (x = 10.3, 10.5, 10.7...) et pas des entiers arrondis.

Il faut vérifier que la chaîne complète (interpolation → getPosition → render) préserve les coordonnées fractionnaires.

---

## Partie 1 — Vérifier la chaîne de coordonnées

- [x] **1.1** Vérifier que `Interpolate.getPosition()` retourne des floats

  Après les changements P2_04A, `player.current.x` et `.y` sont le résultat d'un `lerp()` → ce sont des floats. Vérifier que rien ne les arrondit (`math.floor`, cast en int, etc.).

- [x] **1.2** Vérifier que `render.lua:ghostToScreen()` gère les floats

  La formule `PLAYER_SCREEN_X + (ghostX - playerX) * TILE_SIZE` produit un float si `ghostX` est un float. Le Painter API de mGBA accepte-t-il des coordonnées float dans `drawRectangle()` ? Si oui, pas de problème. Si non, il faudra arrondir au dernier moment (`math.floor`).

- [x] **1.3** Vérifier que les positions envoyées par le réseau sont des entiers (tiles)

  Les adresses mémoire (`HAL.readPlayerX()`) retournent des entiers (position en tiles). L'interpolation crée des floats entre ces entiers. C'est le comportement souhaité.

---

## Partie 2 — Indicateur visuel de direction

**Fichier à modifier :** `client/render.lua`

Le facing direction est synchronisé mais pas visualisé. Ajouter un indicateur simple.

- [x] **2.1** Ajouter un petit marqueur de direction sur le ghost

  Dans `Render.drawGhost()` (ligne 76), après le dessin du rectangle (ligne 102), ajouter un triangle ou un point indiquant la direction :

  ```lua
  -- Petit marqueur de direction (4x4 pixels)
  local markerX, markerY = screenX + 5, screenY + 5
  if position.facing == 1 then       -- Down
    markerY = screenY + GHOST_SIZE - 2
  elseif position.facing == 2 then   -- Up
    markerY = screenY - 2
  elseif position.facing == 3 then   -- Left
    markerX = screenX - 2
  elseif position.facing == 4 then   -- Right
    markerX = screenX + GHOST_SIZE - 2
  end
  painter:setFillColor(0xFFFFFFFF)  -- Blanc
  painter:drawRectangle(markerX, markerY, 4, 4)
  ```

---

## Partie 3 — Couleur selon l'état (optionnel, debug)

**Fichier à modifier :** `client/render.lua`

Après l'implémentation du dead reckoning (P2_04C), le ghost peut être dans différents états. Colorier le ghost selon l'état aide au debug.

- [x] **3.1** Accepter un paramètre `state` optionnel dans `drawGhost()`

  ```lua
  -- Couleurs par état
  local STATE_COLORS = {
    interpolating = 0x8000FF00,   -- Vert (normal)
    extrapolating = 0x80FFFF00,   -- Jaune (prédiction)
    correcting    = 0x80FF8800,   -- Orange (correction)
    idle          = 0x8000FF00,   -- Vert (normal)
  }
  ```

  Utiliser la couleur d'état au lieu de `GHOST_COLOR` si l'état est fourni.

- [x] **3.2** Passer l'état depuis `main.lua`

  Dans `drawOverlay()`, quand on construit `interpolatedPlayers` (ligne 345), inclure aussi l'état :
  ```lua
  interpolatedPlayers[playerId] = {
    pos = interpolated or rawPosition,
    state = Interpolate.getState(playerId)
  }
  ```

  Adapter `Render.drawAllGhosts()` pour lire cette structure.

---

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `client/render.lua:48-49` | Vérifier support coordonnées float |
| `client/render.lua:76-122` | Ajouter marqueur direction |
| `client/render.lua:76` | Accepter état optionnel pour couleur debug |
| `client/main.lua:345-349` | Passer état interpolation au rendu (si P2_04C fait) |

---

## Tests à effectuer

- [ ] **Test 1:** Ghost se déplace de manière fluide pixel par pixel (pas tile par tile)
- [ ] **Test 2:** Marqueur de direction visible et correct
- [ ] **Test 3:** Pas d'artefacts visuels (scintillement, décalage)
- [ ] **Test 4:** Couleurs d'état correctes en mode debug (si P2_04C implémenté)

---

## Critères de succès

✅ **Rendu sub-tile complet** quand :
- Le ghost glisse de pixel en pixel entre les tiles
- Le marqueur de direction est visible et correct
- Aucun arrondi ne casse la fluidité
- Performance rendu inchangée

---

## Prochaine étape

Après cette tâche → **P2_05_NETWORK_POLISH.md** (gestion déconnexion/reconnexion)
