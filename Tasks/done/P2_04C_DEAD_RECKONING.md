# Phase 2 - Dead Reckoning & Prédiction de Mouvement

> **Statut:** Removed (2026-02-03) — Dead reckoning supprimé dans 0.2.7
> **Type:** Feature — Prédiction de la position future d'un ghost quand le buffer est vide
> **Objectif:** Quand le dernier snapshot du buffer est atteint sans nouveau réseau, continuer le mouvement prédit au lieu de figer le ghost.
>
> **Note:** Le dead reckoning (extrapolation + correction douce) a été supprimé dans la version 0.2.7 car il causait un overshoot visible quand le joueur s'arrête : le ghost continuait de marcher au-delà de la vraie position, puis rubber-bandait en arrière. L'approche "animate toward target" qui le remplace n'a pas besoin de prédiction — le ghost attend simplement au dernier snapshot connu, ce qui est visuellement correct pour Pokemon.

---

## Vue d'ensemble

### Problème

Avec l'interpolation bufferisée (P2_04A), quand on rattrape le dernier snapshot du buffer (par ex: perte de paquets, lag réseau), le ghost se fige jusqu'à réception du prochain update. Ce gel est très visible et casse l'immersion.

### Solution : Dead Reckoning

Quand le buffer est épuisé, on **prédit** la position future du ghost en se basant sur sa vélocité récente. Pokemon étant un jeu sur grille avec mouvement constant par direction, la prédiction est fiable :

```
Buffer connu:    [pos1]---[pos2]---[pos3]
                                       |
                          Buffer épuisé ↓
Prédiction:                        [pos3]---[pred4]---[pred5]
                                    ↑ Même vélocité que pos2→pos3
```

Quand un nouvel update réseau arrive, on **corrige** doucement (smooth correction) au lieu de snapper brutalement.

---

## Partie 1 — Calcul de vélocité

**Fichier à modifier :** `client/interpolate.lua`

- [x] **1.1** Stocker la vélocité estimée pour chaque joueur

  Ajouter dans la structure joueur :
  ```lua
  players[playerId] = {
    -- ... champs existants (buffer, current, etc.)
    velocity = {x = 0, y = 0},  -- Vélocité en tiles/ms
    lastFacing = 1,              -- Dernière direction connue
    isMoving = false,            -- Le ghost est-il en mouvement ?
  }
  ```

- [x] **1.2** Calculer la vélocité à partir des snapshots

  À chaque `Interpolate.update()`, si le buffer a ≥ 2 entrées, calculer :
  ```lua
  local prev = buffer[#buffer - 1]
  local curr = buffer[#buffer]
  local dt = curr.t - prev.t
  if dt > 0 then
    player.velocity.x = (curr.pos.x - prev.pos.x) / dt
    player.velocity.y = (curr.pos.y - prev.pos.y) / dt
    player.isMoving = (player.velocity.x ~= 0 or player.velocity.y ~= 0)
    player.lastFacing = curr.pos.facing
  end
  ```

---

## Partie 2 — Extrapolation quand le buffer est vide

**Fichier à modifier :** `client/interpolate.lua`

- [x] **2.1** Dans `Interpolate.step()`, ajouter la branche extrapolation

  Actuellement (après P2_04A), `step()` interpole entre `before` et `after` dans le buffer. Ajouter le cas où `after` n'existe pas :

  ```lua
  if before and after then
    -- Interpolation normale (code existant P2_04A)
    local t = (renderTime - before.t) / (after.t - before.t)
    player.current.x = lerp(before.pos.x, after.pos.x, t)
    player.current.y = lerp(before.pos.y, after.pos.y, t)

  elseif before and player.isMoving then
    -- EXTRAPOLATION : prédire au-delà du dernier snapshot connu
    local extraTime = renderTime - before.t  -- Temps écoulé depuis le dernier snapshot
    local maxExtraTime = 500  -- Ne pas extrapoler au-delà de 500ms

    if extraTime < maxExtraTime then
      player.current.x = before.pos.x + player.velocity.x * extraTime
      player.current.y = before.pos.y + player.velocity.y * extraTime
      player.current.facing = player.lastFacing
    end
    -- Si > maxExtraTime : on fige (le joueur a probablement arrêté de bouger ou déconnecté)
  end
  ```

- [x] **2.2** Limites de l'extrapolation

  L'extrapolation doit être bornée pour éviter des ghosts qui traversent les murs :
  - **Max 500ms** d'extrapolation (configurable via `MAX_EXTRAPOLATION_TIME`)
  - **Même map seulement** — si le ghost est sur une autre map, ne pas extrapoler
  - **Distance max** — si la position prédite s'éloigne de > 5 tiles du dernier snapshot, arrêter

---

## Partie 3 — Correction douce (Smooth Snap-Back)

**Fichier à modifier :** `client/interpolate.lua`

Quand un nouvel update réseau arrive après une période d'extrapolation, la position prédite peut être légèrement différente de la position réelle. Il faut corriger en douceur.

- [x] **3.1** Détecter la correction nécessaire

  Dans `Interpolate.update()`, si on était en mode extrapolation :
  ```lua
  if player.extrapolating then
    local error = distance(player.current, newPosition)
    if error > 0.5 and error < TELEPORT_THRESHOLD then
      -- Correction douce : interpoler de la position prédite vers la vraie
      player.correctionStart = copyPos(player.current)
      player.correctionTarget = copyPos(newPosition)
      player.correctionProgress = 0.0
      player.correcting = true
    end
    player.extrapolating = false
  end
  ```

- [x] **3.2** Appliquer la correction dans `step()`

  ```lua
  if player.correcting then
    player.correctionProgress = player.correctionProgress + 0.15  -- ~7 frames
    if player.correctionProgress >= 1.0 then
      player.correcting = false
    else
      -- Blend entre position corrigée et interpolation normale
      local correctedX = lerp(player.correctionStart.x, player.correctionTarget.x, player.correctionProgress)
      local correctedY = lerp(player.correctionStart.y, player.correctionTarget.y, player.correctionProgress)
      -- Fusionner avec l'interpolation normale
      player.current.x = lerp(correctedX, player.current.x, player.correctionProgress)
      player.current.y = lerp(correctedY, player.current.y, player.correctionProgress)
    end
  end
  ```

---

## Partie 4 — Flags d'état et debug

- [x] **4.1** Tracker l'état du ghost pour debug

  Ajouter un champ `state` au joueur :
  ```lua
  player.state = "interpolating"  -- ou "extrapolating" ou "correcting" ou "idle"
  ```

  Mettre à jour dans `step()` selon la branche exécutée.

- [x] **4.2** Exposer l'état via API

  ```lua
  function Interpolate.getState(playerId)
    if not players[playerId] then return nil end
    return players[playerId].state
  end
  ```

  Utile pour afficher dans le debug overlay (ex: couleur du ghost selon l'état).

---

## Configuration

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `MAX_EXTRAPOLATION_TIME` | 500ms | Durée max de prédiction sans nouveau snapshot |
| `MAX_EXTRAPOLATION_DIST` | 5 tiles | Distance max de prédiction |
| `CORRECTION_SPEED` | 0.15 | Vitesse de correction douce (0-1/frame) |
| `CORRECTION_THRESHOLD` | 0.5 tiles | Erreur min pour déclencher une correction |

---

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `client/interpolate.lua` | Vélocité, extrapolation, correction douce, états |

---

## Tests à effectuer

- [x] **Test 1:** Ghost continue de bouger pendant une perte réseau simulée (~500ms)
- [x] **Test 2:** Ghost ne traverse pas les murs (extrapolation bornée)
- [x] **Test 3:** Après perte réseau, correction douce visible (pas de snap)
- [x] **Test 4:** Extrapolation s'arrête après 500ms (ghost fige, ne drift pas à l'infini)
- [x] **Test 5:** Joueur immobile → pas d'extrapolation
- [x] **Test 6:** Changement de direction → nouvelle vélocité correcte

---

## Critères de succès

✅ **Dead reckoning complet** quand :
- Le ghost continue de bouger naturellement pendant un lag réseau de ~500ms
- La correction après prédiction erronée est douce (pas de rubber-banding visible)
- L'extrapolation est bornée en temps et distance
- Aucun ghost ne traverse les murs ou drift à l'infini
- Performance < 1ms overhead par frame

---

## Prochaine étape

Après cette tâche → **P2_04D_SMOOTH_RENDERING.md** (amélioration du rendu sub-tile)
