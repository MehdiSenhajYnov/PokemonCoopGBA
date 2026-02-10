# P0_12 — Framework de Test Autonome mGBA

> **Statut:** Completed (2026-02-06)
> **Type:** Feature — Infrastructure de test automatisée pour itération autonome par Claude
> **Priorité:** ⭐ Haute (déblocke toutes les phases suivantes)
> **Objectif:** Permettre à Claude d'itérer en boucle autonome : écrire code → lancer mGBA → lire résultats (JSON + screenshots) → corriger → relancer, sans intervention humaine.

---

## Vue d'ensemble

### Problème actuel
Chaque modification nécessite que l'utilisateur lance manuellement mGBA, charge le script, observe le comportement, et rapporte les résultats. Ce cycle manuel est le principal goulot d'étranglement du projet.

### Solution validée (POC)
Un Proof of Concept a démontré que le cycle complet est réalisable :

```
┌─────────────────────────────────────────────┐
│  1. Claude écrit/modifie le code            │
│  2. Claude écrit un test Lua                │
│  3. Claude lance mGBA (--script + ROM)      │
│  4. Le script Lua:                          │
│     • Charge le save state (slot 1)         │
│     • Exécute les tests mémoire             │
│     • Prend des screenshots                 │
│     • Écrit résultats en JSON               │
│  5. Claude lit le JSON + les screenshots    │
│  6. Claude analyse visuellement le rendu    │
│  7. Si fail → corrige → retour au 1        │
│  └─ ~12 secondes par cycle                  │
└─────────────────────────────────────────────┘
```

### Capacités confirmées (POC 2026-02-06)

| Capacité | Status | Détails |
|----------|--------|---------|
| `--script` flag | ✅ | `mGBA.exe --script test.lua ROM.gba` |
| Save state load | ✅ | `emu:loadStateSlot(1)` |
| WRAM read/write | ✅ | `emu.memory.wram` (**PAS** `ewram`) |
| IWRAM read/write | ✅ | `emu.memory.iwram` |
| cart0 read/write | ✅ | ROM patching confirmé (write+readback) |
| Screenshot file | ✅ | `emu:screenshot(path)` → PNG |
| Screenshot Image | ✅ | `emu:screenshotToImage()` → Image object |
| File I/O | ✅ | `io.open()` complet (read/write) |
| `os.clock()` | ✅ | Delta time réel disponible |
| `os.exit(0)` | ❌ | Ne tue PAS mGBA proprement |
| Kill process | ✅ | `powershell -Command "Stop-Process -Name mGBA -Force"` |
| Temps par cycle | ~12s | Dont ~2s stabilisation + ~10s marge |

### Contrainte critique : domaine mémoire
```
✅ emu.memory.wram     -- EWRAM (0x02000000), offsets relatifs (ex: 0x24CBC)
✅ emu.memory.iwram    -- IWRAM (0x03000000), offsets relatifs (ex: 0x5DFC)
✅ emu.memory.cart0    -- ROM (0x08000000), offsets relatifs (ex: 0x00A4B0)
❌ emu.memory.ewram    -- N'EXISTE PAS (nil)
```

---

## Implémentation

### Section 1 — Test Runner Lua (`scripts/testing/runner.lua`)

**Fichiers concernés:**
- `scripts/testing/runner.lua` — Framework de test principal (à créer)
- `scripts/testing/assertions.lua` — Bibliothèque d'assertions (à créer)

**Détails:**

Le runner doit :
1. Charger le save state slot 1 via `emu:loadStateSlot(1)`
2. Attendre N frames de stabilisation (configurable, défaut 120 = 2 secondes)
3. Exécuter les test suites enregistrées
4. Prendre des screenshots à des moments clés (avant/après actions)
5. Écrire tous les résultats dans `test_results.json`
6. Écrire les screenshots dans `test_screenshots/` (avec noms descriptifs)

**API du runner :**
```lua
local Runner = {}

-- Enregistrer une suite de tests
Runner.suite(name, function(t)
    t.test("nom_du_test", function()
        t.assertEqual(valeur, attendu, "message")
        t.assertRange(valeur, min, max, "message")
        t.assertTrue(condition, "message")
        t.screenshot("nom_capture")  -- sauvegarde screenshot
    end)
end)

-- Lancer tous les tests après stabilisation
Runner.run({
    saveStateSlot = 1,
    stabilizationFrames = 120,
    screenshotDir = "C:/.../test_screenshots/",
    resultsFile = "C:/.../test_results.json",
})
```

**Format JSON des résultats :**
```json
{
    "timestamp": "2026-02-06 14:30:00",
    "saveState": true,
    "duration_ms": 2500,
    "screenshots": ["overworld_initial.png", "after_warp.png"],
    "suites": [
        {
            "name": "memory_addresses",
            "tests": [
                {"name": "playerX_readable", "pass": true, "value": 6, "details": ""},
                {"name": "partyCount_valid", "pass": true, "value": 1, "details": "range [1,6]"}
            ],
            "passed": 2, "failed": 0
        }
    ],
    "summary": {"total": 12, "passed": 12, "failed": 0}
}
```

### Section 2 — Suites de Tests Modulaires

**Fichiers concernés:**
- `scripts/testing/suites/memory.lua` — Validation adresses mémoire (à créer)
- `scripts/testing/suites/rom_patches.lua` — Test ROM patching (à créer)
- `scripts/testing/suites/battle.lua` — Test battle system (à créer)
- `scripts/testing/suites/warp.lua` — Test warp system (à créer)
- `scripts/testing/suites/network.lua` — Test protocole réseau (à créer)

**Suite memory.lua :**
Vérifie que toutes les adresses dans `config/run_and_bun.lua` sont lisibles et retournent des valeurs saines :
- PlayerX/Y (u16, valeurs > 0)
- MapGroup/MapId (u8)
- PartyCount (u8, range [1,6])
- gPlayerParty (600 bytes lisibles)
- gBattleTypeFlags (u32)
- gMainInBattle (u8, 0 en overworld)
- callback2 (u32, != 0 en overworld normal)
- gBattleResources (u32)
- IWRAM: cameraX/Y, gWirelessCommType, gReceivedRemoteLinkPlayers

**Suite rom_patches.lua :**
Valide que le ROM patching fonctionne pour le battle system :
- Lire `GetMultiplayerId` (cart0 offset `0x00A4B0`) — sauvegarder original
- Écrire patch host `00 20 70 47` (MOV R0,#0; BX LR)
- Readback et vérifier
- Restaurer original
- Écrire patch client `01 20 70 47` (MOV R0,#1; BX LR)
- Readback et vérifier
- Restaurer original
- Tester `PlayerBufferExecCompleted` patch (+0x1C: écrire 0xE01C)
- Tester `LinkOpponentBufferExecCompleted` patch (+0x1C: écrire 0xE01C)
- Tester `PrepareBufferDataTransferLink` patch (+0x18: écrire 0xE008)

Adresses ROM référencées (`config/run_and_bun.lua`):
- `GetMultiplayerId`: `0x0800A4B1` (cart0 offset `0x00A4B0`)
- `PlayerBufferExecCompleted`: `0x0806F0D5` (cart0 offset `0x06F0D4`, patch à +0x1C = `0x06F0F0`)
- `LinkOpponentBufferExecCompleted`: `0x08078789` (cart0 offset `0x078788`, patch à +0x1C = `0x0787A4`)
- `PrepareBufferDataTransferLink`: `0x08032FA9` (cart0 offset `0x032FA8`, patch à +0x18 = `0x032FC0`)

**Suite battle.lua :**
Tests multi-phase du battle system (nécessite actions séquentielles) :
1. Vérifier état initial (inBattle=0, battleTypeFlags=0)
2. Lire party locale via `Battle.readLocalParty()` (600 bytes)
3. Injecter une party test dans gEnemyParty via `Battle.injectEnemyParty()`
4. Readback gEnemyParty et vérifier match
5. Appliquer tous les ROM+EWRAM patches (`battle.lua` lignes 300-400)
6. Screenshot après patches
7. Vérifier gWirelessCommType=0, gReceivedRemoteLinkPlayers=1
8. Setter callback2 = CB2_HandleStartBattle (0x08037B45)
9. Attendre N frames, screenshots périodiques
10. Vérifier que inBattle passe à 1
11. Restaurer tous les patches

**Suite warp.lua :**
1. Lire position actuelle (playerX/Y, mapGroup/mapId)
2. Écrire sWarpDestination (0x020318A8) avec coords duel room (28, 24, 3, 5)
3. Readback sWarpDestination
4. Screenshot avant warp
5. Optionnel: trigger warp et vérifier map change (avancé)

**Suite network.lua :**
Nécessite le serveur Node.js lancé en parallèle :
1. Importer `client/network.lua`
2. Tenter connexion à `127.0.0.1:8080`
3. Envoyer message registration
4. Recevoir réponse
5. Tester encodage/décodage JSON (vérifier round-trip)

### Section 3 — Launcher (Claude-side)

**Fichiers concernés:**
- Aucun fichier à créer — c'est le workflow que Claude exécute via Bash

**Séquence de commandes standard :**
```powershell
# 1. Kill toute instance existante
powershell -Command "Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue"

# 2. Nettoyer les résultats précédents
rm -f test_results.json test_screenshots/*.png

# 3. Lancer mGBA avec le test script
cd C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA
start "" "mgba/mGBA.exe" --script "scripts/testing/run_all.lua" "rom/Pokemon RunBun.gba"

# 4. Attendre les résultats (poll le fichier)
# Boucle: sleep 2 + check si test_results.json existe et contient "status":"complete"

# 5. Lire les résultats
cat test_results.json

# 6. Lire les screenshots (Claude est multimodal)
# Read tool sur chaque .png dans test_screenshots/

# 7. Kill mGBA
powershell -Command "Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue"
```

**Point d'entrée unique : `scripts/testing/run_all.lua`**
Ce script charge le runner + toutes les suites et lance l'exécution. Claude n'a qu'à lancer cette commande.

### Section 4 — Screenshots périodiques

**Fichiers concernés:**
- `scripts/testing/runner.lua` — Intégré dans le runner

**Détails:**
Le runner supporte deux modes de capture :
1. **Screenshots explicites** : via `t.screenshot("nom")` dans les tests
2. **Screenshots périodiques** : option `periodicScreenshots = N` — capture toutes les N frames pendant l'exécution
3. **Screenshots conditionnels** : capture automatiquement quand un test échoue

Toutes les captures sont nommées avec un préfixe séquentiel : `001_overworld_initial.png`, `002_after_patch.png`, etc.

Claude peut ensuite les analyser visuellement via `Read` tool (multimodal).

### Section 5 — Tests multi-frames (actions séquentielles)

**Fichiers concernés:**
- `scripts/testing/runner.lua` — Support des tests asynchrones

**Détails:**
Certains tests nécessitent d'attendre plusieurs frames (ex: vérifier qu'un warp se termine, qu'un combat démarre). Le runner doit supporter :

```lua
t.asyncTest("battle_starts", function(done)
    -- Frame 0: Apply patches
    applyPatches()
    t.screenshot("before_battle")

    -- Frame 60: Check if battle started
    t.waitFrames(60, function()
        local inBattle = emu.memory.wram:read8(0x0206AE)
        t.assertEqual(inBattle, 1, "battle should have started")
        t.screenshot("in_battle")
        done()
    end)
end)
```

Implémentation via callbacks chaînés dans `callbacks:add("frame", ...)`.

### Section 6 — Intégration avec le server Node.js

**Fichiers concernés:**
- `server/server.js` — Pas de modification nécessaire
- `scripts/testing/suites/network.lua` — Tests E2E

**Détails:**
Pour les tests réseau, Claude lance le serveur en background avant mGBA :
```bash
# Lancer le serveur en background
cd server && node server.js &

# Puis lancer mGBA avec les tests
start "" "mgba/mGBA.exe" --script "scripts/testing/run_all.lua" "rom/Pokemon RunBun.gba"
```

La suite `network.lua` utilise l'API socket mGBA (`socket.connect()`) pour se connecter au serveur et vérifier les échanges.

### Section 7 — Tests E2E deux joueurs

**Fichiers concernés:**
- `scripts/testing/suites/e2e_battle.lua` — Tests deux instances (à créer, futur)

**Détails (phase avancée, pas prioritaire):**
Lancer 2 instances mGBA avec des scripts différents (master + slave) :
```bash
start "" "mgba/mGBA.exe" --script "scripts/testing/e2e_master.lua" "rom/Pokemon RunBun.gba"
start "" "mgba/mGBA.exe" --script "scripts/testing/e2e_slave.lua" "rom/Pokemon RunBun.gba"
```

Coordination via fichiers partagés ou le serveur TCP. Non prioritaire pour la v1.

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `scripts/testing/runner.lua` | Framework de test principal (load save state, run suites, JSON output, screenshots) |
| `scripts/testing/assertions.lua` | Bibliothèque assertions (assertEqual, assertRange, assertTrue, screenshot) |
| `scripts/testing/run_all.lua` | Point d'entrée unique (charge runner + toutes les suites) |
| `scripts/testing/suites/memory.lua` | Suite: validation adresses mémoire (WRAM/IWRAM/cart0) |
| `scripts/testing/suites/rom_patches.lua` | Suite: test ROM patching (write+readback pour chaque patch) |
| `scripts/testing/suites/battle.lua` | Suite: test battle system (patches, party inject, trigger, state machine) |
| `scripts/testing/suites/warp.lua` | Suite: test warp system (sWarpDestination write, map change) |
| `scripts/testing/suites/network.lua` | Suite: test connexion réseau (socket + JSON round-trip) |

## Fichiers à modifier

| Fichier | Modification |
|---------|-------------|
| `scripts/test_harness_poc.lua` | Archiver vers `scripts/archive/` (remplacé par le framework) |
| `scripts/test_minimal.lua` | Archiver vers `scripts/archive/` (remplacé par le framework) |

## Fichiers à supprimer / archiver

| Fichier | Action |
|---------|--------|
| `test_results.json` (racine) | Supprimé à chaque run (généré dynamiquement) |
| `test_screenshot.png` (racine) | Supprimé à chaque run (remplacé par `test_screenshots/`) |
| `test_screenshot2.png` (racine) | Supprimer (artefact POC) |

---

## Prérequis

1. **Save state slot 1** : Le jeu doit être en overworld avec au moins 1 Pokémon dans l'équipe
   - Actuellement disponible : `rom/Pokemon RunBun.ss1` (position 6,17 devant un Centre Pokémon, 1 Pokémon)
2. **ROM** : `rom/Pokemon RunBun.gba`
3. **mGBA** : `mgba/mGBA.exe` (version 0.11-8977, `--script` supporté)
4. **Serveur** (optionnel, pour tests réseau) : `node server/server.js`

---

## Plan d'implémentation

### Phase 1 : Core Framework (priorité immédiate)
- [x] **1.1** Créer `scripts/testing/runner.lua` — structure de base (load save, wait frames, run tests, write JSON)
- [x] **1.2** Créer `scripts/testing/assertions.lua` — assertEqual, assertRange, assertTrue, screenshot
- [x] **1.3** Créer `scripts/testing/run_all.lua` — point d'entrée (require runner + suites)
- [x] **1.4** Créer `scripts/testing/suites/memory.lua` — test toutes les adresses connues
- [ ] **1.5** Valider le cycle complet : Claude lance → résultats → screenshots → analyse (requires mGBA + save state)

### Phase 2 : Suites spécialisées (battle system)
- [x] **2.1** Créer `scripts/testing/suites/rom_patches.lua` — write+readback chaque patch ROM
- [x] **2.2** Créer `scripts/testing/suites/battle.lua` — party inject, patches, trigger battle
- [x] **2.3** Support tests multi-frames (asyncTest avec waitFrames)
- [x] **2.4** Screenshots périodiques automatiques pendant les tests battle

### Phase 3 : Tests réseau et E2E
- [x] **3.1** Créer `scripts/testing/suites/network.lua` — connexion server + JSON round-trip
- [x] **3.2** Créer `scripts/testing/suites/warp.lua` — sWarpDestination + map change
- [ ] **3.3** (Futur) E2E deux joueurs — coordination master/slave

### Phase 4 : Polish
- [x] **4.1** Archiver `scripts/test_harness_poc.lua` et `scripts/test_minimal.lua`
- [ ] **4.2** Nettoyer artefacts POC (test_screenshot.png, test_results.json racine)
- [ ] **4.3** Documenter le workflow dans CLAUDE.md (section testing)

---

## Notes techniques

### Kill mGBA
```powershell
# ✅ Fonctionne toujours :
powershell -Command "Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue"

# ❌ Ne fonctionne PAS toujours :
taskkill /F /IM mGBA.exe

# ❌ Ne tue PAS le process :
os.exit(0)  -- depuis Lua
```

### Chemins absolus (requis par io.open dans mGBA)
Les scripts Lua dans mGBA doivent utiliser des chemins absolus ou `script.dir` pour les I/O fichier :
```lua
local BASE = "C:/Users/mehdi/Desktop/Dev/PokemonCoopGBA"
-- ou
local BASE = script.dir .. "/../.."  -- si lancé depuis scripts/testing/
```

### Domaines mémoire mGBA
```lua
emu.memory.wram    -- EWRAM (offsets depuis 0x02000000)
emu.memory.iwram   -- IWRAM (offsets depuis 0x03000000)
emu.memory.cart0   -- ROM   (offsets depuis 0x08000000)
-- emu.memory.ewram N'EXISTE PAS
```

### Timing
- 1 frame = ~16.67ms à 60fps
- 120 frames = ~2 secondes (stabilisation save state)
- Cycle complet (launch → results) = ~12 secondes
- Marge recommandée pour poll résultats : 15 secondes

---

**Dernière mise à jour:** 2026-02-06
**Estimé:** Phase 1 = ~200 lignes Lua, Phase 2 = ~300 lignes, Phase 3 = ~150 lignes
