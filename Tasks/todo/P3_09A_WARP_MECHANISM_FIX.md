# Warp Mechanism Fix — CB2_LoadMap freeze

> **Statut:** Completed (2026-02-04)
> **Type:** Bug Fix — le warp duel freeze le jeu
> **Priorite:** P0 - CRITIQUE (resolu)
> **Prerequis:** P3_09_DUEL_WARP.md (UI/serveur OK, seul le warp RAM echoue)

---

## Probleme

Le duel warp (teleportation des joueurs vers une salle de combat) freeze le jeu a 100% des tentatives.
Ecrire `gMain.callback2 = CB2_LoadMap` depuis Lua cause un freeze permanent : CB2_LoadMap tourne
mais ne complete jamais son state machine. callback2 reste a `0x08007441` pendant 300 frames
sans jamais revenir a `CB2_Overworld` (`0x080A89A5`).

Le systeme de duel (UI, server coordination, request/accept) fonctionne parfaitement.
Seul le mecanisme de warp RAM echoue.

---

## Adresses confirmees

| Adresse | Valeur | Source | Statut |
|---------|--------|--------|--------|
| `0x0202064C` | gMain.callback2 | `scan_warp_addresses.lua` | Confirme |
| `0x08007441` | CB2_LoadMap (ROM ptr) | Scanner (transition porte) | Confirme |
| `0x080A89A5` | CB2_Overworld (ROM ptr) | Scanner (valeur normale) | Confirme |
| `0x02020648` | gMain base (callback2 - 4) | Deduit du scanner | Probable |
| `0x020318A8` | sWarpData | Scan EWRAM (match SaveBlock1) | Non fiable |
| `0x02024CBC` | SaveBlock1 base (pos.x) | Offsets confirmes | Confirme |

Autres adresses callback trouvees par le scanner (meme pattern changed+reverted, espacement 0x44) :
- `0x02020690` : snapshot `0x080ADB19` -> `0x08007441` -> reverted
- `0x020206D4` : snapshot `0x080ADB19` -> `0x08007441` -> reverted

---

## Tentatives echouees (3 essais) — HISTORIQUE

### Tentative 1 — callback2 seul
**Ecriture:** `callback2 = CB2_LoadMap`
**Resultat:** Freeze. callback2 reste a 0x08007441 indefiniment.

### Tentative 2 — callback1 + state a +0x08
**Ecritures:** `callback1 = NULL`, `state(+0x08) = 0`, `vblankCallback(+0x0C) = NULL`, `hblankCallback(+0x10) = NULL`, `callback2 = CB2_LoadMap`
**Resultat:** Freeze identique. L'offset +0x08 est `savedCallback`, pas `state`.

### Tentative 3 — state a +0x35 (pokeemerald layout)
**Ecritures:** `callback1 = NULL`, `savedCallback(+0x08) = NULL`, tous les interrupt callbacks = NULL, `state(+0x35) = 0`, `callback2 = CB2_LoadMap`
**Resultat:** Freeze identique.

### Conclusion — APPROCHE ABANDONNEE
Le probleme N'EST PAS le layout de gMain. Meme en ecrivant les champs gMain correctement,
CB2_LoadMap depend de **dizaines de variables globales dispersees** dans tout EWRAM :
`gPaletteFade`, `gGpuBgConfigs`, `gTasks[]`, `gObjectEvents[]`, contexte de scripts, etat DMA,
etat sonore, etc. Le jeu met 16 frames a preparer cet etat via `Task_WarpAndLoadMap`.

**Il est impossible de reproduire manuellement ce state cleanup depuis Lua.**
Scanner gMain ne resoudra pas le probleme. Il faut une approche differente.

---

## Analyse de la cause racine

### Pendant un warp naturel (porte), le jeu fait ~16 frames de preparation :
1. Gel de tous les ObjectEvents (NPCs, joueur)
2. Fade palette vers noir (interpolation progressive sur 16 frames)
3. Arret de la musique (`MapMusicStop()`)
4. Nettoyage du contexte de scripts (`ScriptContext_Init()`)
5. Nettoyage des field effects
6. Reset du systeme de taches (`gTasks`)
7. Flush des transferts DMA
8. Reset de `gPaletteFade`, `gPlttBufferFaded`, `gGpuBgConfigs`...
9. **Puis seulement** : callback1 = NULL, state = 0, callback2 = CB2_LoadMap

### Pourquoi ecrire callback2 ne marchera JAMAIS :
- CB2_LoadMap case 0 appelle `FieldClearVBlankHBlankCallbacks()`, `ScriptContext_Init()`, `MapMusicStop()`, etc.
- Ces fonctions lisent/ecrivent des dizaines de globals qui doivent etre dans un etat specifique
- Sans les 16 frames de preparation, ces globals sont "sales" → freeze ou comportement indefini
- C'est un probleme fondamental, pas un probleme de layout gMain
- Meme avec un scan parfait de gMain, les autres globals resteraient incorrects

### Solution : laisser le jeu faire sa propre preparation
Toutes les approches viables partagent un principe : **ne pas contourner le pipeline du jeu,
mais l'utiliser**. Soit en capturant un etat "propre" (save state), soit en interceptant
un warp naturel (watchpoint/breakpoint).

---

## APIs mGBA disponibles (dev build 0.11+)

Ces APIs existent dans mGBA dev build et n'ont PAS ete exploitees pour le warp :

### Breakpoints et Watchpoints
```
emu:setBreakpoint(callback, address, segment?) -> s64 (breakpoint ID)
emu:clearBreakpoint(bpId) -> bool
emu:setWatchpoint(callback, address, type, segment?) -> s64
emu:setRangeWatchpoint(callback, minAddr, maxAddr, type, segment?) -> s64
```
Watchpoint types : `C.WATCHPOINT_TYPE.WRITE` (1), `READ` (2), `RW` (3), `WRITE_CHANGE` (5)

### Registres CPU
```
emu:readRegister("r0".."r15", "cpsr") -> value
emu:writeRegister("r0".."r15", "cpsr", value)
```
r13 = SP, r14 = LR, r15 = PC. Ecrire r15 = jump.

### Save States (en memoire)
```
emu:saveStateBuffer(flags=31) -> string (binary blob)
emu:loadStateBuffer(buffer, flags=29) -> bool
```
Flags : SCREENSHOT(1), SAVEDATA(2), CHEATS(4), RTC(8), METADATA(16), ALL(31).
**IMPORTANT**: flags de load = 29 par defaut = tout SAUF SAVEDATA. Le SRAM (fichier de sauvegarde) n'est PAS ecrase.

### Simulation d'inputs
```
emu:setKeys(bitmask)        -- remplace toutes les touches
emu:addKey(keyId)           -- appuie une touche
emu:clearKey(keyId)         -- relache une touche
emu:getKeys() -> u32        -- lit l'etat actuel
```
Keys : `C.GBA_KEY.A`(0), `B`(1), `SELECT`(2), `START`(3), `RIGHT`(4), `LEFT`(5), `UP`(6), `DOWN`(7)
Pour bitmask : `1 << C.GBA_KEY.A` = 1, `1 << C.GBA_KEY.UP` = 64, etc.

### Callback keysRead
```lua
callbacks:add("keysRead", function()
    emu:setKeys(0)  -- supprime tous les inputs
end)
```
Se declenche AVANT que le jeu ne lise les touches. Ideal pour injection/suppression d'inputs.

---

## Plan d'implementation — approche unifiee

### Architecture : Watchpoint Central + Save State + Door Fallback

**Principe :** Un seul watchpoint WRITE_CHANGE sur `callback2Addr` sert de socle commun.
Il gere automatiquement 3 situations selon le contexte :

```
watchpoint WRITE_CHANGE sur 0x0202064C (callback2)
  │
  │ nouvelle valeur == CB2_LoadMap (0x08007441) ?
  │
  ├─ Pas de golden state capture ?
  │    → CAPTURE : sauvegarder le save state (setup one-time)
  │    → laisser le warp naturel continuer normalement
  │
  ├─ Duel pending + golden state dispo ?
  │    → SAFETY NET : re-ecrire sWarpData avec destination duel
  │    → (le save state hijack a deja fait le gros du travail)
  │
  └─ Duel pending + PAS de golden state ?
       → DOOR FALLBACK : le joueur traverse une porte,
         on remplace la destination par la salle de duel
         + on capture le golden state pour les prochains warps
```

Les deux modes (save state et door fallback) coexistent. Le watchpoint est toujours actif.
Le save state est le mode principal (instantane), le door fallback est le mode de secours
automatique (avant que le joueur ait traverse sa premiere porte).

---

### Phase 1 : Watchpoint + Golden State Capture

Se fait automatiquement au demarrage. Le watchpoint reste actif toute la session.

- [x] **1.1** Au demarrage (`main.lua:init`), poser un watchpoint WRITE_CHANGE sur `callback2Addr` (0x0202064C)
- [x] **1.2** Le callback du watchpoint verifie la nouvelle valeur :
  - Si `!= CB2_LoadMap` (0x08007441) → ignorer
  - Si `== CB2_LoadMap` → traiter selon le contexte (voir 1.3, 1.4, 1.5)
- [x] **1.3** **Contexte "pas de golden state"** (premier warp naturel) :
  - `State.goldenWarpState = emu:saveStateBuffer()`
  - Log "Golden warp state captured"
  - Si un duel est pending → aussi executer le door fallback (1.5)
  - Sinon → laisser le warp naturel continuer
- [x] **1.4** **Contexte "duel pending + golden state deja capture"** (safety net) :
  - Re-ecrire sWarpData + SaveBlock1->location avec la destination duel
  - Securite : garantit que meme si le save state hijack a un edge case, la destination est correcte
- [x] **1.5** **Contexte "duel pending + PAS de golden state"** (door fallback) :
  - Ecrire destination duel dans sWarpData + SaveBlock1->location
  - Capturer le golden state au passage (pour les prochains warps)
  - Le jeu charge notre destination au lieu de celle de la porte
  - UX : le joueur voit le warp normal de la porte mais arrive dans la salle de duel

**Timing :** Le watchpoint fire au frame exact ou callback2 passe a CB2_LoadMap.
A ce moment, les 16 frames de preparation sont terminees, tous les globals sont propres,
et CB2_LoadMap case 0 n'a pas encore execute.

---

### Phase 2 : Duel Warp (mode principal — save state hijack)

Quand le serveur envoie `duel_warp` ET que le golden state est disponible :

- [x] **2.1** Sauvegarder les donnees de jeu actuelles depuis WRAM :
  - SaveBlock1 : lire ~16KB depuis `0x02024CBC` (position, map, inventaire, equipe, flags, progression)
  - Stocker dans un tableau Lua : `savedGameData[i] = wram:read32(offset + i*4)` pour i = 0..4095
- [x] **2.2** Charger le golden state : `emu:loadStateBuffer(goldenWarpState)`
  - L'emulateur est maintenant dans l'etat propre mid-warp
  - callback2 = CB2_LoadMap (case 0 pas encore execute)
  - SRAM (fichier de sauvegarde) n'est PAS touche (flags par defaut = 29)
  - Le watchpoint reste actif (debugger state != emulator state)
- [x] **2.3** Restaurer les donnees de jeu dans WRAM :
  - Ecrire les 4096 valeurs SaveBlock1 : `wram:write32(offset + i*4, savedGameData[i])`
- [x] **2.4** Ecrire la destination du duel par-dessus :
  - `SaveBlock1->location` : mapGroup, mapId, warpId=0xFF, x, y (a 0x02024CC0)
  - `SaveBlock1->pos` : x, y (a 0x02024CBC)
  - `sWarpData` : memes valeurs (si trouve via `HAL.findSWarpData()`)
- [x] **2.5** Activer le state machine existant :
  - `State.inputsLocked = true`
  - `State.warpPhase = "loading"` (pas de phase "blank" — golden state a deja l'ecran noir)
  - `State.unlockFrame = frameCounter + 300` (safety timeout)
- [x] **2.6** Le frame suivant : CB2_LoadMap case 0 s'execute → le watchpoint fire (safety net, re-ecrit destination)
- [x] **2.7** Detection de fin : `HAL.isWarpComplete()` (callback2 revient a CB2_Overworld)

**UX joueur :** Ecran courant → bref noir → salle de duel apparait. Identique a un warp normal.

---

### Phase 3 : Duel Warp (mode fallback — door interception)

Quand le serveur envoie `duel_warp` MAIS que le golden state n'est PAS encore capture :

- [x] **3.1** Stocker la destination duel dans `State.duelPending = {mapGroup, mapId, x, y}`
- [x] **3.2** Afficher un overlay : "Enter any door to start the duel"
- [x] **3.3** Le watchpoint est deja actif — quand le joueur traverse une porte :
  - Le watchpoint fire (callback2 → CB2_LoadMap)
  - Contexte 1.5 s'applique : ecrire destination duel + capturer golden state
  - Le jeu charge la salle de duel au lieu de la destination de la porte
- [x] **3.4** Activer le meme state machine (inputsLocked, warpPhase = "loading")
- [x] **3.5** Les prochains duels utiliseront le mode principal (golden state maintenant disponible)

**UX joueur :** Message "Enter any door" → joueur traverse une porte → arrive dans la salle de duel.
Pas ideal mais fonctionnel. N'arrive qu'une seule fois (premier duel avant toute porte traversee).

---

### Phase 4 : Gestion des cas limites

- [ ] **4.1** (deferred — test without SaveBlock2 first) Preservation SaveBlock2 (si necessaire apres tests) :
  - Trouver l'adresse de SaveBlock2 dans Run & Bun (scan)
  - Sauvegarder/restaurer en plus de SaveBlock1
- [ ] **4.2** (deferred — test performance first) Performance : 4096 read32 + 4096 write32 = ~8192 operations
  - Si trop lent pour un seul frame, repartir sur 2-3 frames
- [ ] **4.3** (deferred — requires runtime testing) Verifier que l'equipe Pokemon, l'inventaire, les flags de progression sont intacts apres warp
- [x] **4.4** Deconnexion pendant un duel pending (door fallback) : reset `State.duelPending`, retirer overlay

---

### Fallback avance (si les deux modes echouent)

Si ni le save state ni le door fallback ne fonctionnent, deux approches avancees sont possibles.
Elles ne font PAS partie du plan principal et ne doivent etre considerees qu'en dernier recours.

#### Breakpoint sur le code ROM de warp initiation
- Trouver l'adresse ROM de `DoWarp()` via breakpoint + lecture de LR pendant un warp naturel
- Quand duel trigger : `emu:writeRegister("r15", doWarpAddr)` dans un breakpoint sur CB2_Overworld
- Le jeu execute son propre DoWarp → preparation naturelle → warp propre
- **Risque :** manipulation de PC mid-frame fragile, reverse engineering necessaire

#### Appel de fonction ROM via registres
```lua
emu:writeRegister("r0", arg0)
emu:writeRegister("r14", RETURN_SENTINEL)
emu:writeRegister("r15", doWarpAddr)
local bp = emu:setBreakpoint(function() ... end, RETURN_SENTINEL)
```
- **Risque :** Interactions ARM/THUMB, timeout, pipeline d'instructions

---

## Fichiers concernes

### A modifier

| Fichier | Lignes | Modification |
|---------|--------|-------------|
| `client/hal.lua` | 388-550 | Ajouter `HAL.saveGameData()`, `HAL.restoreGameData(data)`, `HAL.setupWarpWatchpoint()`. Simplifier `triggerMapLoad()` (gardee comme legacy, le save state la remplace). |
| `client/main.lua` | 445-499 | Refactorer le warp state machine : supprimer phase "blank", ajouter logique save state + door fallback. |
| `client/main.lua` | 569-595 | Handler `duel_warp` : brancher sur save state (golden dispo) ou door fallback (pas de golden). |
| `client/main.lua` | ~420 | Ajouter appel a `HAL.setupWarpWatchpoint()` dans init. |

### Fichiers NON modifies

`client/duel.lua`, `client/render.lua`, `client/sprite.lua`, `client/occlusion.lua`,
`client/interpolate.lua`, `client/network.lua`, `server/server.js`, `config/run_and_bun.lua`

### Scripts de diagnostic (PLUS necessaires pour le warp)

`scripts/scan_gmain_warp_state.lua` — **ANNULE**. Le scan gMain ne resoudra pas le probleme.
Les scripts existants (`scan_warp_addresses.lua`) restent utiles comme reference.

---

## Flow detaille

### Initialisation (au demarrage du script)
```
main.lua:init()
  → HAL.init()
  → HAL.setupWarpWatchpoint()
      → watchpoint WRITE_CHANGE sur 0x0202064C (callback2Addr)
      → callback = onCallback2Changed (reste actif toute la session)
```

### Callback watchpoint (logique centrale)
```
onCallback2Changed():
  newVal = lire callback2
  si newVal != CB2_LoadMap → return (on ne gere que les transitions vers CB2_LoadMap)

  si goldenWarpState == nil :
    goldenWarpState = emu:saveStateBuffer()    ← CAPTURE
    log("Golden warp state captured")

  si duelPending != nil :
    ecrire duelPending.destination dans sWarpData + SaveBlock1->location
    log("Duel destination written (watchpoint safety)")
```

### Premier warp naturel (joueur traverse une porte)
```
Frame N    : joueur marche dans une porte
Frame N+1..N+16 : Task_WarpAndLoadMap fait le cleanup (fade, freeze, etc.)
Frame N+17 : callback2 = CB2_LoadMap → watchpoint fire
           → golden state capture
           → si duel pending : destination ecrite (door fallback)
           → sinon : warp naturel continue normalement
Frame N+18..N+K : CB2_LoadMap charge la map
Frame N+K+1 : callback2 = CB2_Overworld (warp termine)
```

### Duel warp — mode principal (golden state disponible)
```
Frame N   : serveur envoie duel_warp {mapGroup:28, mapId:24, x:3, y:5}
          → duelPending = {mapGroup, mapId, x, y}
          → goldenState existe ? OUI →
          → lire 16KB de SaveBlock1 depuis WRAM (sauvegarde donnees jeu)
          → emu:loadStateBuffer(goldenState) (etat propre mid-warp)
          → ecrire 16KB de SaveBlock1 dans WRAM (restaure donnees jeu)
          → ecrire destination duel dans SaveBlock1->location + sWarpData
          → State.warpPhase = "loading"
Frame N+1 : CB2_LoadMap case 0 s'execute (etat propre garanti)
          → watchpoint fire (safety net) → re-ecrit destination duel
Frame N+2..N+K : CB2_LoadMap charge la map de duel
Frame N+K+1 : callback2 = CB2_Overworld → isWarpComplete() → unlock + duelPending = nil
```

### Duel warp — mode fallback (pas de golden state)
```
Frame N   : serveur envoie duel_warp {mapGroup:28, mapId:24, x:3, y:5}
          → duelPending = {mapGroup, mapId, x, y}
          → goldenState existe ? NON →
          → afficher overlay "Enter any door to start the duel"
          → State.warpPhase = "waiting_door"
Frame N+?? : joueur traverse une porte → warp naturel demarre
Frame N+??+16 : callback2 = CB2_LoadMap → watchpoint fire
              → golden state capture (pour les prochains warps)
              → destination duel ecrite dans sWarpData + SaveBlock1
              → retirer overlay
              → State.warpPhase = "loading"
Frame +K  : CB2_LoadMap charge la salle de duel (au lieu de la porte)
Frame +K+1 : callback2 = CB2_Overworld → unlock + duelPending = nil
```

---

## Inconnues et risques

1. **SaveBlock1 taille exacte** : 0x3D88 en vanilla emerald. Run & Bun peut differer.
   Mitigation : copier 16KB (0x4000) conservativement depuis 0x02024CBC.

2. **SaveBlock2 necessaire ?** : CB2_LoadMap case 3 lit SaveBlock2 (genre joueur, trainer type).
   Mitigation : tester sans d'abord. Si le joueur apparait mal, trouver et preserver SaveBlock2.

3. **Performance des 8192 operations memoire** : 4096 read32 + 4096 write32 par pcall.
   Mitigation : tester. Si trop lent, repartir sur 2-3 frames ou reduire la zone copiee.

4. **loadStateBuffer mid-callback** : Charger un save state pendant un callback Lua `frame`.
   L'emulateur devrait gerer car les save states sont conçus pour etre charges a tout moment.
   Mitigation : tester. Si probleme, utiliser un flag et charger au frame suivant.

5. **Golden state perime** : Le golden state est capture une fois et reutilise. Les globals
   "systeme" (gMain, interrupts, GPU) ne changent pas entre warps, donc c'est safe.
   Les globals "jeu" (SaveBlock) sont restaures manuellement a chaque warp.

---

## Tests a effectuer

### Tests watchpoint + golden state
1. Warp naturel (porte) — verifier que le golden state est capture sans perturber le warp
2. Verifier dans les logs que le watchpoint fire et capture le state
3. Traverser plusieurs portes — verifier que le golden state n'est capture qu'une fois

### Tests mode principal (save state hijack)
4. Duel warp apres avoir traverse une porte — les 2 joueurs arrivent aux bonnes coords
5. Verifier que l'equipe Pokemon est intacte apres le warp
6. Verifier que l'inventaire est intact apres le warp
7. Verifier que les flags de progression sont intacts (trainers battus, events, etc.)
8. Warp depuis differentes maps (interieur, exterieur, grotte)
9. Warp pendant que le joueur marche / est en velo

### Tests mode fallback (door interception)
10. Duel warp AVANT avoir traverse une porte — overlay "Enter any door" s'affiche
11. Joueur traverse une porte → arrive dans la salle de duel (pas dans la porte)
12. Apres le fallback, golden state est maintenant capture → prochain duel utilise le mode principal
13. Deconnexion pendant "waiting_door" — overlay disparait, duelPending reset

### Tests generaux
14. Double warp rapide (duel → retour → duel)
15. Warp avec 3+ joueurs dans la room (seuls les 2 duellistes doivent warp)
16. Deconnexion pendant le warp loading (cleanup propre)

---

## References techniques

### Flow warp naturel (pokeemerald)

```
1. Player touche warp tile
2. DoWarp() → Task_WarpAndLoadMap:
   - Phase 0-2: Freeze objects, fade to black (16 frames)
   - Phase 3: WarpIntoMap() → ApplyCurrentWarp() copie sWarpData → SaveBlock1
   - Phase 4: callback1 = NULL, state = 0, callback2 = CB2_LoadMap
3. CB2_LoadMap state machine:
   - case 0: FieldClearVBlankHBlankCallbacks, ScriptContext_Init, MapMusicStop
   - case 1: LoadSaveblockMapHeader (lit SaveBlock1->location)
   - case 2: Setup sprites, tiles
   - case 3: Restore callbacks, fade in (lit SaveBlock2)
   - case N: callback2 = CB2_Overworld (retour normal)
```

### SaveBlock1 layout (vanilla emerald, reference)

```
+0x00  pos.x           (s16)  ← 0x02024CBC dans Run & Bun
+0x02  pos.y           (s16)  ← 0x02024CBE
+0x04  location.mapGroup (u8) ← 0x02024CC0
+0x05  location.mapNum   (u8) ← 0x02024CC1
+0x06  location.warpId   (s8) ← 0x02024CC2
+0x07  padding           (u8)
+0x08  location.x       (s16) ← 0x02024CC4
+0x0A  location.y       (s16) ← 0x02024CC6
...
Total: ~0x3D88 bytes (vanilla). Inconnu pour Run & Bun.
```

### mGBA save state flags

```
C.SAVESTATE.SCREENSHOT = 1
C.SAVESTATE.SAVEDATA   = 2
C.SAVESTATE.CHEATS     = 4
C.SAVESTATE.RTC        = 8
C.SAVESTATE.METADATA   = 16
C.SAVESTATE.ALL        = 31

saveStateBuffer(flags=31)    → sauve tout
loadStateBuffer(buf, flags=29) → charge tout SAUF savedata (SRAM non ecrase)
```
