# Fix complet du systeme de duel PvP

> **Statut:** En attente d'implementation
> **Type:** Bug Fix — 5 bugs critiques empechent le duel PvP de fonctionner
> **Priorite:** P0 - CRITIQUE
> **Prerequis:** P3_10A_SCAN_BATTLE_ADDRESSES.md (adresses manquantes trouvees)
> **Date creation:** 2026-02-05

---

## Probleme

Le systeme de duel PvP est non-fonctionnel. Les logs montrent:
```
[PokéCoop] No golden state — using door fallback mode
[PokéCoop] Enter any door to start the duel!
[PokéCoop] Duel warp received: 2:2 (8,4) master=false     ← MAUVAISE MAP
[Battle] Battle configured: flags=0x08000008 master=false
[PokéCoop] PvP battle started!
[PokéCoop] Battle finished: unknown                         ← INSTANTANE
```

Le flow attendu (Demande → Accept → Warp → Combat → Fin → Retour) echoue a 5 endroits.

---

## Causes identifiees (par priorite)

### P0 - CRITIQUE

#### 1. Server envoie les mauvaises coordonnees
**Fichier:** `server/server.js:18-25`

```javascript
const DUEL_ROOM = {
  mapGroup: 2,    // ← FAUX — devrait etre 28
  mapId: 2,       // ← FAUX — devrait etre 24
  playerAX: 5,    // ← FAUX — devrait etre 3
  playerAY: 4,    // ← FAUX — devrait etre 5
  playerBX: 8,    // ← FAUX — devrait etre 10
  playerBY: 4     // ← FAUX — devrait etre 5
};
```

**Impact:** Les joueurs sont teleportes dans un Pokemon Center (2:2) au lieu de Battle Colosseum 2P (28:24).
**Fix:** Utiliser les coordonnees de `config/run_and_bun.lua:37-44` (duelRoom section).

---

#### 2. Premier duel oblige a entrer dans un batiment (door fallback)
**Fichier:** `client/main.lua:874-882`

```lua
-- === MODE FALLBACK: Door Interception ===
log("No golden state — using door fallback mode")
log("Enter any door to start the duel!")
State.inputsLocked = true
State.warpPhase = "waiting_door"
State.unlockFrame = State.frameCounter + 1800  -- 30 seconds to find a door
```

**Impact:** Sans golden state (premier duel de la session), le joueur doit physiquement entrer dans un batiment.
**Fix:** Utiliser `HAL.triggerMapLoad()` (`hal.lua:533-561`) qui existe deja mais n'est jamais appele. Cette fonction:
- NULL callback1 a +0x00 (ligne 541)
- NULL savedCallback a +0x08 (ligne 544)
- Clear interrupt callbacks (lignes 547-550)
- Zero gMain.state a +0x35 (ligne 553)
- Set callback2 = CB2_LoadMap (ligne 556)

Le code de remplacement:
1. `HAL.blankScreen()` (hal.lua:589) — ecran noir pour transition propre
2. `HAL.writeWarpData(coords)` — ecrire destination dans sWarpData
3. `HAL.triggerMapLoad()` — forcer CB2_LoadMap
4. `State.warpPhase = "loading"` — attendre completion normalement

Le watchpoint capturera le golden state automatiquement lors de ce premier warp (ligne 489-491). Les duels suivants utiliseront le golden state hijack (plus rapide).

---

#### 3. Le combat ne demarre JAMAIS
**Fichier:** `client/battle.lua:173-213`

`Battle.startBattle()` ecrit `gBattleTypeFlags` (ligne 194) et `gTrainerBattleOpponent_A` (ligne 200) mais ne dit **jamais au jeu de demarrer le combat**. Il manque: `gMain.callback2 = CB2_InitBattle`.

**Impact:** Le jeu reste en mode overworld. Les flags de combat sont ecrits mais personne ne les lit.

**Fix en 2 parties:**

**Partie A — Auto-detection CB2_InitBattle (client/main.lua):**
- Chaque frame, lire `gMain.inBattle` a `0x0202067F` (adresse corrigee)
- Tracker `prevInBattle` dans State
- Quand transition 0→1: lire `HAL.readCallback2()` → c'est CB2_InitBattle
- Stocker l'adresse dans Battle module via `Battle.setCB2InitBattle(addr)`
- Ceci se produit automatiquement quand le joueur entre dans un combat naturel (herbes, dresseur)

**Partie B — Trigger battle (client/hal.lua + client/battle.lua):**
- Ajouter `HAL.triggerBattle(cb2InitBattle)` dans hal.lua:
  - NULL callback1 a gMain+0x00 (comme triggerMapLoad ligne 541)
  - Zero gMain.state a gMain+0x35 (comme triggerMapLoad ligne 553)
  - Set callback2 = cb2InitBattle
- Modifier `Battle.startBattle()` pour appeler `HAL.triggerBattle()` apres avoir ecrit les flags
- Si CB2_InitBattle pas encore detecte → retourner false + log "Enter any battle to calibrate PvP"

---

#### 4. Le combat "finit" instantanement
**Fichier:** `client/battle.lua:448-452` + `config/run_and_bun.lua:61`

```lua
-- battle.lua:448-452 (Method 2 dans isFinished)
if ADDRESSES and ADDRESSES.gMainInBattle then
  local ok, inBattle = pcall(emu.memory.wram.read8, emu.memory.wram,
    toWRAMOffset(ADDRESSES.gMainInBattle))
  if ok and inBattle == 0 then
    return true  -- ← RETOURNE TRUE IMMEDIATEMENT
  end
end
```

```lua
-- config/run_and_bun.lua:61
gMainInBattle = 0x020233E0,  -- FAUX! C'est dans gPlayerParty (offset +0x10)
```

**Impact:** `0x020233E0` lit un byte dans les donnees du premier Pokemon (otId). Ce byte est souvent 0, donc `isFinished()` retourne true des le premier appel → "Battle finished: unknown" instantanement.

**Fix:** Changer `config/run_and_bun.lua:61`:
```lua
gMainInBattle = 0x0202067F,  -- gMain base (0x02020648) + 0x37
```

---

#### 5. L'outcome est toujours "unknown"
**Fichier:** `client/battle.lua:463-479`

```lua
function Battle.getOutcome()
  if not ADDRESSES or not ADDRESSES.gBattleOutcome then
    return nil  -- ← TOUJOURS NIL (gBattleOutcome = nil dans config)
  end
```

**Impact:** Sans `gBattleOutcome`, le resultat du combat est inconnu.

**Fix:**
- Prerequis: trouver l'adresse via P3_10A (scan_battle_outcome.lua corrige)
- Remplir `config/run_and_bun.lua:58` avec l'adresse trouvee
- En attendant, ajouter un fallback dans `getOutcome()`: si gBattleOutcome nil, retourner "completed" (au lieu de nil)

---

## Plan d'implementation

### Phase 1 : Fix immediats (pas de scan necessaire)

- [ ] **1.1** Corriger `server/server.js:18-25` — DUEL_ROOM coords: `{28, 24, 3, 5, 10, 5}`
- [ ] **1.2** Corriger `config/run_and_bun.lua:61` — gMainInBattle: `0x020233E0` → `0x0202067F`
- [ ] **1.3** Ajouter `gMainBase = 0x02020648` et `gMainState = 0x0202067D` dans config battle section

### Phase 2 : Warp direct sans porte (client/main.lua + client/hal.lua)

- [ ] **2.1** Remplacer le bloc door fallback (`main.lua:874-882`) par:
  - `HAL.blankScreen()`
  - `HAL.writeWarpData(coords.mapGroup, coords.mapId, coords.x, coords.y)`
  - `HAL.triggerMapLoad()`
  - `State.warpPhase = "loading"` + `State.unlockFrame = frameCounter + 300`
- [ ] **2.2** Supprimer la phase "waiting_door" dans le state machine (`main.lua:516-527`)
- [ ] **2.3** Supprimer l'overlay "Enter any door" (`main.lua:443-462`)
- [ ] **2.4** Supprimer la logique door fallback dans le watchpoint handler (`main.lua:494-510`)

### Phase 3 : Auto-detection CB2_InitBattle (client/main.lua + client/hal.lua)

- [ ] **3.1** Ajouter `HAL.readInBattle()` dans hal.lua — lire gMain.inBattle a offset +0x37
- [ ] **3.2** Ajouter `State.prevInBattle = 0` dans les variables State (`main.lua:84-102`)
- [ ] **3.3** Ajouter `State.cb2InitBattle = nil` dans State
- [ ] **3.4** Dans la boucle principale (apres watchpoint processing, avant warp state machine):
  - Lire inBattle via `HAL.readInBattle()`
  - Si transition 0→1 et `State.cb2InitBattle == nil`:
    - `State.cb2InitBattle = HAL.readCallback2()`
    - `Battle.setCB2InitBattle(State.cb2InitBattle)`
    - Log "Battle system calibrated! CB2_InitBattle = 0x%08X"
  - `State.prevInBattle = inBattle`
- [ ] **3.5** Log au demarrage: "Enter any battle to calibrate PvP" si CB2_InitBattle inconnu

### Phase 4 : Trigger de combat (client/hal.lua + client/battle.lua)

- [ ] **4.1** Ajouter `HAL.triggerBattle(cb2InitBattle)` dans hal.lua:
  - Meme pattern que `triggerMapLoad()` (lignes 533-561) mais avec cb2InitBattle au lieu de cb2LoadMap
  - NULL callback1 (`gMainBase + 0x00`)
  - Zero gMain.state (`gMainBase + 0x35`)
  - Set callback2 = cb2InitBattle (`gMainBase + 0x04`)
- [ ] **4.2** Ajouter dans battle.lua:
  - Variable locale `cb2InitBattle = nil`
  - `Battle.setCB2InitBattle(addr)` — setter
  - `Battle.hasCB2InitBattle()` — checker
- [ ] **4.3** Modifier `Battle.startBattle()` (lignes 173-213):
  - Apres avoir ecrit gBattleTypeFlags et gTrainerBattleOpponent_A
  - Si `cb2InitBattle` connu: appeler `HAL.triggerBattle(cb2InitBattle)`
  - Sinon: log erreur + retourner false
- [ ] **4.4** Passer HAL en dependance de Battle.init() ou via fonction globale

### Phase 5 : Fix detection fin de combat (client/battle.lua + client/main.lua)

- [ ] **5.1** Modifier `Battle.isFinished()` (lignes 435-457):
  - Utiliser `HAL.readInBattle()` au lieu de lire ADDRESSES.gMainInBattle directement
  - Condition: `inBattle` etait 1 (combat en cours) ET maintenant 0 → fini
  - Tracker `battleState.prevInBattle` pour detecter la transition 1→0
- [ ] **5.2** Modifier `Battle.getOutcome()` (lignes 463-479):
  - Si gBattleOutcome disponible: utiliser comme avant
  - Sinon: retourner `"completed"` au lieu de nil
- [ ] **5.3** Dans main.lua phase "in_battle" (lignes 648-656):
  - Quand `Battle.isFinished()` → envoyer duel_end + transition "returning"

### Phase 6 : Integration et polish

- [ ] **6.1** Verifier que le retour ("returning" phase, `main.lua:659-695`) fonctionne:
  - Golden state garanti disponible (capture pendant le warp aller)
  - saveGameData → loadGoldenState → restoreGameData → writeWarpData(origin)
- [ ] **6.2** Verifier les timeouts a chaque phase
- [ ] **6.3** Tester la deconnexion pendant le combat (`main.lua:949-963`)
- [ ] **6.4** Nettoyer les logs debug excessifs

---

## Fichiers a modifier

| Fichier | Modifications |
|---------|--------------|
| `server/server.js:18-25` | DUEL_ROOM: `{2,2,5,4,8,4}` → `{28,24,3,5,10,5}` |
| `config/run_and_bun.lua:58-69` | gMainInBattle fix + ajouter gMainBase/gMainState |
| `client/hal.lua` | Ajouter `readInBattle()`, `triggerBattle(cb2)` |
| `client/battle.lua` | CB2_InitBattle storage, fix `startBattle()`, fix `isFinished()`, fix `getOutcome()` |
| `client/main.lua` | Remplacer door fallback, auto-detection CB2_InitBattle, fix in_battle phase |

---

## Experience utilisateur finale

```
1. Premier lancement → log "Enter any battle to calibrate PvP"
2. Joueur entre dans les herbes → combat sauvage → "Battle system calibrated!"
3. Joueur A presse A pres du ghost de B → "Duel request sent"
4. Joueur B accepte (A) → "Duel accepted"
5. Les deux warpent INSTANTANEMENT vers Battle Colosseum (28:24)
   (pas de porte! triggerMapLoad ou golden state hijack)
6. Echange d'equipes automatique (600 bytes chacun)
7. Combat PvP demarre (CB2_InitBattle)
8. Joueurs combattent normalement (choix synchronises via reseau)
9. Fin de combat → "Battle finished: completed"
10. Retour automatique a la position d'origine
```

**Note:** L'etape 2 (calibration) est necessaire UNE SEULE FOIS par session.

---

## Test plan

- [ ] Verifier warp vers map 28:24 (pas 2:2) — les deux joueurs arrivent a (3,5) et (10,5)
- [ ] Verifier warp direct sans porte (triggerMapLoad au premier duel)
- [ ] Verifier que le golden state est capture pendant le premier warp
- [ ] Verifier que le second duel utilise le golden state hijack (plus rapide)
- [ ] Entrer dans un combat sauvage → CB2_InitBattle auto-detecte
- [ ] Verifier que startBattle() trigger le combat via CB2_InitBattle
- [ ] Verifier que isFinished() detecte la fin correctement (pas instantanement)
- [ ] Verifier le retour a l'origine apres le combat
- [ ] Tester deconnexion pendant le combat → retour propre
- [ ] Tester timeout de choix adverse (30 sec)
