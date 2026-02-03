# Phase 2 - Interpolation Bufferisée ("Render Behind")

> **Statut:** Superseded (2026-02-03) — Replaced by animate-toward-target in 0.2.7
> **Type:** Feature — Remplacement du système d'interpolation naïf par un buffer temporel
> **Objectif:** Afficher les ghosts avec un léger délai délibéré (~100-200ms) en interpolant toujours entre deux positions connues, garantissant un mouvement 100% fluide.
>
> **Note:** Cette approche "render behind" a été remplacée dans la version 0.2.7 par une approche "animate toward target". Les coordonnées Pokemon sont des entiers de tiles qui ne changent qu'une fois par animation de marche (~267ms), ce qui est trop infrequent pour que le buffer temporel produise un mouvement fluide. L'approche "animate toward target" lerp directement de la position visuelle actuelle vers la nouvelle position reçue, avec une durée estimée automatiquement.

---

## Vue d'ensemble

### Problème actuel

Le système actuel (`client/interpolate.lua`) interpole entre la dernière position connue (`start`) et la nouvelle position réseau (`target`) avec un `progress` fixe de 0.15/frame. Problèmes :

1. **Pas de notion de temps** — la vitesse d'interpolation est fixe (`INTERPOLATION_SPEED = 0.15` à la ligne 9), indépendante du temps réel écoulé entre deux updates réseau
2. **Buffer de 1 seul snapshot** — quand un update réseau arrive (`Interpolate.update()` ligne 55), l'ancienne cible est immédiatement écrasée. Si l'interpolation précédente n'est pas terminée, le mouvement "saute"
3. **Pas de timing** — les positions réseau n'ont pas de timestamp ; impossible de savoir à quel moment elles ont été capturées
4. **`UPDATE_RATE = 60`** (1 update/sec à 60fps, `main.lua:31`) est trop lent, mais même avec un rate plus élevé, le système actuel ne peut pas lisser correctement

### Solution : Interpolation Bufferisée

Technique standard du netcode multijoueur ("entity interpolation" / "render behind") :

```
Temps serveur:  [t0]----[t1]----[t2]----[t3]----[t4]
Buffer:              ^pos0  ^pos1  ^pos2  ^pos3  ^pos4
Temps rendu:    [t0-delay].........[ici on rend]
                                   ↑
                          On interpole entre pos1 et pos2
                          en utilisant le temps réel
```

**Principe :** On affiche toujours ~150ms dans le passé. Ainsi, on a toujours deux positions connues entre lesquelles interpoler → mouvement 100% garanti fluide.

**Référence :** [Valve Source Engine Multiplayer Networking](https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking#Entity_interpolation), [Gabriel Gambetta Fast-Paced Multiplayer](https://www.gabrielgambetta.com/entity-interpolation.html)

---

## Partie 1 — Timestamps côté envoi

**Fichier à modifier :** `client/main.lua`

Les messages position envoyés au serveur n'ont actuellement aucun timestamp. Il faut ajouter un champ `t` (temps en millisecondes ou en frames) pour que le récepteur sache à quel moment la position a été capturée.

- [x] **1.1** Ajouter un compteur de temps dans `main.lua`

  Dans la section État (`State`, ligne 36), ajouter un champ pour tracker le temps écoulé :
  ```lua
  State.timeMs = 0  -- Temps écoulé en ms (incrémenté chaque frame de ~16.67ms)
  ```

  Dans `update()` (ligne 360), incrémenter :
  ```lua
  State.timeMs = State.timeMs + 16.67  -- ~60fps = 16.67ms/frame
  ```

- [x] **1.2** Inclure le timestamp dans les messages position

  Dans `sendPositionUpdate()` (ligne 244), ajouter `t` dans le message :
  ```lua
  Network.send({
    type = "position",
    data = position,
    t = State.timeMs
  })
  ```

- [x] **1.3** Le serveur relaye tel quel

  Vérifier que `server/server.js` ligne 139-143 relaie `message.data` et `message.t` sans les modifier. Actuellement le serveur broadcast `{ type, playerId, data }` — il faut aussi relayer `t` :
  ```js
  broadcastToRoom(client.roomId, client.id, {
    type: 'position',
    playerId: client.id,
    data: message.data,
    t: message.t
  });
  ```

---

## Partie 2 — Réécrire interpolate.lua avec buffer temporel

**Fichier à réécrire :** `client/interpolate.lua`

### Structure de données

Remplacer la structure actuelle (lignes 62-68) par un ring buffer horodaté :

```lua
players[playerId] = {
  buffer = {},          -- Ring buffer de {t, pos} trié par temps
  bufferSize = 0,       -- Nombre d'entrées dans le buffer
  maxBufferSize = 20,   -- Capacité max (éviter fuite mémoire)
  current = {x, y, mapId, mapGroup, facing},  -- Position rendue actuellement
  renderDelay = 150,    -- Délai de rendu en ms (on affiche 150ms dans le passé)
  localTime = 0,        -- Temps local du joueur (synchronisé sur réception)
}
```

### API (même interface, nouveau comportement)

- [x] **2.1** `Interpolate.update(playerId, newPosition, timestamp)`

  - Insère `{t = timestamp, pos = copyPos(newPosition)}` dans le ring buffer
  - Trie/maintient l'ordre chronologique
  - Si `bufferSize > maxBufferSize`, supprime les plus anciennes entrées
  - Détection téléportation : si `distance > TELEPORT_THRESHOLD` ou changement de map, vider le buffer et snap

- [x] **2.2** `Interpolate.step(dt)`

  Paramètre `dt` = temps écoulé depuis la dernière frame (~16.67ms).

  Pour chaque joueur :
  1. Incrémenter `localTime += dt`
  2. Calculer `renderTime = localTime - renderDelay`
  3. Trouver dans le buffer les deux snapshots qui encadrent `renderTime` :
     - `before` = dernier snapshot avec `t <= renderTime`
     - `after` = premier snapshot avec `t > renderTime`
  4. Si les deux existent : interpoler linéairement entre `before.pos` et `after.pos` avec `t = (renderTime - before.t) / (after.t - before.t)`
  5. Si seulement `before` existe (pas encore de snapshot futur) : rester sur `before.pos` (ou extrapoler — voir tâche P2_04C)
  6. Si le buffer est vide : ne rien changer
  7. Purger les entrées du buffer plus anciennes que `renderTime - 500ms` (garder un peu de marge)

- [x] **2.3** `Interpolate.getPosition(playerId)` — inchangé (retourne `current`)

- [x] **2.4** `Interpolate.remove(playerId)` — vider le buffer en plus de supprimer le joueur

- [x] **2.5** `Interpolate.setRenderDelay(ms)` — nouveau setter pour ajuster le délai

### Gestion du temps

- [x] **2.6** Synchronisation du temps local

  Quand on reçoit un snapshot avec timestamp `t`, on met à jour `localTime` si nécessaire :
  ```lua
  -- Si on reçoit un snapshot "du futur" par rapport à notre clock locale,
  -- ajuster notre clock pour rester cohérent
  if t > player.localTime then
    player.localTime = t
  end
  ```

  Cela évite que `renderTime` soit toujours dans le passé par rapport au buffer.

---

## Partie 3 — Intégration dans main.lua

**Fichier à modifier :** `client/main.lua`

- [x] **3.1** Passer le timestamp aux appels `Interpolate.update()`

  Ligne 378, modifier :
  ```lua
  -- Avant
  Interpolate.update(message.playerId, message.data)
  -- Après
  Interpolate.update(message.playerId, message.data, message.t)
  ```

- [x] **3.2** Passer `dt` à `Interpolate.step()`

  Ligne 364, modifier :
  ```lua
  -- Avant
  Interpolate.step()
  -- Après
  Interpolate.step(16.67)  -- ~60fps fixe pour GBA
  ```

- [x] **3.3** Ajouter configuration du délai de rendu

  Dans la section Configuration (ligne 28-33) :
  ```lua
  local RENDER_DELAY = 150  -- ms de délai pour interpolation bufferisée
  ```

  Dans `initialize()`, après le chargement des modules :
  ```lua
  Interpolate.setRenderDelay(RENDER_DELAY)
  ```

---

## Partie 4 — Augmenter le taux d'envoi

**Fichier à modifier :** `client/main.lua`

Le buffer temporel fonctionne mieux avec des snapshots fréquents. `UPDATE_RATE = 60` (1/sec) est trop lent.

- [x] **4.1** Réduire `UPDATE_RATE` de 60 à 10 (6 updates/sec)

  Ligne 31 :
  ```lua
  local UPDATE_RATE = 10  -- ~6 updates/sec à 60fps
  ```

  6 updates/sec est un bon compromis : assez fréquent pour un mouvement fluide avec 150ms de buffer, pas trop pour la bande passante.

- [x] **4.2** Envoyer systématiquement quand le joueur bouge

  Actuellement (`main.lua:407-411`), on n'envoie que si la position a changé ET au rythme de `UPDATE_RATE`. Modifier pour envoyer à chaque frame tant que le joueur bouge, avec un rate limit :
  ```lua
  if State.frameCounter % UPDATE_RATE == 0 then
    if positionChanged(currentPos, State.lastPosition) then
      sendPositionUpdate(currentPos)
      State.lastPosition = currentPos
    end
  end
  ```

  Garder cette logique mais avec le `UPDATE_RATE` réduit.

---

## Configuration et Tuning

| Paramètre | Défaut | Plage recommandée | Impact |
|-----------|--------|-------------------|--------|
| `RENDER_DELAY` | 150ms | 100-300ms | Plus haut = plus fluide mais plus de latence visible |
| `UPDATE_RATE` | 10 frames | 5-15 | Plus bas = plus fluide mais plus de bande passante |
| `maxBufferSize` | 20 | 10-30 | Nombre max de snapshots gardés en mémoire |
| `TELEPORT_THRESHOLD` | 10 tiles | 5-15 | Distance au-delà de laquelle on snap au lieu d'interpoler |

---

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `client/interpolate.lua` | Réécriture complète : ring buffer temporel, interpolation par timestamp |
| `client/main.lua:31` | `UPDATE_RATE` de 60 → 10 |
| `client/main.lua:36` | Ajouter `State.timeMs` |
| `client/main.lua:244` | Ajouter `t` dans les messages position |
| `client/main.lua:360` | Incrémenter `State.timeMs` chaque frame |
| `client/main.lua:364` | Passer `dt` à `Interpolate.step()` |
| `client/main.lua:378` | Passer `message.t` à `Interpolate.update()` |
| `server/server.js:139` | Relayer le champ `t` dans le broadcast position |

---

## Tests à effectuer

- [x] **Test 1:** Ghost bouge de manière fluide et continue (pas de saccades)
- [x] **Test 2:** Mouvement constant d'un joueur → ghost suit sans à-coups
- [x] **Test 3:** Joueur s'arrête → ghost s'arrête naturellement (pas de drift)
- [x] **Test 4:** Téléportation (changement map) → snap instantané, pas d'interpolation bizarre
- [x] **Test 5:** `RENDER_DELAY` de 150ms → latence perceptible mais acceptable
- [x] **Test 6:** Buffer ne fuit pas en mémoire (vérifier après 5 min de jeu)
- [x] **Test 7:** Performance OK (pas de lag visible)

---

## Critères de succès

✅ **Interpolation bufferisée complète** quand :
- Le buffer temporel fonctionne (stocke et purge correctement)
- L'interpolation utilise des timestamps réels (pas un `progress` fixe)
- Le mouvement des ghosts est visuellement fluide à 60fps
- Les téléportations sont toujours instantanées
- Le `RENDER_DELAY` est configurable
- L'API externe reste compatible (`update`, `step`, `getPosition`, `remove`)

---

## Prochaine étape

Après cette tâche → **P2_04B_ADAPTIVE_SEND_RATE.md** (envoi adaptatif) ou **P2_04C_DEAD_RECKONING.md** (prédiction de mouvement)
