# Guide Complet: Scan Mémoire pour Run & Bun

## Vue d'ensemble

**Pokémon Run & Bun** est le ROM hack cible principal de ce projet. Basé sur Pokémon Émeraude, il modifie énormément le code, ce qui signifie que **les offsets mémoire d'Émeraude vanilla NE FONCTIONNERONT PAS**.

**Objectif:** Trouver les adresses mémoire spécifiques à Run & Bun pour lire les données du joueur en temps réel.

## ⚠️ CRITIQUE: Adresses Statiques vs Dynamiques

Les adresses mémoire GBA peuvent être de deux types:

### 1. Statiques (Offsets fixes)
- Les données sont toujours au même endroit dans WRAM (0x02xxxxxx)
- Simple à utiliser: lecture directe de l'adresse
- Exemple: `playerX = memory.read16(0x02024844)`

### 2. Dynamiques (Via pointeurs)
- Les données sont à des adresses qui changent à chaque session
- Il faut suivre une chaîne de pointeurs (SaveBlock1/2)
- Exemple: `SaveBlock1Ptr → offset +0x10 → playerX`
- Le code HAL a déjà `readSafePointer()` pour supporter ça

**Stratégie:** On doit d'abord TESTER pour savoir quel type Run & Bun utilise.

## Offsets à Trouver

### Haute Priorité (Phase 1)
- [ ] **PlayerX** - Coordonnée X du joueur
- [ ] **PlayerY** - Coordonnée Y du joueur
- [ ] **MapID** - ID de la map actuelle
- [ ] **MapGroup** - Groupe de la map actuelle
- [ ] **FacingDirection** - Direction où regarde le joueur

### Moyenne Priorité (Phase 2-3)
- [ ] **Camera X/Y** - Position de la caméra (pour rendering ghosts)
- [ ] **Player Name** - Pour affichage au-dessus des ghosts
- [ ] **Player Sprite** - Pour affichage du sprite correct
- [ ] **Movement State** - Marche/court/vélo

### Basse Priorité (Phase 4+)
- [ ] **Battle Flag** - Pour savoir si en combat
- [ ] **Pokémon Party** - Pour features avancées
- [ ] **Badges** - Pour matchmaking

## Méthodologie de Scan

### ✅ Méthode Recommandée: Debugger Lua mGBA

**Pourquoi mGBA et pas Cheat Engine?**
- Scan direct de la WRAM GBA (adresses 0x02000000+)
- Pas de problème d'ASLR du processus PC
- Adresses trouvées directement utilisables
- Console Lua intégrée pour tester en live

### Phase 1: Tester les Offsets Émeraude Vanilla

Même si Run & Bun modifie le code, testons d'abord les offsets d'Émeraude vanilla comme point de départ.

**Dans mGBA:**
1. Charger Run & Bun
2. **Tools → Scripting → Console Lua**
3. Copier-coller ce script:

```lua
-- Test des offsets Émeraude vanilla
local test_addresses = {
  {addr = 0x02024844, name = "PlayerX (Emerald)"},
  {addr = 0x02024846, name = "PlayerY (Emerald)"},
  {addr = 0x02024842, name = "MapID (Emerald)"},
  {addr = 0x02024843, name = "MapGroup (Emerald)"},
}

print("=== Testing Emerald vanilla offsets ===")
for _, test in ipairs(test_addresses) do
  local value = memory.read16(test.addr)
  print(string.format("%s: %d (0x%04X)", test.name, value, value))
end
print("\nWalk around and run this script again to see if values change correctly.")
```

4. Se déplacer dans le jeu
5. Relancer le script

**Résultats:**
- ✅ Les valeurs changent correctement → BINGO! Offsets statiques fonctionnent
- ❌ Valeurs random/garbage → Passer à Phase 2

### Phase 2: Scanner avec Lua

Si Phase 1 échoue, scanner manuellement la WRAM:

```lua
-- Scanner pour trouver une valeur spécifique dans WRAM
function scanWRAM(value, size)
  local start = 0x02000000
  local end_addr = 0x0203FFFF
  local results = {}

  print(string.format("Scanning WRAM for value: %d (0x%04X)", value, value))

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
    if i <= 20 then -- Limiter l'affichage
      print(string.format("  0x%08X", addr))
    end
  end

  if #results > 20 then
    print(string.format("  ... and %d more", #results - 20))
  end

  return results
end

-- Exemple d'utilisation:
-- 1. Regarder votre coordonnée X dans le jeu (ex: 10)
-- 2. Scanner: local results = scanWRAM(10, 2)
-- 3. Se déplacer à X=15
-- 4. Rescanner: local results2 = scanWRAM(15, 2)
-- 5. Comparer les résultats pour trouver l'adresse correcte
```

**Procédure de scan itératif:**
1. Noter votre position X actuelle (visible in-game)
2. Scanner cette valeur
3. Se déplacer (X change)
4. Rescanner la nouvelle valeur
5. Comparer les listes de résultats
6. Répéter jusqu'à avoir 1-3 candidats
7. Tester chaque candidat en marchant

### Phase 3: Identifier si Pointeurs Dynamiques

Si les offsets changent entre sessions (fermer/rouvrir mGBA), c'est probablement dynamique.

**Test de persistance:**
```lua
-- Tester si une adresse est persistante
local test_addr = 0x02024844 -- adresse candidate

-- Session 1: noter la valeur
local value1 = memory.read16(test_addr)
print("Value:", value1)

-- Fermer mGBA, rouvrir, charger la save, relancer le script
-- Si la valeur est complètement différente/garbage → adresse dynamique
```

**Si dynamique, chercher SaveBlock1 pointer:**

Dans Pokémon Émeraude vanilla, les pointeurs SaveBlock sont dans IWRAM (0x03000000+):
- SaveBlock1Ptr: `0x03005D8C`
- SaveBlock2Ptr: `0x03005DA0` (R&B shifted from vanilla 0x03005D90)

```lua
-- Chercher SaveBlock1 pointer
function findSaveBlockPointers()
  local iwram_start = 0x03000000
  local iwram_end = 0x03007FFF

  print("=== Searching for SaveBlock pointers in IWRAM ===")

  for addr = iwram_start, iwram_end, 4 do
    local ptr = memory.read32(addr)

    -- Un pointeur valide pointe vers WRAM
    if ptr >= 0x02000000 and ptr <= 0x0203FFFF then
      print(string.format("Potential pointer at 0x%08X -> 0x%08X", addr, ptr))
    end
  end
end

-- Exécuter
findSaveBlockPointers()
```

**Tester les candidats:**
```lua
-- Test d'un pointeur candidat
local ptr_addr = 0x03005D8C -- exemple
local sb1_ptr = memory.read32(ptr_addr)

print(string.format("SaveBlock1 pointer: 0x%08X", sb1_ptr))
print("Is valid WRAM?", sb1_ptr >= 0x02000000 and sb1_ptr <= 0x0203FFFF)

-- Dumper les premiers bytes de la structure pointée
print("\n=== Dumping structure ===")
for offset = 0, 0x100, 2 do
  local value = memory.read16(sb1_ptr + offset)
  print(string.format("Offset +0x%04X: %5d (0x%04X)", offset, value, value))
end

-- Chercher visuellement vos coordonnées dans ce dump
```

## Script de Scan Automatique

Utilitaire pour tracker les changements:

```lua
-- Tracker les adresses qui changent quand vous bougez
function trackChanges(startAddr, endAddr, frames)
  local snapshots = {}

  print(string.format("Taking %d snapshots...", frames))

  for frame = 1, frames do
    emu.frameadvance()
    local snapshot = {}

    for addr = startAddr, endAddr, 2 do
      snapshot[addr] = memory.read16(addr)
    end

    table.insert(snapshots, snapshot)

    if frame % 10 == 0 then
      print(string.format("  Snapshot %d/%d", frame, frames))
    end
  end

  print("\nAnalyzing changes...")
  local changed_addrs = {}

  for addr = startAddr, endAddr, 2 do
    local values = {}
    for i = 1, #snapshots do
      table.insert(values, snapshots[i][addr])
    end

    -- Vérifier si les valeurs ont changé
    local first = values[1]
    local changed = false
    for i = 2, #values do
      if values[i] ~= first then
        changed = true
        break
      end
    end

    if changed then
      table.insert(changed_addrs, {addr = addr, values = values})
    end
  end

  print(string.format("\nFound %d addresses that changed:", #changed_addrs))
  for i = 1, math.min(50, #changed_addrs) do
    local entry = changed_addrs[i]
    print(string.format("  0x%08X: %d -> %d",
      entry.addr, entry.values[1], entry.values[#entry.values]))
  end
end

-- Utilisation: se déplacer pendant 60 frames
-- trackChanges(0x02020000, 0x02030000, 60)
```

## Implémentation dans le Code

### Si Offsets STATIQUES

Créer `config/run_and_bun.lua`:

```lua
return {
    name = "Pokemon Run and Bun",
    gameId = "BPRE", -- ou ID spécifique
    version = "v1.0",

    offsets = {
        -- Offsets trouvés via scan
        playerX = 0x0xxxxxxx,
        playerY = 0x0xxxxxxx,
        mapId = 0x0xxxxxxx,
        mapGroup = 0x0xxxxxxx,
        facing = 0x0xxxxxxx,

        -- Optionnels (à trouver plus tard)
        cameraX = nil,
        cameraY = nil,
        playerName = nil,
    },

    validation = {
        wramStart = 0x02000000,
        wramEnd = 0x0203FFFF,
        maxX = 1024,
        maxY = 1024
    }
}
```

### Si Offsets DYNAMIQUES (via pointeurs)

Modifier `config/run_and_bun.lua`:

```lua
return {
    name = "Pokemon Run and Bun",
    gameId = "BPRE",
    version = "v1.0",

    -- Mode dynamique activé
    useDynamicPointers = true,

    -- Pointeurs de base (dans IWRAM)
    pointers = {
        saveBlock1 = 0x03005D8C, -- ou autre adresse trouvée
    },

    -- Offsets relatifs aux pointeurs
    offsets = {
        -- Format: {pointer = "nom", offsets = {chain}}
        playerX = {pointer = "saveBlock1", offsets = {0x0000}},
        playerY = {pointer = "saveBlock1", offsets = {0x0002}},
        mapId = {pointer = "saveBlock1", offsets = {0x0004}},
        mapGroup = {pointer = "saveBlock1", offsets = {0x0005}},
    }
}
```

Modifier `hal.lua` pour supporter les deux modes:

```lua
function HAL.readPlayerX()
  if config.useDynamicPointers and config.offsets.playerX.pointer then
    -- Mode dynamique
    local basePtr = config.pointers[config.offsets.playerX.pointer]
    local addr = HAL.readSafePointer(basePtr, config.offsets.playerX.offsets)
    return safeRead(addr, 2)
  else
    -- Mode statique
    return safeRead(config.offsets.playerX, 2)
  end
end
```

## Validation des Offsets

Une fois les offsets trouvés, les valider:

```lua
-- Script de validation complète
function validateOffsets()
  print("=== Offset Validation ===\n")

  local x = memory.read16(0x0xxxxxxx) -- votre offset PlayerX
  local y = memory.read16(0x0xxxxxxx) -- votre offset PlayerY
  local mapId = memory.readByte(0x0xxxxxxx)
  local mapGroup = memory.readByte(0x0xxxxxxx)

  print(string.format("Position: X=%d Y=%d", x, y))
  print(string.format("Map: Group=%d ID=%d", mapGroup, mapId))

  -- Vérifier plages valides
  local valid = true

  if x > 1024 or y > 1024 then
    print("⚠️  WARNING: Coordinates out of expected range")
    valid = false
  end

  if mapGroup > 50 then
    print("⚠️  WARNING: MapGroup suspiciously high")
    valid = false
  end

  if valid then
    print("\n✅ All offsets appear valid!")
    print("Walk around and run this again to double-check.")
  else
    print("\n❌ Some offsets may be incorrect. Rescan needed.")
  end
end

validateOffsets()
```

## Structure Mémoire Attendue

Basé sur Émeraude vanilla (structure probable, PEUT ÊTRE DIFFÉRENTE):

```
Offset +0x00: MapGroup (1 byte)
Offset +0x01: MapID (1 byte)
Offset +0x02: PlayerX (2 bytes, little-endian)
Offset +0x04: PlayerY (2 bytes, little-endian)
Offset +0x06: Elevation? (1 byte)
Offset +0x08: FacingDirection (1 byte)
```

⚠️ Run & Bun peut avoir une structure complètement différente.

## Checklist de Scan

- [ ] Installer mGBA 0.10.0+
- [ ] Obtenir ROM Run & Bun (dernière version)
- [ ] Tester offsets Émeraude vanilla (Phase 1)
- [ ] Si échec: Scanner PlayerX avec script Lua
- [ ] Scanner PlayerY
- [ ] Scanner MapID et MapGroup
- [ ] Scanner FacingDirection
- [ ] Tester persistance (statique vs dynamique)
- [ ] Si dynamique: chercher pointeurs SaveBlock
- [ ] Créer config/run_and_bun.lua
- [ ] Valider avec script de validation
- [ ] Tester en jeu (marcher, changer de map)
- [ ] Documenter les offsets trouvés

## Outils de Debug

```lua
-- Afficher position en temps réel (overlay)
emu.registerafter(function()
  local x = memory.read16(0x0xxxxxxx)
  local y = memory.read16(0x0xxxxxxx)
  gui.text(10, 10, string.format("X:%d Y:%d", x, y))
end)
```

## Ressources

### Pour Run & Bun
- Discord/Forum de la communauté Run & Bun
- Documentation des offsets (si disponible)

### Outils
- mGBA 0.10.0+ avec console Lua
- Savestate mGBA pour tests rapides
- `gui.drawText()` pour affichage en temps réel

## Prochaines Étapes

1. **Trouver les 5 offsets de base** (X, Y, MapID, MapGroup, Facing)
2. **Créer config/run_and_bun.lua** avec les offsets
3. **Tester avec main.lua** pour validation en jeu
4. **Documenter** tout dans ce guide
5. **Commit** les offsets dans le repo

---

**Status:** Phase 1 - Scan prioritaire
**Dernière mise à jour:** 2026-02-02
