# Phase 0 - Découverte des Offsets Mémoire Run & Bun

> **Statut:** ✅ COMPLÉTÉ (2026-02-02)
> **Type:** Research & Configuration — Identification offsets mémoire
> **Objectif:** Identifier et documenter les adresses mémoire (statiques ou dynamiques) pour Pokémon Run & Bun afin de permettre la lecture des coordonnées joueur et données de map

---

## 🚨 Problématique Critique

**Run & Bun modifie énormément la ROM de base d'Émeraude.** Les offsets mémoire d'Émeraude vanilla (actuellement dans `config/emerald_us.lua`) **NE FONCTIONNERONT PAS** directement.

### Deux Types d'Adresses Possibles

1. **Offsets STATIQUES** (facile)
   - Données toujours à la même adresse WRAM (0x02xxxxxx)
   - Lecture directe avec `memory.read16(address)`
   - Utilisé actuellement par le code

2. **Offsets DYNAMIQUES** (complexe)
   - Données accessibles via pointeurs (ex: SaveBlock1/2)
   - Pointeurs de base fixes (IWRAM 0x03xxxxxx)
   - Offsets relatifs aux pointeurs
   - Nécessite `HAL.readSafePointer()` *(déjà implémenté mais pas utilisé)*

**On doit identifier quel type Run & Bun utilise AVANT de continuer.**

---

## Vue d'ensemble

Cette phase DOIT être complétée avant Phase 1 (TCP Network) car sans offsets corrects, on ne peut pas:
- Lire la position du joueur
- Synchroniser les positions
- Tester le ghosting

### Référence Documentation

Voir guide complet: **`docs/MEMORY_SCANNING_GUIDE.md`**

---

## Implémentation

### 0.1 - Phase de Test Rapide (Offsets Émeraude Vanilla)

**Objectif:** Vérifier si par chance les offsets d'Émeraude vanilla fonctionnent sur Run & Bun

**Fichiers concernés:**
- `config/emerald_us.lua:18-28` — Offsets de référence

**Procédure:**

- [ ] **0.1.1** Lancer Run & Bun dans mGBA
  - Charger la ROM dans mGBA 0.10.0+
  - Ouvrir **Tools → Scripting**

- [ ] **0.1.2** Tester offsets Émeraude dans la console Lua:
  ```lua
  -- Copier-coller dans console mGBA
  print("=== Test Offsets Emerald Vanilla ===")
  local x = memory.read16(0x02024844)
  local y = memory.read16(0x02024846)
  local mapId = memory.readByte(0x02024842)
  local mapGroup = memory.readByte(0x02024843)
  local facing = memory.readByte(0x02024848)

  print(string.format("X: %d (0x%04X)", x, x))
  print(string.format("Y: %d (0x%04X)", y, y))
  print(string.format("MapID: %d, MapGroup: %d", mapId, mapGroup))
  print(string.format("Facing: %d", facing))
  print("\nSe déplacer dans le jeu puis relancer ce script")
  ```

- [ ] **0.1.3** Se déplacer dans le jeu (haut/bas/gauche/droite)

- [ ] **0.1.4** Relancer le script et observer:
  - **✅ SI valeurs changent correctement** (X/Y augmentent/diminuent logiquement):
    - → Offsets vanilla fonctionnent! Passer à section 0.4
  - **❌ SI valeurs random/garbage ou ne changent pas**:
    - → Passer à section 0.2 (Scan Lua)

**Résultat attendu:** Savoir en 2 minutes si on peut utiliser les offsets vanilla

---

### 0.2 - Scan Mémoire avec Debugger Lua (Si 0.1 échoue)

**Objectif:** Scanner la WRAM GBA pour trouver les coordonnées du joueur

**Fichiers concernés:**
- Aucun (utilisation console mGBA)

**Référence:** `docs/MEMORY_SCANNING_GUIDE.md` — Section "Méthode 1: Debugger mGBA intégré"

**Procédure:**

- [ ] **0.2.1** Créer script de scan dans console mGBA:
  ```lua
  -- Scanner WRAM pour une valeur
  function scanWRAM(value, size)
    local start = 0x02000000
    local end_addr = 0x0203FFFF
    local results = {}

    print(string.format("Scanning for value %d (0x%X) with size %d bytes...", value, value, size))

    for addr = start, end_addr, size do
      local read_value
      if size == 1 then
        read_value = memory.readByte(addr)
      elseif size == 2 then
        read_value = memory.read16(addr)
      elseif size == 4 then
        read_value = memory.read32(addr)
      end

      if read_value == value then
        table.insert(results, addr)
      end
    end

    print(string.format("Found %d matches:", #results))
    for i, addr in ipairs(results) do
      if i <= 20 then -- Limiter affichage
        print(string.format("  0x%08X", addr))
      end
    end

    return results
  end
  ```

- [ ] **0.2.2** Scanner coordonnée X:
  1. Noter position X actuelle (compter les tiles depuis un point de référence)
  2. Estimer valeur (tiles × 16, ex: tile 10 → X ≈ 160)
  3. Scanner: `local results_x = scanWRAM(160, 2)`
  4. Se déplacer horizontalement (5+ tiles)
  5. Rescanner nouvelle valeur
  6. Répéter jusqu'à avoir 1-5 adresses candidates

- [ ] **0.2.3** Scanner coordonnée Y (même méthode, mouvement vertical)

- [ ] **0.2.4** Valider candidats:
  ```lua
  -- Tester une adresse candidate
  local candidate = 0x02??????

  while true do
    emu:runFrame()
    local value = memory.read16(candidate)
    print(string.format("0x%08X = %d", candidate, value))
  end
  ```
  Observer si la valeur change correctement en se déplaçant

- [ ] **0.2.5** Scanner MapID et MapGroup (1 byte chacun)
  - Changer de map (entrer bâtiment, changer route)
  - Scanner valeurs qui changent
  - Généralement proches de X/Y en mémoire

**Résultat attendu:** Liste d'adresses WRAM candidates pour X, Y, MapID, MapGroup, Facing

---

### 0.3 - Identifier Type (Statique vs Dynamique)

**Objectif:** Déterminer si les adresses trouvées sont fixes ou via pointeurs

**Procédure:**

- [ ] **0.3.1** Test de stabilité - Sauvegarder puis recharger:
  1. Noter adresses trouvées (ex: PlayerX = 0x02025000)
  2. Créer savestate mGBA
  3. Charger le savestate
  4. Vérifier si données toujours aux mêmes adresses

  **SI oui** → Offsets STATIQUES (facile!)
  **SI non** → Offsets DYNAMIQUES (continuer)

- [ ] **0.3.2** Si dynamiques - Chercher pointeurs SaveBlock:
  ```lua
  -- Scanner IWRAM pour pointeurs vers WRAM
  print("=== Searching for SaveBlock pointers ===")
  local iwram_start = 0x03000000
  local iwram_end = 0x03007FFF

  for addr = iwram_start, iwram_end, 4 do
    local ptr = memory.read32(addr)
    -- Un pointeur SaveBlock pointe vers WRAM
    if ptr >= 0x02000000 and ptr <= 0x0203FFFF then
      print(string.format("Potential pointer at 0x%08X -> 0x%08X", addr, ptr))
    end
  end
  ```

- [ ] **0.3.3** Tester candidats SaveBlock:
  ```lua
  -- Test si c'est SaveBlock1
  local ptr_addr = 0x03005D8C -- Exemple
  local sb1_ptr = memory.read32(ptr_addr)

  print(string.format("SaveBlock1 pointer: 0x%08X", sb1_ptr))

  -- Dumper structure pour trouver offsets relatifs
  print("=== Structure dump ===")
  for offset = 0, 0x100, 2 do
    local value = memory.read16(sb1_ptr + offset)
    print(string.format("+0x%04X: %5d (0x%04X)", offset, value, value))
  end
  ```

  Chercher visuellement les coordonnées du joueur dans ce dump

**Résultat attendu:** Savoir si offsets statiques ou dynamiques + adresses/pointeurs exacts

---

### 0.4 - Créer Profil ROM Run & Bun

**Objectif:** Documenter offsets dans fichier config

**Fichiers à créer:**
- `config/run_and_bun.lua` — Profil ROM Run & Bun

**Procédure:**

- [ ] **0.4.1** Si offsets STATIQUES - Créer profil simple:
  ```lua
  --[[
    Pokémon Run & Bun Configuration

    ROM hack basé sur Émeraude avec modifications majeures
    Game ID: [À compléter]
    Version: [À compléter]

    Offsets trouvés via scan mGBA Lua le [DATE]
  ]]

  return {
    -- Game metadata
    name = "Pokémon Run & Bun",
    gameId = "BPEE", -- ou autre si différent
    version = "1.0",

    -- Memory offsets (STATIQUES)
    offsets = {
      -- Coordonnées joueur (trouvées via scan)
      playerX = 0x02??????,     -- [ADRESSE TROUVÉE]
      playerY = 0x02??????,     -- [ADRESSE TROUVÉE]

      -- Informations map
      mapGroup = 0x02??????,    -- [ADRESSE TROUVÉE]
      mapId = 0x02??????,       -- [ADRESSE TROUVÉE]

      -- État joueur
      facing = 0x02??????,      -- [ADRESSE TROUVÉE]

      -- Optionnel (Phase 2+)
      isMoving = nil,           -- TBD
      runningState = nil,       -- TBD

      -- SaveBlock pointers (si trouvés)
      saveBlock1Ptr = nil,      -- TBD si nécessaire
      saveBlock2Ptr = nil,      -- TBD si nécessaire
    },

    -- Validation ranges
    validation = {
      minX = 0,
      maxX = 1024,
      minY = 0,
      maxY = 1024,
      minMapGroup = 0,
      maxMapGroup = 50,  -- Ajuster selon Run & Bun
      minMapId = 0,
      maxMapId = 255
    },

    -- Fonction validation (copier depuis emerald_us.lua)
    validatePosition = function(self, x, y, mapGroup, mapId)
      local v = self.validation
      if x < v.minX or x > v.maxX then return false end
      if y < v.minY or y > v.maxY then return false end
      if mapGroup < v.minMapGroup or mapGroup > v.maxMapGroup then return false end
      if mapId < v.minMapId or mapId > v.maxMapId then return false end
      return true
    end,
  }
  ```

- [ ] **0.4.2** Si offsets DYNAMIQUES - Créer profil avec pointeurs:
  ```lua
  return {
    name = "Pokémon Run & Bun",
    gameId = "BPEE",
    version = "1.0",

    -- Mode dynamique activé
    useDynamicPointers = true,

    -- Pointeurs de base (IWRAM - fixes)
    pointers = {
      saveBlock1 = 0x03??????, -- [ADRESSE POINTER TROUVÉE]
      saveBlock2 = 0x03??????, -- Si nécessaire
    },

    -- Offsets RELATIFS aux pointeurs
    offsets = {
      -- Format: {pointer = "nom", offsets = {offset1, offset2, ...}}
      playerX = {pointer = "saveBlock1", offsets = {0x????}},
      playerY = {pointer = "saveBlock1", offsets = {0x????}},
      mapId = {pointer = "saveBlock1", offsets = {0x????}},
      mapGroup = {pointer = "saveBlock1", offsets = {0x????}},
      facing = {pointer = "saveBlock1", offsets = {0x????}},
    },

    -- ... reste identique
  }
  ```

**Résultat attendu:** Fichier config complet et testé

---

### 0.5 - Adapter Code HAL (Si mode dynamique)

**Objectif:** Modifier HAL pour supporter mode dynamique si nécessaire

**Fichiers à modifier:**
- `client/hal.lua:140-173` — Fonctions readPlayerX/Y/etc.

**Procédure:**

- [ ] **0.5.1** Modifier `HAL.readPlayerX()`:
  ```lua
  function HAL.readPlayerX()
    if not config or not config.offsets.playerX then
      return nil
    end

    -- Mode dynamique (via pointeur)
    if type(config.offsets.playerX) == "table" then
      local base = config.pointers[config.offsets.playerX.pointer]
      if not base then return nil end
      local addr = HAL.readSafePointer(base, config.offsets.playerX.offsets)
      if not addr then return nil end
      return safeRead(addr, 2)
    end

    -- Mode statique (adresse directe)
    return safeRead(config.offsets.playerX, 2)
  end
  ```

- [ ] **0.5.2** Répéter pour `readPlayerY()`, `readMapId()`, `readMapGroup()`, `readFacing()`

- [ ] **0.5.3** Tester avec script validation:
  ```lua
  -- Dans console mGBA après avoir chargé main.lua
  local x = HAL.readPlayerX()
  local y = HAL.readPlayerY()
  print(string.format("Position via HAL: X=%d Y=%d", x or -1, y or -1))
  ```

**Résultat attendu:** HAL fonctionne en mode dynamique si nécessaire

---

### 0.6 - Tests de Validation

**Objectif:** Valider que les offsets fonctionnent correctement

**Procédure:**

- [ ] **0.6.1** Test lecture temps réel - Créer script test:
  ```lua
  -- Charger config Run & Bun
  local config = require("config.run_and_bun")
  local HAL = require("hal")
  HAL.init(config)

  -- Boucle de test
  callbacks.add("frame", function()
    local x = HAL.readPlayerX()
    local y = HAL.readPlayerY()
    local mapId = HAL.readMapId()
    local mapGroup = HAL.readMapGroup()
    local facing = HAL.readFacing()

    gui.drawText(5, 5, string.format("X: %d Y: %d", x or -1, y or -1), 0xFFFFFF)
    gui.drawText(5, 15, string.format("Map: %d:%d", mapGroup or -1, mapId or -1), 0xFFFFFF)
    gui.drawText(5, 25, string.format("Facing: %d", facing or -1), 0xFFFFFF)
  end)
  ```

- [ ] **0.6.2** Se déplacer dans toutes les directions:
  - ↑ Haut → Y diminue
  - ↓ Bas → Y augmente
  - ← Gauche → X diminue
  - → Droite → X augmente

- [ ] **0.6.3** Changer de map:
  - Entrer dans un bâtiment → MapID change
  - Aller sur une autre route → MapID/MapGroup changent

- [ ] **0.6.4** Test stabilité - Sauvegarder/recharger:
  1. Noter position affichée
  2. Sauvegarder jeu (savestate mGBA)
  3. Recharger savestate
  4. Vérifier que position est toujours correcte

- [ ] **0.6.5** Documenter résultats dans `docs/RUN_AND_BUN.md`:
  - Adresses trouvées
  - Type (statique/dynamique)
  - Résultats des tests
  - Date et méthode utilisée

**Résultat attendu:** Confirmation que tous les offsets fonctionnent correctement

---

### 0.7 - Modifier Detection ROM (Si nécessaire)

**Objectif:** Permettre détection automatique de Run & Bun

**Fichiers à modifier:**
- `client/main.lua:59-79` — Fonction detectROM()

**Procédure:**

- [ ] **0.7.1** Identifier Game ID de Run & Bun:
  ```lua
  -- Dans console mGBA
  local code = ""
  for i = 0, 3 do
    local byte = memory.readByte(0x080000AC + i, "ROM")
    if byte and byte ~= 0 then
      code = code .. string.char(byte)
    end
  end
  print("Game ID:", code)

  local title = ""
  for i = 0, 11 do
    local byte = memory.readByte(0x080000A0 + i, "ROM")
    if byte and byte ~= 0 then
      title = title .. string.char(byte)
    end
  end
  print("Game Title:", title)
  ```

- [ ] **0.7.2** Si Game ID identique à Émeraude (BPEE):
  Ajouter détection via titre ROM dans `detectROM()`:
  ```lua
  local function detectROM()
    -- Lire game code
    local success, gameId = pcall(function()
      local code = ""
      for i = 0, 3 do
        local byte = memory.readByte(0x080000AC + i, "ROM")
        if byte and byte ~= 0 then
          code = code .. string.char(byte)
        end
      end
      return code
    end)

    -- Lire titre pour différencier hacks
    local title = ""
    pcall(function()
      for i = 0, 11 do
        local byte = memory.readByte(0x080000A0 + i, "ROM")
        if byte and byte ~= 0 then
          title = title .. string.char(byte)
        end
      end
    end)

    log("Detected ROM ID: " .. (gameId or "unknown"))
    log("Detected ROM Title: " .. title)

    -- Détection Run & Bun (titre contient "RUN" ou "BUN")
    if title:find("RUN") or title:find("BUN") then
      log("Loading Run & Bun config")
      return require("config.run_and_bun")
    end

    -- Fallback Emerald vanilla
    if gameId == "BPEE" then
      log("Loading Emerald US config")
      return require("config.emerald_us")
    end

    return nil
  end
  ```

- [ ] **0.7.3** Tester détection automatique

**Résultat attendu:** Run & Bun détecté et config chargée automatiquement

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `config/run_and_bun.lua` | Profil ROM avec offsets Run & Bun (statiques ou dynamiques) |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `client/hal.lua:140-173` | (Optionnel) Adapter fonctions read* pour mode dynamique si nécessaire |
| `client/main.lua:59-79` | (Optionnel) Améliorer detectROM() pour auto-détection Run & Bun |
| `docs/RUN_AND_BUN.md` | Documenter offsets trouvés, méthode, résultats tests |

---

## Outils Nécessaires

- **mGBA 0.10.0+** avec console Lua (Tools → Scripting)
- **ROM Pokémon Run & Bun** (dernière version)
- **Patience** (scan peut prendre 10-30 minutes)

---

## Critères de Succès

✅ Phase 0 complète quand:

1. **Type identifié** (statique ou dynamique)
2. **Offsets documentés** dans `config/run_and_bun.lua`:
   - PlayerX ✓
   - PlayerY ✓
   - MapID ✓
   - MapGroup ✓
   - FacingDirection ✓
3. **Tests validés**:
   - Lecture temps réel fonctionne ✓
   - Valeurs changent correctement au mouvement ✓
   - Stabilité après savestate ✓
4. **Documentation complète** dans `docs/RUN_AND_BUN.md`
5. **Code HAL adapté** (si mode dynamique)
6. **Détection ROM** (si possible)

---

## Prochaine Étape

Après cette tâche → **PHASE1_TCP_NETWORK.md** (Communication serveur)

**⚠️ IMPORTANT:** Cette phase DOIT être terminée avant de commencer Phase 1, sinon impossible de synchroniser les positions.

---

## 📚 Ressources

- **Guide complet:** `docs/MEMORY_SCANNING_GUIDE.md`
- **Référence config:** `config/emerald_us.lua`
- **Code HAL:** `client/hal.lua:78-108` (fonction readSafePointer déjà implémentée)
- **mGBA Scripting:** https://mgba.io/docs/scripting.html

---

**Effort estimé:** 1-3 heures (selon si offsets statiques ou dynamiques)
**Priorité:** 🔴 CRITIQUE - Bloque toute la suite du projet
