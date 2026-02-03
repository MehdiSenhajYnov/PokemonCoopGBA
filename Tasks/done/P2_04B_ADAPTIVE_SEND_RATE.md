# Phase 2 - Taux d'Envoi Adaptatif

> **Statut:** Completed (2026-02-03)
> **Type:** Feature — Envoi intelligent des positions selon l'état du joueur
> **Objectif:** Envoyer des updates fréquents quand le joueur bouge, rares quand il est immobile, pour optimiser bande passante et fluidité.

---

## Vue d'ensemble

### Problème actuel

`main.lua:31` définit `UPDATE_RATE = 60` (1 update/sec). Après P2_04A, ce sera 10 (~6/sec). Mais ce taux fixe est sous-optimal :

- **Quand le joueur marche** : 6/sec peut encore causer des micro-saccades. Il faudrait 10-15/sec.
- **Quand le joueur est immobile** : même 1/sec gaspille de la bande passante. Il faudrait 0/sec (aucun envoi).
- **Quand le joueur court (B enfoncé)** : la vitesse double, il faudrait aussi doubler le taux d'envoi.

### Solution : Taux adaptatif

```
Immobile:    0 updates/sec    (envoyer 1x au moment de l'arrêt)
Marche:      10 updates/sec   (toutes les 6 frames)
Course:      15 updates/sec   (toutes les 4 frames)
Warp/Télé:   Envoi immédiat   (1 message instantané)
```

---

## Partie 1 — Détection d'état de mouvement

**Fichier à modifier :** `client/main.lua`

- [x] **1.1** Tracker l'état de mouvement du joueur

  Ajouter dans `State` (ligne 36) :
  ```lua
  State.isMoving = false
  State.lastMoveFrame = 0      -- Dernière frame où la position a changé
  State.sendCooldown = 0       -- Frames restantes avant prochain envoi autorisé
  ```

- [x] **1.2** Détecter mouvement dans `update()`

  Après `readPlayerPosition()` (ligne 367), comparer avec la position précédente :
  ```lua
  if currentPos and positionChanged(currentPos, State.lastPosition) then
    State.isMoving = true
    State.lastMoveFrame = State.frameCounter
  else
    -- Considérer immobile après 30 frames (~0.5sec) sans changement
    if State.frameCounter - State.lastMoveFrame > 30 then
      State.isMoving = false
    end
  end
  ```

---

## Partie 2 — Logique d'envoi adaptatif

**Fichier à modifier :** `client/main.lua`

- [x] **2.1** Remplacer la logique d'envoi fixe

  Actuellement (lignes 407-411) :
  ```lua
  if State.frameCounter % UPDATE_RATE == 0 then
    if positionChanged(currentPos, State.lastPosition) then
      sendPositionUpdate(currentPos)
      State.lastPosition = currentPos
    end
  end
  ```

  Remplacer par :
  ```lua
  local sendRate = State.isMoving and 6 or 0  -- 6 frames = 10/sec; 0 = pas d'envoi

  if sendRate > 0 and State.sendCooldown <= 0 then
    if positionChanged(currentPos, State.lastPosition) then
      sendPositionUpdate(currentPos)
      State.lastPosition = currentPos
      State.sendCooldown = sendRate
    end
  end

  -- Envoyer 1 update quand on s'arrête (position finale)
  if not State.isMoving and positionChanged(currentPos, State.lastSentPosition) then
    sendPositionUpdate(currentPos)
    State.lastSentPosition = currentPos
  end

  State.sendCooldown = math.max(0, State.sendCooldown - 1)
  ```

- [x] **2.2** Envoi immédiat sur changement de map

  Dans la logique de détection de mouvement, si `mapId` ou `mapGroup` a changé, envoyer immédiatement sans cooldown.

---

## Partie 3 — Configuration

- [x] **3.1** Ajouter constantes configurables dans `main.lua` (section Configuration) :

  ```lua
  local SEND_RATE_MOVING = 6     -- frames entre envois quand en mouvement (6 = 10/sec)
  local SEND_RATE_IDLE = 0       -- 0 = pas d'envoi quand immobile
  local IDLE_THRESHOLD = 30      -- frames sans mouvement = considéré immobile
  ```

---

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `client/main.lua:31` | Remplacer `UPDATE_RATE` fixe par système adaptatif |
| `client/main.lua:36` | Ajouter `isMoving`, `lastMoveFrame`, `sendCooldown` dans State |
| `client/main.lua:407-411` | Réécrire logique d'envoi avec taux adaptatif |

---

## Tests à effectuer

- [ ] **Test 1:** Joueur immobile → aucun message envoyé (vérifier logs serveur)
- [ ] **Test 2:** Joueur commence à marcher → envois commencent à ~10/sec
- [ ] **Test 3:** Joueur s'arrête → 1 dernier envoi (position finale), puis silence
- [ ] **Test 4:** Changement de map → envoi immédiat
- [ ] **Test 5:** Bande passante réduite en idle vs ancien système
- [ ] **Test 6:** Ghost toujours fluide pendant mouvement

---

## Critères de succès

✅ **Taux adaptatif complet** quand :
- Zéro envoi en idle
- ~10 envois/sec en mouvement
- Envoi immédiat sur changement de map
- Le ghost reste fluide (combiné avec P2_04A buffer temporel)
- Bande passante mesurée < 50% du système fixe à 10/sec constant

---

## Prochaine étape

Après cette tâche → **P2_04C_DEAD_RECKONING.md** (prédiction de mouvement)
