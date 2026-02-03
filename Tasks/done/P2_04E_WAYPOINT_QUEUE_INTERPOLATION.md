# Phase 2 - Interpolation Waypoint Queue

> **Statut:** Completed (2026-02-03)
> **Type:** Update — Refactoring du systeme d'interpolation
> **Priorite:** Haute
> **Objectif:** Remplacer le systeme "animate toward target" (une seule cible ecrasee) par une file de waypoints avec catch-up adaptatif universel, pour garantir la fidelite du parcours meme a tres haute vitesse (speedhack mGBA jusqu'a 250x+)

---

## Probleme actuel

### Symptome
Quand un joueur utilise le speedhack de mGBA (2x a 250x+), les ghosts sur les autres clients ne suivent pas le meme parcours. Un mouvement "droite, droite, bas" apparait comme un deplacement diagonal.

### Cause racine
`client/interpolate.lua` ne garde qu'une seule position cible (`animTo`). Quand un nouveau snapshot arrive, il **ecrase** la cible precedente (ligne 118):
```lua
-- client/interpolate.lua:117-118
player.animFrom = copyPos(player.current)
player.animTo = copyPos(newPosition)
```

En speedhack, plusieurs snapshots arrivent entre deux frames (ou dans un intervalle tres court). Toutes les positions intermediaires sont perdues — seule la derniere est conservee comme cible d'interpolation.

### Impact
- Parcours incorrect: le ghost prend des raccourcis diagonaux au lieu du vrai chemin
- Plus le speedhack est eleve, plus le probleme est visible
- Incompatible avec l'utilisation du speedhack en mode coop

---

## Solution: Waypoint Queue + Catch-up adaptatif

### Principe
Chaque position recue via le reseau est ajoutee a une **file FIFO** (queue) au lieu d'ecraser la cible. Le ghost consomme les waypoints **un par un, dans l'ordre**, garantissant que le parcours affiche est identique au parcours reel du joueur.

```
AVANT:  snapshot1 → [animTo] ← snapshot2 ecrase snapshot1 → mouvement diagonal
APRES:  snapshot1, snapshot2, snapshot3 → [queue: pos1, pos2, pos3] → consomme dans l'ordre
```

### Formule universelle de catch-up

**Une seule formule, pas de paliers:**

```
segmentDuration = BASE_DURATION / max(1, queueLength)
```

| Variable | Description |
|----------|-------------|
| `BASE_DURATION` | Duree naturelle d'un pas de marche (~250ms). Seule constante configurable. |
| `queueLength` | Nombre de waypoints restants dans la queue |
| `segmentDuration` | Duree d'interpolation pour le segment courant |

**Proprietes mathematiques:**
- Queue = 1 → 250ms (vitesse normale, marche standard)
- Queue = 10 → 25ms (10x plus rapide — speedhack modere)
- Queue = 50 → 5ms (50x plus rapide)
- Queue = 250 → 1ms (250x plus rapide)
- **Auto-regulation**: queue grossit → ghost accelere → queue se vide → ghost ralentit
- **Equilibre naturel**: le retard percu est toujours ~BASE_DURATION peu importe la vitesse du sender
- **Aucun threshold/palier/if-else**: la formule seule gere tous les cas de 1x a 1000x+

---

## Implementation

### Partie 1 — Nouvelle structure de donnees joueur

**Fichier:** `client/interpolate.lua`

Remplacer la structure `players[playerId]` actuelle (lignes 78-88) par:

```lua
players[playerId] = {
  current = copyPos(newPosition),  -- Position visuelle actuelle (inchangee)
  queue = {},                      -- FIFO de waypoints: {pos1, pos2, ...}
  animFrom = nil,                  -- Debut du segment courant (position precedente)
  animProgress = 0,                -- Progression [0, 1] sur le segment courant
  state = "idle",                  -- "idle" | "interpolating"
}
```

**Champs supprimes:**
- `lastReceived` → plus necessaire, remplace par le dernier element de la queue
- `lastTimestamp` → plus necessaire (la duree est calculee par la taille de la queue, pas par l'intervalle timestamp)
- `animTo` → remplace par `queue[1]` (le prochain waypoint a atteindre)
- `animDuration` → calcule dynamiquement a chaque frame via la formule

- [x] **1.1** Definir la nouvelle structure de donnees joueur
- [x] **1.2** Ajouter la constante `BASE_DURATION = 250` (ms) en remplacement de `DEFAULT_ANIM_DURATION`, `MIN_ANIM_DURATION`, `MAX_ANIM_DURATION`
- [x] **1.3** Ajouter la constante `MAX_QUEUE_SIZE = 1000` (filet de securite memoire)

---

### Partie 2 — Refactoring de `Interpolate.update()`

**Fichier:** `client/interpolate.lua`, fonction `Interpolate.update()` (actuellement lignes 69-125)

**Comportement actuel:** ecrase `animTo` avec la nouvelle position.
**Nouveau comportement:** ajoute la position a la queue.

- [x] **2.1** Premier snapshot (joueur inconnu): snap direct a la position, queue vide (inchange)
- [x] **2.2** Snapshots suivants: `table.insert(player.queue, copyPos(newPosition))` au lieu d'ecraser animTo
- [x] **2.3** Detection de teleportation entre waypoints consecutifs:
  - Comparer `newPosition` avec le **dernier element de la queue** (ou `player.current` si queue vide)
  - Si changement de map OU distance > `TELEPORT_THRESHOLD`: **flush** la queue, snap au nouveau point
  - IMPORTANT: ne PAS comparer avec `player.current` (qui est la position interpolee, potentiellement loin derriere)
- [x] **2.4** Deduplication: si la nouvelle position est identique (meme x, y, mapId, mapGroup) au dernier element de la queue (ou a `player.current` si queue vide), ignorer (ne pas ajouter). Le `facing` seul ne justifie PAS un nouveau waypoint (eviter les waypoints immobiles).
  - Exception: si seul le `facing` change et la queue est vide, mettre a jour `player.current.facing` directement
- [x] **2.5** Queue overflow: si `#player.queue > MAX_QUEUE_SIZE`, flush la queue et snap au dernier point recu. Log un warning.
- [x] **2.6** Le parametre `timestamp` n'est plus utilise pour calculer la duree d'animation. Le conserver dans la signature pour compatibilite API mais ne pas l'utiliser en interne.

---

### Partie 3 — Refactoring de `Interpolate.step()`

**Fichier:** `client/interpolate.lua`, fonction `Interpolate.step()` (actuellement lignes 133-167)

C'est le coeur du changement. Le step doit pouvoir **consommer plusieurs waypoints par frame** a haute vitesse.

- [x] **3.1** Implementer la boucle de consommation multi-waypoints:

```lua
function Interpolate.step(dt)
  dt = dt or 16.67

  for _, player in pairs(players) do
    if #player.queue == 0 then
      player.state = "idle"
    else
      player.state = "interpolating"
      local remaining = dt  -- temps restant a consommer dans cette frame

      while remaining > 0 and #player.queue > 0 do
        -- Initialiser le debut du segment si necessaire
        if not player.animFrom then
          player.animFrom = copyPos(player.current)
        end

        -- Formule universelle: duree proportionnelle inverse a la taille de la queue
        local segDuration = BASE_DURATION / math.max(1, #player.queue)

        -- Combien de temps reste pour finir ce segment?
        local timeLeftInSegment = (1 - player.animProgress) * segDuration

        if remaining >= timeLeftInSegment then
          -- Ce segment est termine dans cette frame
          remaining = remaining - timeLeftInSegment

          -- Snap au waypoint cible
          local target = player.queue[1]
          player.current = copyPos(target)

          -- Pop le waypoint consomme
          table.remove(player.queue, 1)

          -- Reset pour le prochain segment
          player.animFrom = copyPos(player.current)
          player.animProgress = 0
        else
          -- Frame terminee au milieu d'un segment
          player.animProgress = player.animProgress + remaining / segDuration

          local t = player.animProgress
          local target = player.queue[1]
          player.current.x = lerp(player.animFrom.x, target.x, t)
          player.current.y = lerp(player.animFrom.y, target.y, t)
          player.current.mapId = target.mapId
          player.current.mapGroup = target.mapGroup

          -- Facing: basculer au point median
          if t >= 0.5 then
            player.current.facing = target.facing
          end

          remaining = 0  -- frame terminee
        end
      end

      -- Apres la boucle: si queue vide, on est idle
      if #player.queue == 0 then
        player.state = "idle"
        player.animFrom = nil
        player.animProgress = 0
      end
    end
  end
end
```

- [x] **3.2** Le `queueLength` est relu a chaque iteration de la boucle while (`#player.queue`) car il change quand on pop un waypoint. C'est essentiel: sans ca, la vitesse ne s'adapte pas pendant la frame.
- [x] **3.3** Quand un segment est consomme en moins d'une frame (haute vitesse), le facing du waypoint est applique directement (pas de point median — le segment est trop court pour que ce soit visible).
- [x] **3.4** Protection: si `dt <= 0`, return early sans rien faire.
- [x] **3.5** ATTENTION a `table.remove(queue, 1)`: c'est O(n) en Lua. Pour une queue de 1000 elements, ca peut devenir couteux. **Solution optionnelle**: utiliser un index de tete (`queueHead`) au lieu de table.remove, et compacter periodiquement. A implementer si le profiling montre un probleme, sinon `table.remove` est suffisant pour des queues < 1000.

---

### Partie 4 — Fonctions utilitaires inchangees

**Fichier:** `client/interpolate.lua`

Ces fonctions/API restent identiques:

- [x] **4.1** `Interpolate.getPosition(playerId)` — retourne `players[playerId].current` (inchange)
- [x] **4.2** `Interpolate.getState(playerId)` — retourne "interpolating" si queue non vide, "idle" sinon
- [x] **4.3** `Interpolate.remove(playerId)` — `players[playerId] = nil` (inchange, nettoie la queue automatiquement)
- [x] **4.4** `Interpolate.getPlayers()` — inchange
- [x] **4.5** `Interpolate.setTeleportThreshold(threshold)` — inchange
- [x] **4.6** Helpers `copyPos()`, `distance()`, `isSameMap()`, `lerp()` — inchanges

---

### Partie 5 — Verification integration `main.lua`

**Fichier:** `client/main.lua`

Normalement AUCUN changement requis dans main.lua car l'API publique est preservee. Verifier:

- [x] **5.1** Ligne 384: `Interpolate.step(16.67)` — OK, inchange
- [x] **5.2** Ligne 441: `Interpolate.update(message.playerId, message.data, message.t)` — OK, meme signature
- [x] **5.3** Ligne 363: `Interpolate.getPosition(playerId)` — OK, meme retour
- [x] **5.4** Ligne 449: `Interpolate.remove(message.playerId)` — OK, inchange
- [x] **5.5** L'envoi adaptatif (lignes 496-511) envoie deja une position a chaque changement de tile (`SEND_RATE_MOVING = 1`). C'est exactement ce dont la queue a besoin: un waypoint par tile traversee.
- [x] **5.6** Verifier qu'aucun autre module ne depend de champs internes supprimes (`lastReceived`, `lastTimestamp`, `animTo`, `animDuration`)

---

### Partie 6 — Suppression du code mort

**Fichier:** `client/interpolate.lua`

- [x] **6.1** Supprimer les constantes devenues inutiles: `DEFAULT_ANIM_DURATION`, `MIN_ANIM_DURATION`, `MAX_ANIM_DURATION`
- [x] **6.2** Supprimer la logique de calcul de duree basee sur les timestamps (lignes 107-114 actuelles)
- [x] **6.3** Supprimer les champs `lastReceived`, `lastTimestamp`, `animTo`, `animDuration` de la structure joueur

---

## Configuration

| Constante | Valeur | Description |
|-----------|--------|-------------|
| `BASE_DURATION` | 250 | Duree naturelle d'un pas (ms). Controle la vitesse de base du ghost. |
| `TELEPORT_THRESHOLD` | 10 | Distance en tiles au-dela de laquelle on snap (inchange) |
| `MAX_QUEUE_SIZE` | 1000 | Taille max de la queue (filet de securite) |

**Note:** `BASE_DURATION` est la seule constante qui affecte le comportement. 250ms correspond a la duree d'une animation de marche GBA (~16 frames a 60fps). Ajuster si le feeling est trop lent ou trop rapide.

---

## Edge cases detailles

| # | Scenario | Comportement attendu |
|---|----------|---------------------|
| 1 | Queue vide, joueur immobile | State "idle", rien ne se passe |
| 2 | Un seul waypoint | Lerp normal a BASE_DURATION ms — identique au systeme actuel |
| 3 | Burst reseau (lag puis rattrapage) | Queue grossit d'un coup, ghost accelere automatiquement |
| 4 | Joueur arrete apres speedhack | Queue se vide progressivement, ghost ralentit jusqu'a idle |
| 5 | Positions dupliquees (meme x,y) | Ignorees a l'ajout (deduplication, Partie 2.4) |
| 6 | Changement de map en speedhack | Teleport detecte, queue flush, snap immediat |
| 7 | Speedhack 250x pendant 10 secondes | Queue monte a ~250, `segDuration` = 1ms, ghost consomme ~16 waypoints/frame (16.67ms / 1ms) |
| 8 | dt = 0 ou negatif | Return early, rien ne se passe |
| 9 | Queue atteint MAX_QUEUE_SIZE | Flush + snap + warning log |
| 10 | Deconnexion du sender | `Interpolate.remove()` nettoie la queue |
| 11 | Facing change sans mouvement | Mise a jour directe de current.facing (pas de waypoint ajoute) |
| 12 | Nouveau joueur rejoint | Snap a la premiere position (inchange) |
| 13 | Plusieurs ghosts avec des queues de tailles differentes | Chaque ghost a sa propre queue, independante — un ghost en speedhack n'affecte pas les autres |

---

## Tests a effectuer

### Test 1: Comportement normal (sans speedhack)
- [ ] Ghost se deplace fluidement (pas de saccade)
- [ ] Parcours identique au joueur reel (droite-droite-bas = droite-droite-bas, pas de diagonale)
- [ ] Arret propre quand le joueur s'arrete (pas de glissement)
- [ ] Direction (facing) correcte a chaque etape

### Test 2: Speedhack modere (2x-4x)
- [ ] Ghost accelere visiblement mais suit le bon parcours
- [ ] Pas de diagonale sur des mouvements en L
- [ ] La queue ne croit pas indefiniment (se stabilise)

### Test 3: Speedhack extreme (50x-250x)
- [ ] Ghost suit le parcours correct (meme si tres rapidement)
- [ ] Pas de freeze ou lag sur le client recepteur
- [ ] La queue se vide quand le joueur s'arrete
- [ ] Performance acceptable (pas de spike CPU a cause de table.remove en boucle)

### Test 4: Teleportation
- [ ] Changement de map: snap immediat, queue videe
- [ ] Grand deplacement (> 10 tiles): snap immediat

### Test 5: Reseau
- [ ] Lag simule puis rattrapage: ghost accelere pour rattraper
- [ ] Deconnexion/reconnexion: ghost disparait puis reapparait correctement

### Test 6: Multi-ghosts
- [ ] 2+ ghosts avec des vitesses differentes (un en speedhack, un normal)
- [ ] Chaque ghost a son propre rythme, pas d'interference

---

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `client/interpolate.lua` | Refactoring complet: queue FIFO, formule catch-up, boucle multi-waypoints |

## Fichiers a verifier (pas de modification attendue)

| Fichier | Verification |
|---------|-------------|
| `client/main.lua` | API identique — confirmer qu'aucun champ interne n'est accede directement |
| `client/render.lua` | Consomme `Interpolate.getPosition()` — aucun changement |

---

## Criteres de succes

1. Le ghost suit exactement le meme parcours que le joueur reel, a toute vitesse
2. Pas de mouvement diagonal quand le joueur fait des angles droits
3. La formule `BASE_DURATION / queueLength` gere tous les cas sans palier
4. Performance stable: pas de spike CPU meme avec une queue de 200+ waypoints
5. API publique `Interpolate.*` inchangee: zero modification dans main.lua et render.lua
6. Le systeme fonctionne identiquement a l'ancien pour un seul waypoint (vitesse normale)

---

## Prochaine etape

`Tasks/todo/P2_07_OPTIMIZATION.md` — Profiling et optimisation performance (inclura le profiling de la queue si necessaire)
