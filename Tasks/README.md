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

### todo/P0_00_MEMORY_OFFSET_DISCOVERY.md
**Status:** 🔴 À faire ⭐ **PRIORITÉ CRITIQUE**
**Description:** Identifier et documenter les offsets mémoire de Run & Bun (statiques ou dynamiques)

**Problématique:**
Run & Bun modifie énormément Émeraude. Les offsets vanilla ne fonctionneront probablement PAS. On doit:
1. Tester si offsets Emerald vanilla fonctionnent (test rapide)
2. Si non, scanner avec debugger Lua mGBA
3. Identifier si offsets statiques (0x02xxxxxx) ou dynamiques (via pointeurs SaveBlock)
4. Créer profil `config/run_and_bun.lua`
5. Adapter HAL si mode dynamique

**Contenu:**
- 0.1: Test rapide offsets vanilla (2 min)
- 0.2: Scan Lua WRAM si échec (scripts fournis)
- 0.3: Identifier type (statique vs dynamique)
- 0.4: Créer profil ROM
- 0.5: Adapter HAL si dynamique
- 0.6: Tests validation
- 0.7: Améliorer detection ROM

**Fichiers:**
- ✨ Créer: `config/run_and_bun.lua`
- 📝 Modifier (optionnel): `client/hal.lua:140-173`, `client/main.lua:59-79`
- 📝 Documenter: `docs/RUN_AND_BUN.md`

**Référence complète:** `docs/MEMORY_SCANNING_GUIDE.md`

**⚠️ BLOQUANT:** Cette phase DOIT être terminée avant Phase 1 (impossible de lire positions sinon)

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

### todo/P2_03_GHOSTING_RENDER.md
**Status:** 🔴 À faire
**Tâches groupées:** #4 + #5 + #6
**Description:** Système complet d'affichage visuel des autres joueurs

**Contenu:**
- Partie 1: Rechercher offsets caméra (Cheat Engine)
- Partie 2: Créer `client/render.lua` (conversion coordonnées, gui.drawRectangle)
- Partie 3: Intégrer dans `main.lua` (boucle update)

**Fichiers:**
- ✨ Créer: `client/render.lua`
- 📝 Modifier: `config/emerald_us.lua` (cameraX/Y), `client/hal.lua` (readCamera), `client/main.lua`

**Features:**
- Carrés colorés représentant ghosts
- Noms affichés au-dessus
- Filtrage par map
- Toggle visibilité (F3)

---

### todo/P2_04_INTERPOLATION.md
**Status:** 🔴 À faire
**Tâches groupées:** #7 + #8
**Description:** Mouvement fluide des ghosts via interpolation linéaire

**Contenu:**
- Partie 1: Créer `client/interpolate.lua` (lerp, gestion téléportations)
- Partie 2: Intégrer dans `main.lua` (step chaque frame, positions interpolées)
- Partie 3: Améliorer `render.lua` avec flèches direction et trails

**Fichiers:**
- ✨ Créer: `client/interpolate.lua`
- 📝 Modifier: `client/main.lua` (ligne 12, 173+, réception positions, drawOtherPlayers)

**Paramètres:**
- `INTERPOLATION_SPEED = 0.15` (15% par frame)
- `TELEPORT_THRESHOLD = 10` (tiles)

---

### todo/P2_05_NETWORK_POLISH.md
**Status:** 🔴 À faire
**Tâche:** #9
**Description:** Gestion robuste déconnexion/reconnexion

**Contenu:**
- Auto-reconnexion avec backoff exponentiel
- Détection déconnexion serveur
- Nettoyage ghosts inactifs (timeout)
- Indicateur UI statut connexion

**Fichiers:**
- 📝 Modifier: `client/network.lua`, `client/main.lua`

---

### todo/P2_06_OPTIMIZATION.md
**Status:** 🔴 À faire
**Tâche:** #10
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

### todo/P2_07_FINAL_TESTING.md
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

### todo/P3_08_DUEL_WARP.md
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

### todo/P4_09_MULTI_ROM.md
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

### todo/P5_10_DOCUMENTATION.md
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
Phase 2 - Ghosting            [░░░░░░░░░░]  0%
Phase 3 - Duel Warp           [░░░░░░░░░░]  0%
Phase 4 - Multi-ROM           [░░░░░░░░░░]  0%
Phase 5 - Documentation       [░░░░░░░░░░]  0%

Global                        [███░░░░░░░] 33%
```

---

## 🎯 Ordre d'exécution recommandé

Toutes les tâches sont dans `todo/` jusqu'à leur complétion:

0. **todo/P0_00_MEMORY_OFFSET_DISCOVERY.md** ⭐ ← **COMMENCER ICI (BLOQUANT)**
1. **todo/P1_01_TCP_NETWORK.md**
2. **todo/P1_02_TCP_TESTING.md**
3. **todo/P2_03_GHOSTING_RENDER.md**
4. **todo/P2_04_INTERPOLATION.md**
5. **todo/P2_05_NETWORK_POLISH.md**
6. **todo/P2_06_OPTIMIZATION.md**
7. **todo/P2_07_FINAL_TESTING.md**
8. **todo/P3_08_DUEL_WARP.md**
9. **todo/P4_09_MULTI_ROM.md** (Radical Red, Unbound)
10. **todo/P5_10_DOCUMENTATION.md**

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
- `docs/PHASE2_PLAN.md` - Plan détaillé Phase 2
- `docs/PROJECT_STRUCTURE.md` - Architecture système

---

**Dernière mise à jour:** 2026-02-02
**Version projet:** 0.2.0-alpha
**Phase actuelle:** Phase 1 Complete ✅ | Phase 2 (Ghosting) Ready to Start
