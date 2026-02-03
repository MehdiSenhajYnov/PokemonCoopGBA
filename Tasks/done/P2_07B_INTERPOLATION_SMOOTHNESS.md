# Phase 2 - Fluidite du mouvement ghost (interpolation smoothness)

> **Statut:** Completed (2026-02-03)
> **Type:** Optimisation — Eliminer les micro-saccades entre les pas et les ralentissements a l'arrivee
> **Priorite:** Haute
> **Objectif:** Rendre le mouvement ghost totalement fluide en corrigeant 5 problemes dans le frame loop et le systeme d'interpolation.

---

## Probleme actuel

Le ghost a des micro-saccades visibles:
- **En debut/fin de chaque pas:** Le ghost s'arrete brievement (~1-2 frames) avant de continuer au pas suivant
- **Pendant le mouvement continu (plus rare):** A-coups de vitesse quand la queue oscille entre 1 et 2 elements
- Le mouvement continu sans arret est relativement fluide, ce qui pointe vers des problemes de transition entre waypoints

---

## Causes identifiees et fixes

### Fix 1 — Ordre receive/step dans le frame loop (IMPACT FORT)

**Fichier:** `client/main.lua`
**Probleme:** `Interpolate.step(16.67)` (ligne 414) est appele AVANT la reception des messages (ligne 462-501). Chaque frame, le ghost avance d'abord, vide potentiellement sa queue, passe en idle, puis recoit le prochain waypoint. Resultat: **1 frame de pause systematique** entre chaque pas.

```
Frame N:  step() → queue vide → ghost IDLE
          receive() → nouveau waypoint ajoute a la queue
Frame N+1: step() → consomme le waypoint (1 frame de retard)
```

**Fix:** Deplacer le bloc de reception (lignes 462-501) AVANT `Interpolate.step()` (ligne 414). L'interpolation et la reconnexion/deconnexion restent apres.

- [x] **1.1** Deplacer le bloc `if State.connected then ... receive ... end` (lignes 462-501) juste avant `Interpolate.step()` (ligne 414), apres `State.timeMs` (ligne 411)
- [x] **1.2** Verifier que la deconnexion/reconnexion (lignes 433-460) reste AVANT le receive (pour ne pas traiter des messages sur une socket morte)

**Impact:** Le waypoint est dans la queue AVANT que step() ne tourne. Le ghost ne passe plus en idle entre deux pas consecutifs.

---

### Fix 2 — Padding de duree pour absorber la latence reseau (IMPACT FORT)

**Fichier:** `client/interpolate.lua`
**Probleme:** Meme en localhost, il y a ~2 frames de latence incompressible (flush fin de frame sender + TCP transit + receive frame suivant receiver). Le ghost finit son interpolation avant que le prochain waypoint n'arrive → micro-pause visible.

**Fix:** Apres le calcul de `duration` dans `Interpolate.update()` (ligne 158), multiplier par un facteur de padding:

```lua
duration = math.floor(duration * 1.08)  -- 8% padding absorbs network jitter
```

- [x] **2.1** Ajouter la ligne de padding apres le bloc de calcul de duration (apres ligne 158, avant ligne 159 `player.lastTimestamp = timestamp`)

**Impact:** Le ghost interpole 8% plus lentement (~21ms sur un pas de marche de 266ms). Le prochain waypoint arrive avant qu'il finisse → transition seamless. Le catch-up formula (diviseur queue length) corrige l'accumulation automatiquement.

---

### Fix 3 — Inverser la priorite duration: timestamp delta > camera hint (IMPACT MOYEN)

**Fichier:** `client/interpolate.lua`
**Probleme:** Le hint camera (`durationHint`, base sur 1 frame de scroll) est prioritaire meme pour les pas consecutifs (lignes 150-158). Or le delta timestamp mesure le gap reel entre deux envois — plus fiable pour les pas consecutifs car moyenne sur tout le pas, pas juste 1 frame de camera.

Le scroll camera GBA peut varier frame a frame (acceleration/deceleration au debut/fin de la marche), rendant le hint imprecis.

**Fix:** Inverser la logique dans le calcul de duration (lignes 150-158):

```lua
local duration = DEFAULT_DURATION
if timestamp and player.lastTimestamp then
  local dt = timestamp - player.lastTimestamp
  if dt >= MIN_DURATION and dt <= DEFAULT_DURATION * 2 then
    duration = dt  -- Consecutive step: use actual timing
  elseif durationHint and durationHint >= MIN_DURATION and durationHint <= MAX_DURATION then
    duration = durationHint  -- Idle gap: use camera estimate
  end
elseif durationHint and durationHint >= MIN_DURATION and durationHint <= MAX_DURATION then
  duration = durationHint  -- No previous timestamp: use camera estimate
end
```

- [x] **3.1** Remplacer le bloc de calcul de duration (lignes 150-158) par la version avec priorite inversee

**Impact:** Pas consecutifs utilisent le timing reel (plus stable). Premier pas apres idle utilise le hint camera (adapte walk/run/bike). Fallback `DEFAULT_DURATION` si rien n'est disponible.

---

### Fix 4 — Utiliser le vrai delta temps au lieu de 16.67ms fixe (IMPACT MOYEN)

**Fichier:** `client/main.lua`
**Probleme:** `Interpolate.step(16.67)` (ligne 414) et `State.timeMs = State.timeMs + 16.67` (ligne 411) assument un 60fps parfait. Si un frame prend 25ms (GC Lua, occlusion lourde, pic CPU), l'interpolation n'avance que de 16.67ms → ghost en retard. Frame suivant rapide → ghost en avance. Cree des micro-accelerations/decelerations visibles.

**Fix:** Tracker le temps reel avec `os.clock()`:

```lua
-- Variable locale au module (avant update()):
local lastClock = os.clock()

-- Dans update(), remplacer le bloc ligne 410-414:
local now = os.clock()
local realDt = math.max(5, math.min(50, (now - lastClock) * 1000))  -- ms, clamped [5, 50]
lastClock = now

State.frameCounter = State.frameCounter + 1
State.timeMs = State.timeMs + realDt

-- ... (receive deplace ici par Fix 1) ...

Interpolate.step(realDt)
```

- [x] **4.1** Ajouter `local lastClock = os.clock()` comme variable locale du module (avant la fonction `update()`)
- [x] **4.2** Dans `update()`, remplacer `State.timeMs = State.timeMs + 16.67` (ligne 411) par le calcul `realDt` via `os.clock()`
- [x] **4.3** Remplacer `Interpolate.step(16.67)` (ligne 414) par `Interpolate.step(realDt)`

**Note:** Sur Windows (plateforme du projet), `os.clock()` retourne le wall time. Le clamp [5, 50] protege contre les valeurs extremes (pause debugger, premier frame).

**Impact:** L'interpolation suit le temps reel. Frame drops et variations sont compenses naturellement.

---

### Fix 5 — Courbe de catch-up plus douce (IMPACT MOYEN)

**Fichier:** `client/interpolate.lua`
**Probleme:** `segDuration = wpDuration / math.max(1, #player.queue)` (ligne 205). Quand la queue passe de 1→2 elements, la vitesse **double instantanement**. Quand le premier waypoint est consomme (queue 2→1), la vitesse est **divisee par 2**. Cree des a-coups de vitesse visibles pendant le mouvement continu.

**Fix:** Remplacer le diviseur (ligne 205):

```lua
-- Avant:
local segDuration = wpDuration / math.max(1, #player.queue)
-- Apres:
local segDuration = wpDuration / math.max(1, 1 + 0.5 * (#player.queue - 1))
```

Resultat par taille de queue:
| Queue | Ancien diviseur | Nouveau diviseur | Vitesse relative |
|-------|----------------|-----------------|-----------------|
| 1 | /1 | /1 | 1x (normal) |
| 2 | /2 | /1.5 | 1.5x (au lieu de 2x) |
| 3 | /3 | /2 | 2x (au lieu de 3x) |
| 5 | /5 | /3 | 3x (au lieu de 5x) |
| 10 | /10 | /5.5 | 5.5x (au lieu de 10x) |

- [x] **5.1** Remplacer la ligne 205 par la nouvelle formule avec `1 + 0.5 * (#player.queue - 1)`

**Impact:** Transitions de vitesse plus douces entre les pas. Pour le speedhack extreme, le catch-up est un peu moins agressif mais le `MAX_QUEUE_SIZE` (1000) protege les cas extremes.

---

## Ordre d'implementation recommande

1. **Fix 1** (deplacer receive) — le changement le plus impactant, 0 risque
2. **Fix 3** (priorite dt>hint) — corrige la precision des durees
3. **Fix 2** (padding 1.08x) — absorbe le jitter restant apres Fix 1
4. **Fix 5** (catch-up doux) — lisse les transitions de vitesse
5. **Fix 4** (os.clock) — compense les variations de framerate

Chaque fix est testable independamment. Aucun ne modifie le protocole reseau ni le serveur.

---

## Fichiers a modifier

| Fichier | Modifications |
|---------|--------------|
| `client/main.lua` | Fix 1 (deplacer bloc receive avant step), Fix 4 (os.clock realDt) |
| `client/interpolate.lua` | Fix 2 (padding 1.08x), Fix 3 (priorite dt>hint), Fix 5 (catch-up doux) |

## Fichiers NON modifies

| Fichier | Raison |
|---------|--------|
| `server/server.js` | Aucun changement de protocole |
| `client/network.lua` | Transport inchange |
| `client/render.lua` | Utilise `Interpolate.getPosition()` — API inchangee |
| `client/sprite.lua` | Independant du systeme de position |
| `client/occlusion.lua` | Independant du systeme de position |
| `client/hal.lua` | Aucune nouvelle lecture memoire necessaire |

---

## Tests a effectuer

### Test 1: Mouvement continu
- [ ] Marcher 10+ pas sans s'arreter → transitions entre pas sans micro-pauses
- [ ] Visuellement: le ghost doit glisser de maniere continue, pas "pas-pause-pas-pause"

### Test 2: Debut de mouvement
- [ ] Premier pas apres un arret → pas de ralentissement visible
- [ ] Course et velo → premier pas a la bonne vitesse

### Test 3: Fin de mouvement
- [ ] Ghost s'arrete proprement sans saccade a l'arrivee
- [ ] Pas de "drift" apres l'arret (ghost ne continue pas au-dela)

### Test 4: Vitesses variables
- [ ] Course → vitesse correcte, pas de stuttering
- [ ] Velo → vitesse correcte, pas de stuttering
- [ ] Speedhack 2x/4x → ghost suit sans queue overflow

### Test 5: Frame drops
- [ ] Occlusion lourde (beaucoup de tiles BG1) → ghost compense automatiquement
- [ ] Pas d'acceleration/deceleration visible pendant les pics de charge

### Test 6: Changement de map
- [ ] Warp/teleportation → toujours clean, pas de residu d'interpolation

---

## Criteres de succes

1. Mouvement continu sans aucune micro-pause visible entre les pas
2. Debut et fin de mouvement fluides
3. Pas de regression sur: early detection, prediction, idle correction, speedhack
4. Performance: aucun overhead mesurable (les fixes sont tous des changements de calcul, pas de nouvelles lectures memoire)
