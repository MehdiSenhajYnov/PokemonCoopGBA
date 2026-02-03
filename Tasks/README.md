# Tasks - Pokémon Unified Co-op Framework

Index de toutes les tâches d'implémentation organisées par phase.

## 📁 Organisation

```
Tasks/
├── todo/          Tâches à faire (toutes les tasks actuelles)
├── done/          Tâches terminées (vide pour l'instant)
├── updates/       Mises à jour et améliorations futures
└── README.md      Ce fichier
```

**Format des noms:** `P{phase}_{numéro}_{nom}.md`
- Exemple: `P1_01_TCP_NETWORK.md` = Phase 1, tâche #01, TCP Network
- Facile de voir l'ordre: 00 → 01 → 02 → ... → 10
- Facile d'insérer: Utiliser décimales (P1_01.5) ou renommer

---

## 📋 Vue d'ensemble

**Projet:** Framework multijoueur seamless pour ROM GBA Pokémon
**Cible prioritaire:** Pokémon Run & Bun (ROM hack basé Émeraude)
**Phases:** 6 (Memory Discovery → Foundation → Ghosting → Duel Warp → Multi-ROM → Documentation)

---

## Phase 0 - Memory Offset Discovery 🔍

### done/features/P0_00_MEMORY_OFFSET_DISCOVERY.md
**Status:** 🟢 Terminé (2026-02-02)
**Description:** Offsets mémoire Run & Bun identifiés et documentés

**Résultat:**
- Offsets vanilla Émeraude: NE fonctionnent PAS pour Run & Bun
- Scan WRAM via mGBA Lua: 5 offsets trouvés
- Mode: **STATIQUE** (pas de pointeurs dynamiques)
- Config `config/run_and_bun.lua` rempli
- Documentation mise à jour dans `docs/RUN_AND_BUN.md`

**Offsets découverts:**
- PlayerX: `0x02024CBC` | PlayerY: `0x02024CBE`
- MapGroup: `0x02024CC0` | MapID: `0x02024CC1`
- Facing: `0x02036934`

---

## Phase 1 - Foundation ✅

### done/features/P1_01_TCP_NETWORK.md
**Status:** 🟢 Completed (2026-02-02)
**Tâches groupées:** #1 + #2
**Description:** Créer module `network.lua` pour communication TCP et l'intégrer dans `main.lua`

**Contenu:**
- Partie 1: Créer `client/network.lua` (API connect/send/receive) ✅
- Partie 2: Intégrer dans `main.lua` (connexion, registration, envoi/réception positions) ✅
- Protocole JSON ligne-délimité ✅
- Mode non-bloquant avec buffering ✅

**Fichiers créés:**
- ✅ `client/network.lua` (TCP module + custom JSON encoder/decoder)

---

### todo/P1_02_TCP_TESTING.md
**Status:** 🔴 À faire
**Tâche:** #3
**Description:** Tests bout en bout validation Phase 1 complète

**Contenu:**
- 10 suites de tests (serveur, connexion, synchronisation, déconnexion, performance)
- Tests localhost et LAN
- Documentation résultats dans `docs/TESTING.md`

**Critères succès:**
- ✅ 2 clients connectés simultanément
- ✅ Positions synchronisées < 2 sec
- ✅ Pas de freeze/crash
- ✅ Performance acceptable

---

## Phase 2 - Ghosting System 👻

### done/P2_03_GHOSTING_RENDER.md
**Status:** 🟢 Terminé (2026-02-03)
**Tâches groupées:** #4 + #5 + #6
**Description:** Système complet d'affichage visuel des autres joueurs

**Résultat:**
- Camera offsets trouvés: IWRAM 0x03005DFC (X), 0x03005DF8 (Y)
- `client/render.lua` créé (Painter API, conversion coordonnées monde→écran)
- HAL étendu avec support IWRAM + readCameraX/Y + conversion s16
- Intégré dans main.lua (drawOverlay avec ghost rendering)

**Fichiers créés/modifiés:**
- ✅ Créé: `client/render.lua`
- ✅ Modifié: `client/hal.lua` (IWRAM support, readCameraX/Y, toSigned16)
- ✅ Modifié: `client/main.lua` (require render, drawOverlay avec ghosts)

---

### done/P2_04_INTERPOLATION.md
**Status:** 🟢 Terminé (2026-02-03)
**Tâches groupées:** #7 + #8
**Description:** Mouvement fluide des ghosts via interpolation linéaire

**Résultat:**
- `client/interpolate.lua` créé (lerp, teleport detection, per-frame step)
- Intégré dans `main.lua` (Interpolate.step() chaque frame, positions interpolées pour rendu)
- Gestion déconnexion (Interpolate.remove sur player_disconnected)
- Partie 3 (flèches/trails render.lua) skippée — optionnelle, uses gui.* API qui n'existe pas dans mGBA

**Fichiers créés/modifiés:**
- ✅ Créé: `client/interpolate.lua`
- ✅ Modifié: `client/main.lua` (require, Interpolate.step, interpolated rendering, disconnect handling)

---

### done/P2_04A_BUFFERED_INTERPOLATION.md
**Status:** 🟢 Terminé (2026-02-03)
**Description:** Remplacement de l'interpolation naïve par un buffer temporel ("render behind")

**Contenu:**
- Ring buffer de positions horodatées par joueur
- Interpolation temporelle entre deux snapshots connus (toujours fluide)
- Timestamps dans les messages position (client + serveur)
- Délai de rendu configurable (~150ms)
- Augmentation du taux d'envoi (UPDATE_RATE 60 → 10)

**Fichiers:**
- 📝 Réécrire: `client/interpolate.lua` (buffer temporel)
- 📝 Modifier: `client/main.lua` (timestamps, dt, config)
- 📝 Modifier: `server/server.js` (relayer timestamp)

---

### done/P2_04B_ADAPTIVE_SEND_RATE.md
**Status:** 🟢 Terminé (2026-02-03)
**Description:** Envoi adaptatif : fréquent en mouvement, zéro en idle

**Résultat:**
- Replaced fixed `UPDATE_RATE` with adaptive `SEND_RATE_MOVING` / `SEND_RATE_IDLE`
- Movement detection via `positionChanged()` with `IDLE_THRESHOLD` (30 frames)
- ~10 sends/sec while moving, 0 sends/sec when idle
- Immediate send on map change (warp/teleport)
- Final position update sent when player stops

**Fichiers modifiés:**
- ✅ `client/main.lua` (adaptive send logic, movement state tracking, config constants)

---

### done/P2_04C_DEAD_RECKONING.md
**Status:** 🟢 Terminé (2026-02-03)
**Description:** Prédiction de mouvement quand le buffer est vide + correction douce

**Résultat:**
- Velocity tracking from buffer snapshots
- Extrapolation when buffer exhausted (max 500ms, max 5 tiles)
- Smooth correction on position error after extrapolation
- State tracking API (`Interpolate.getState()`)

**Fichiers modifiés:**
- ✅ Modifié: `client/interpolate.lua` (vélocité, extrapolation, correction, state)

---

### done/P2_04D_SMOOTH_RENDERING.md
**Status:** 🟢 Terminé (2026-02-03)
**Description:** Rendu sub-tile pixel par pixel + indicateur de direction + couleurs debug par état

**Résultat:**
- `ghostToScreen()` avec `math.floor` pour positionnement pixel-perfect
- Marqueur de direction 4x4 blanc sur chaque ghost (facing 1-4)
- Couleurs d'état debug: vert (interpolating/idle), jaune (extrapolating), orange (correcting)
- `drawAllGhosts()` supporte format `{pos=..., state=...}` avec fallback ancien format
- `main.lua` passe l'état d'interpolation au système de rendu

**Fichiers modifiés:**
- ✅ `client/render.lua` (math.floor, direction marker, state colors, drawAllGhosts format)
- ✅ `client/main.lua` (interpolatedPlayers structure avec state)

---

### done/P2_05_NETWORK_POLISH.md
**Status:** 🟢 Terminé (2026-02-03)
**Tâche:** #9
**Description:** Gestion robuste déconnexion/reconnexion

**Résultat:**
- Auto-reconnexion avec backoff exponentiel (max 10 attempts, cap 30s)
- Détection déconnexion (socket error callback, receive error, send pcall)
- Nettoyage ghosts via server broadcast `player_disconnected` (pas de timeout client)
- Indicateur UI statut connexion (ONLINE/RECONNECTING/OFFLINE)
- Server broadcasts `player_disconnected` on disconnect

**Fichiers modifiés:**
- ✅ `client/network.lua` (disconnection detection, reconnect with backoff)
- ✅ `client/main.lua` (reconnect logic, enhanced UI)
- ✅ `server/server.js` (disconnect broadcast, double-disconnect guard)

---

### done/P2_06_GHOST_SPRITE_RENDERING.md
**Status:** 🟢 Terminé (2026-02-03)
**Tâche:** #10
**Description:** Remplacer les carres verts par les vrais sprites GBA extraits dynamiquement de la VRAM/OAM/Palette

**Résultat:**
- `client/sprite.lua` créé (extraction VRAM/OAM/Palette, reconstruction Image, cache, serialisation réseau)
- `client/hal.lua` étendu (readOAMEntry, readSpriteTiles, readSpritePalette)
- `client/render.lua` modifié (drawImage avec fallback rectangle, overlay.image passé en paramètre)
- `client/main.lua` modifié (capture sprite local, envoi/réception sprite_update)
- `server/server.js` modifié (relayer sprite_update avec cache)

**Fichiers créés/modifiés:**
- ✅ Créé: `client/sprite.lua`
- ✅ Modifié: `client/hal.lua`, `client/render.lua`, `client/main.lua`, `server/server.js`

---

### done/P2_06A_SPRITE_DETECTION_RELIABILITY.md
**Status:** 🟢 Terminé (2026-02-03)
**Priorité:** ⭐ Haute
**Description:** La detection OAM du sprite joueur echoue parfois (prend un NPC ou reflet d'eau)

**Résultat:**
- `findPlayerOAM()` rewritten with two-pass approach: strict tileNum filter (pass 1) + fallback scoring (pass 2)
- Hysteresis locking system: `lockedTileNum` locks after 30 frames, unlocks after 10 frames of absence
- OAM priority discrimination: player (pri=2) beats water reflection (pri=3) — reflection has same tileNum=0 and vFlip=false
- `parseOAMEntry()` now extracts `priority` field (attr2 bits 10-11)
- `Sprite.init()` resets all locking state on map change

**Fichiers modifiés:** `client/sprite.lua`

---

### done/P2_06B_GHOST_DEPTH_OCCLUSION.md
**Status:** 🟢 Terminé (2026-02-03)
**Priorité:** ⭐ Haute
**Description:** Le ghost s'affiche au-dessus des batiments au lieu d'etre cache derriere

**Résultat:**
- Y-sorting: `drawAllGhosts()` trie par Y croissant (ghosts derriere dessines en premier)
- BG layer occlusion: `occlusion.lua` lit la tilemap BG1, decode les tiles 4bpp, redessine les pixels de couverture par-dessus les ghosts via Painter API
- HAL etendu: 6 nouvelles fonctions BG/IO (readIOReg16, readBGControl, readBGScroll, readBGTilemapEntry, readBGTileData, readBGPalette)
- Ghosts opaques (`GHOST_ALPHA = 0xFF`) — l'occlusion gere la profondeur, semi-transparence plus necessaire

**Fichiers créés/modifiés:** `client/occlusion.lua` (nouveau), `client/hal.lua`, `client/render.lua`, `client/sprite.lua`, `client/main.lua`

---

### done/P2_04E_WAYPOINT_QUEUE_INTERPOLATION.md
**Status:** 🟢 Terminé (2026-02-03)
**Priorite:** ⭐ Haute
**Description:** Remplacer l'interpolation "animate toward target" par une file de waypoints avec catch-up adaptatif universel (`BASE_DURATION / queueLength`)

**Résultat:**
- Queue FIFO: chaque position recue est ajoutee a la queue, consommee dans l'ordre
- Formule universelle: `segmentDuration = BASE_DURATION / max(1, queueLength)` — scale de 1x a 1000x+
- Consommation multi-waypoints par frame (boucle while dans step())
- Auto-regulation: le ghost suit le parcours exact a toute vitesse
- Deduplication et teleport detection contre dernier element de la queue
- API publique inchangee (zero modification dans main.lua/render.lua)

**Fichiers modifiés:**
- ✅ `client/interpolate.lua` (refactoring complet)

---

### todo/P2_07_OPTIMIZATION.md
**Status:** 🔴 À faire
**Tâche:** #11
**Description:** Profiling et optimisation performance

**Cibles:**
- Latency < 100ms (localhost)
- CPU overhead < 5%
- Support 10+ clients simultanés
- 60fps stable

**Contenu:**
- Profiling latency réseau
- Optimisations rendu (culling, caching)
- Optimisations réseau (compression, rate limiting)
- Tests stress (10-20 clients)

**Fichiers:**
- ✨ Créer: `docs/performance.md`

---

### todo/P2_08_FINAL_TESTING.md
**Status:** 🔴 À faire
**Tâche:** #15
**Description:** Suite complète tests validation Phase 2

**Contenu:**
- Test Suite 1: Localhost (2 clients)
- Test Suite 2: LAN (2 machines)
- Test Suite 3: Stress (10+ clients)
- Test Suite 4: Edge cases
- Test Suite 5: Compatibilité ROMs

**Validation:**
- Tous critères succès Phase 2 atteints
- Documentation résultats complète
- Aucun bug bloquant

---

## Phase 3 - Duel Warp ⚔️

### todo/P3_09_DUEL_WARP.md
**Status:** 🔴 À faire
**Tâches groupées:** #11 + #12
**Description:** Téléportation synchronisée vers salle de combat

**Contenu:**
- Partie 1: Module `duel.lua` (détection proximité, trigger bouton A, UI prompt)
- Partie 2: Téléportation (HAL.writePlayerPosition, coordination serveur)
- Partie 3: Coordonnées Duel Room (recherche Battle Frontier)

**Workflow:**
1. Joueur A près de ghost B
2. A appuie sur bouton A
3. Serveur broadcast duel_request
4. B voit prompt "Duel [PlayerA]?"
5. B accepte (bouton A)
6. Serveur envoie duel_warp aux deux
7. Téléportation simultanée
8. Lock inputs 3 secondes
9. Unlock devant NPC Colisée

**Fichiers:**
- ✨ Créer: `client/duel.lua`
- 📝 Modifier: `server/server.js`, `client/main.lua`, `config/emerald_us.lua` (duelRoom coords)

---

## Phase 4 - Multi-ROM 🌐

### todo/P4_10_MULTI_ROM.md
**Status:** 🔴 À faire
**Tâche:** #13
**Description:** Support Radical Red et Unbound

**Contenu:**
- Méthodologie recherche offsets (même que Phase 0)
- Créer profils ROM:
  - `config/radical_red.lua` (base FireRed)
  - `config/unbound.lua` (base FireRed)
- Améliorer auto-détection ROM

**Note:** Run & Bun maintenant géré dans Phase 0

**Fichiers:**
- ✨ Créer: `config/radical_red.lua`, `config/unbound.lua`
- 📝 Modifier: `client/main.lua` (detectROM amélioration)

---

## Phase 5 - Documentation 📚

### todo/P5_11_DOCUMENTATION.md
**Status:** 🔴 À faire
**Tâche:** #14
**Description:** Documentation complète utilisateur final

**Contenu:**
- Mettre à jour README.md (screenshots, GIFs, features)
- Mettre à jour QUICKSTART.md (Phases 2-4)
- Créer CONFIGURATION.md (paramètres client/serveur)
- Créer TROUBLESHOOTING.md (FAQ, solutions problèmes)
- Créer API.md (modules Lua, protocole réseau)
- Capturer screenshots/GIFs (ghosting, duel warp)
- Mettre à jour CHANGELOG.md (versions 0.2-1.0)

**Fichiers:**
- ✨ Créer: `docs/CONFIGURATION.md`, `docs/TROUBLESHOOTING.md`, `docs/API.md`, `docs/media/*`, `docs/VIDEO.md`
- 📝 Modifier: `README.md`, `docs/QUICKSTART.md`, `docs/INDEX.md`, `docs/CHANGELOG.md`

---

## 📊 Progression Globale

```
Phase 0 - Memory Discovery    [██████████] 100% ✅ COMPLETE
Phase 1 - Foundation          [██████████] 100% ✅ COMPLETE
Phase 2 - Ghosting            [██████████] 100% ✅ COMPLETE (render + interp + camera + smooth + network + sprites + BG occlusion)
Phase 3 - Duel Warp           [░░░░░░░░░░]  0%
Phase 4 - Multi-ROM           [░░░░░░░░░░]  0%
Phase 5 - Documentation       [░░░░░░░░░░]  0%

Global                        [███░░░░░░░] 33%
```

---

## 🎯 Ordre d'exécution recommandé

Toutes les tâches sont dans `todo/` jusqu'à leur complétion:

0. ~~**P0_00_MEMORY_OFFSET_DISCOVERY.md**~~ ✅ TERMINÉ
1. ~~**P1_01_TCP_NETWORK.md**~~ ✅ TERMINÉ
2. **todo/P1_02_TCP_TESTING.md** (tests approfondis optionnels)
3. ~~**P2_03_GHOSTING_RENDER.md**~~ ✅ TERMINÉ
4. ~~**P2_04_INTERPOLATION.md**~~ ✅ TERMINÉ (interpolation naïve)
5. ~~**P2_04A_BUFFERED_INTERPOLATION.md**~~ ✅ SUPERSEDED (replaced by animate-toward-target in 0.2.7)
6. ~~**P2_04B_ADAPTIVE_SEND_RATE.md**~~ ✅ TERMINÉ (SEND_RATE_MOVING tuned to 1 in 0.2.7)
7. ~~**P2_04C_DEAD_RECKONING.md**~~ ✅ REMOVED (caused overshoot, removed in 0.2.7)
8. ~~**P2_04D_SMOOTH_RENDERING.md**~~ ✅ TERMINÉ (sub-tile rendering + camera correction + direction marker)
9. ~~**P2_05_NETWORK_POLISH.md**~~ ✅ TERMINÉ
6. ~~**P2_06_GHOST_SPRITE_RENDERING.md**~~ ✅ TERMINÉ (VRAM sprite extraction + network sync)
6a. ~~**P2_06A_SPRITE_DETECTION_RELIABILITY.md**~~ ✅ TERMINÉ (strict tileNum=0 filter + hysteresis locking)
6b. ~~**P2_06B_GHOST_DEPTH_OCCLUSION.md**~~ ✅ TERMINÉ (Y-sorting + BG layer occlusion + ghosts opaques)
6c. ~~**P2_04E_WAYPOINT_QUEUE_INTERPOLATION.md**~~ ✅ TERMINÉ (waypoint queue + catch-up adaptatif)
7. **todo/P2_07_OPTIMIZATION.md**
8. **todo/P2_08_FINAL_TESTING.md**
9. **todo/P3_09_DUEL_WARP.md**
10. **todo/P4_10_MULTI_ROM.md** (Radical Red, Unbound)
11. **todo/P5_11_DOCUMENTATION.md**

**Workflow:**
- Nouvelles tâches → `todo/`
- Tâches terminées → déplacer vers `done/`
- Format: `P{phase}_{numéro}_{nom}.md`

---

## 🔑 Légende

- 🔴 À faire
- 🟡 En cours
- 🟢 Terminé
- ✨ Fichier à créer
- 📝 Fichier à modifier
- ⭐ Priorité haute

---

## 📝 Notes

**Architecture modulaire:**
- Chaque phase est indépendante
- Possible de travailler en parallèle sur certaines tâches
- Tests après chaque phase majeure

**Références:**
- `CLAUDE.md` - Spécifications complètes
- `Tasks/todo/PHASE2_DETAILED_PLAN.md` - Plan détaillé Phase 2
- `docs/MEMORY_GUIDE.md` - Guide scanning mémoire

---

**Dernière mise à jour:** 2026-02-03
**Version projet:** 0.3.0-alpha
**Phase actuelle:** Phase 0+1+2 Complete ✅ | Phase 3 (Duel Warp) Next
