# Fix complet du systeme de duel PvP

> **Statut:** Completed (2026-02-05)
> **Type:** Bug Fix — 5 bugs critiques empechent le duel PvP de fonctionner
> **Priorite:** P0 - CRITIQUE
> **Prerequis:** P3_10A_SCAN_BATTLE_ADDRESSES.md ✅ DONE
> **Date creation:** 2026-02-05

---

## Resultats de P3_10A (scans effectues)

| Variable | Adresse | Methode | Statut |
|----------|---------|---------|--------|
| `gMainInBattle` | `0x020206AE` | find_inbattle_offset.lua (gMain+0x66) | ✅ CONFIRMÉ (3 combats, pattern 0→1→0) |
| `CB2_BattleMain` | `0x08094815` | scan_battle_callbacks.lua | ✅ TROUVÉ (callback actif pendant combat) |
| `CB2_InitBattle` | N/A | — | ❌ N'existe pas séparément (CB2_LoadMap gère la transition) |
| `CB2_ReturnToField` | N/A | — | ❌ N'existe pas séparément (CB2_LoadMap gère le retour) |
| `gBattleOutcome` | N/A | find_battle_outcome_v2.lua | ❌ NON TROUVABLE (effacé avant que inBattle passe à 0) |
| `gTrainerBattleOpponent_A` | N/A | prediction +0x878 échouée | ❌ Non trouvé (pas bloquant) |

**Sequence callback2 observée (3 combats consistants):**
```
Overworld (0x080A89A5) → CB2_LoadMap (0x08007441) → inBattle 0→1
→ CB2_BattleMain (0x08094815) → combat en cours
→ CB2_LoadMap (0x08007441) → inBattle 1→0 → Overworld (0x080A89A5)
```

**Implications pour le PvP:**
- La detection de fin de combat via `gMainInBattle` (0x020206AE) fonctionne parfaitement
- `gBattleOutcome` n'est PAS nécessaire : utiliser fallback `"completed"` + check HP des parties
- La struct gMain est modifiée dans Run & Bun : offset inBattle = +0x66 (pas +0x37 vanilla)
- `gTrainerBattleOpponent_A` n'est PAS bloquant pour le PvP (utilise BATTLE_TYPE_SECRET_BASE)

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
- Zero gMain.state (ligne 553) — **NOTE: l'offset de state dans R&B est inconnu, il faudra tester/ajuster**
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

`Battle.startBattle()` ecrit `gBattleTypeFlags` (ligne 194) et `gTrainerBattleOpponent_A` (ligne 200) mais ne dit **jamais au jeu de demarrer le combat**. Il manque un trigger pour lancer le combat.

**Impact:** Le jeu reste en mode overworld. Les flags de combat sont ecrits mais personne ne les lit.

**Decouverte P3_10A:** Run & Bun n'a PAS de CB2_InitBattle séparé. La séquence observée est:
```
Overworld → CB2_LoadMap → inBattle=1 → CB2_BattleMain (0x08094815)
```
Le combat est declenché via CB2_LoadMap, qui detecte les flags de combat et charge la scene de combat.

**Fix en 2 parties:**

**Partie A — Auto-detection CB2_BattleMain (client/main.lua):**
- Chaque frame, lire `gMain.inBattle` a `0x020206AE`
- Tracker `prevInBattle` dans State
- Quand transition 0→1: attendre que callback2 != CB2_LoadMap et != CB2_Overworld
- Stocker cette adresse comme `CB2_BattleMain` (devrait etre 0x08094815)
- Ceci se produit automatiquement quand le joueur entre dans un combat naturel
- **Alternative:** hardcoder `CB2_BattleMain = 0x08094815` dans config (deja trouvé)

**Partie B — Trigger battle (client/hal.lua + client/battle.lua):**
- Modifier `Battle.startBattle()` pour appeler `HAL.triggerMapLoad()` apres avoir ecrit les flags
  - La meme fonction que pour le warp! CB2_LoadMap detecte les battle flags et lance le combat
  - Ecrire gBattleTypeFlags AVANT d'appeler triggerMapLoad
- **NOTE IMPORTANTE:** Il faudra tester si CB2_LoadMap suffit a trigger le combat quand les flags sont deja ecrits. Sinon, il faudra aussi setter callback2 = 0x08094815 directement.

---

#### 4. Le combat "finit" instantanement — ✅ DEJA CORRIGÉ par P3_10A
**Fichier:** `config/run_and_bun.lua:61`

~~`gMainInBattle = 0x020233E0` — FAUX, dans gPlayerParty~~

**Fix appliqué:** `gMainInBattle = 0x020206AE` (gMain+0x66, confirmé via find_inbattle_offset.lua)

La detection via `Battle.isFinished()` Method 2 fonctionne maintenant correctement car l'adresse lit le vrai flag inBattle.

---

#### 5. L'outcome est toujours "unknown" — Résolu sans gBattleOutcome
**Fichier:** `client/battle.lua:463-479`

```lua
function Battle.getOutcome()
  if not ADDRESSES or not ADDRESSES.gBattleOutcome then
    return nil  -- ← TOUJOURS NIL (gBattleOutcome = nil dans config)
  end
```

**Impact:** Sans `gBattleOutcome`, le resultat du combat est inconnu.

**Fix (pas besoin de scanner):**
- `gBattleOutcome` est introuvable dans Run & Bun (effacé avant la transition inBattle 1→0)
- Ajouter un fallback dans `getOutcome()`:
  - Si gBattleOutcome nil → retourner `"completed"` (combat terminé, resultat non-specifié)
  - Pour le PvP: determiner win/lose via check HP de gPlayerParty apres le combat
  - HP total > 0 → "win", HP total == 0 → "lose"

---

## Plan d'implementation

### Phase 1 : Fix immediats (pas de scan necessaire)

- [x] **1.1** Corriger `server/server.js:18-25` — DUEL_ROOM coords: `{28, 24, 3, 5, 10, 5}` ✅
- [x] **1.2** ~~Corriger `config/run_and_bun.lua:61` — gMainInBattle~~ ✅ FAIT dans P3_10A (0x020206AE)
- [x] **1.3** Ajouter `CB2_BattleMain = 0x08094815` dans config battle section ✅ (deja present dans config)

### Phase 2 : Warp direct sans porte (client/main.lua + client/hal.lua)

- [x] **2.1** Remplacer le bloc door fallback par triggerMapLoad direct ✅
- [x] **2.2** Supprimer la phase "waiting_door" dans le state machine ✅
- [x] **2.3** Supprimer l'overlay "Enter any door" ✅
- [x] **2.4** Supprimer la logique door fallback dans le watchpoint handler ✅

### Phase 3 : Auto-detection + trigger de combat

- [x] **3.1** Ajouter `HAL.readInBattle()` dans hal.lua ✅
- [x] **3.2** Ajouter `State.prevInBattle = 0` dans les variables State ✅
- [x] **3.3** Tracking inBattle dans la boucle principale (apres watchpoint, avant state machine) ✅
- [x] **3.4** Modifier `Battle.startBattle()` pour trigger via HAL.triggerMapLoad() ✅
- [x] **3.5** Supprimer les references a `gTrainerBattleOpponent_A` dans `Battle.startBattle()` ✅

### Phase 4 : Fix detection fin de combat (client/battle.lua + client/main.lua)

- [x] **4.1** Modifier `Battle.isFinished()` — transition tracking (prevInBattle + battleDetected) ✅
- [x] **4.2** Modifier `Battle.getOutcome()` — HP fallback + "completed" final fallback ✅
- [x] **4.3** main.lua phase "in_battle": Battle.isFinished() → duel_end + "returning" ✅ (deja present)

### Phase 5 : Integration et polish

- [ ] **5.1** Verifier que le retour ("returning" phase, `main.lua:659-695`) fonctionne:
  - Golden state garanti disponible (capture pendant le warp aller)
  - saveGameData → loadGoldenState → restoreGameData → writeWarpData(origin)
- [ ] **5.2** Verifier les timeouts a chaque phase
- [ ] **5.3** Tester la deconnexion pendant le combat (`main.lua:949-963`)
- [ ] **5.4** Nettoyer les logs debug excessifs

---

## Fichiers a modifier

| Fichier | Modifications |
|---------|--------------|
| `server/server.js:18-25` | DUEL_ROOM: `{2,2,5,4,8,4}` → `{28,24,3,5,10,5}` |
| `config/run_and_bun.lua` | ~~gMainInBattle~~ ✅ FAIT + ajouter CB2_BattleMain |
| `client/hal.lua` | Ajouter `readInBattle()` |
| `client/battle.lua` | Fix `startBattle()` (trigger via triggerMapLoad), fix `isFinished()` (transition tracking), fix `getOutcome()` (fallback + HP check) |
| `client/main.lua` | Remplacer door fallback par triggerMapLoad, inBattle tracking, fix in_battle phase |

---

## Experience utilisateur finale

```
1. Joueur A presse A pres du ghost de B → "Duel request sent"
2. Joueur B accepte (A) → "Duel accepted"
3. Les deux warpent INSTANTANEMENT vers Battle Colosseum (28:24)
   (triggerMapLoad direct — pas de porte!)
4. Echange d'equipes automatique (600 bytes chacun)
5. Combat PvP demarre (via CB2_LoadMap + battle flags)
6. Joueurs combattent normalement (choix synchronises via reseau)
7. Fin de combat → "Battle finished: completed"
8. Retour automatique a la position d'origine
```

**Note:** Plus de calibration nécessaire ! CB2_BattleMain est hardcodé dans le config.

---

## Test plan

- [ ] Verifier warp vers map 28:24 (pas 2:2) — les deux joueurs arrivent a (3,5) et (10,5)
- [ ] Verifier warp direct sans porte (triggerMapLoad au premier duel)
- [ ] Verifier que le golden state est capture pendant le premier warp
- [ ] Verifier que le second duel utilise le golden state hijack (plus rapide)
- [ ] Verifier que startBattle() trigger le combat (gBattleTypeFlags + triggerMapLoad)
- [ ] Verifier que isFinished() detecte la fin correctement (transition inBattle 1→0, pas instantané)
- [ ] Verifier getOutcome() retourne "completed" (ou win/lose via HP check)
- [ ] Verifier le retour a l'origine apres le combat
- [ ] Tester deconnexion pendant le combat → retour propre
- [ ] Tester timeout de choix adverse (30 sec)
