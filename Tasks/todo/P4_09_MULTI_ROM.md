# Phase 4 - Support Multi-ROM

> **Statut:** En attente (après Phase 3)
> **Type:** Feature — Profils ROM supplémentaires
> **Objectif:** Ajouter support pour Pokémon Radical Red, Unbound, et autres ROM hacks basés sur moteur Gen 3.

---

## Vue d'ensemble

Créer des profils de configuration pour différentes ROMs en recherchant leurs offsets mémoire spécifiques.

**ROMs à supporter:**
1. Pokémon Radical Red (base FireRed)
2. Pokémon Unbound (base FireRed)
3. ~~Pokémon Run & Bun~~ → **Déplacé vers PHASE0_MEMORY_OFFSET_DISCOVERY.md** (priorité absolue)

**Note importante:** Les ROM hacks modifient souvent la structure mémoire. Les offsets FireRed standard ne fonctionneront probablement PAS directement. Utiliser la même méthodologie que Phase 0 (voir `docs/MEMORY_SCANNING_GUIDE.md`).

---

## Méthodologie

### Recherche d'offsets

- [ ] **1.1** Pour chaque ROM, utiliser Cheat Engine:
  1. Lancer ROM dans mGBA
  2. Chercher PlayerX (valeur 2 bytes)
  3. Se déplacer, Next Scan
  4. Répéter jusqu'à trouver adresse stable
  5. Même processus pour PlayerY, MapID, etc.

- [ ] **1.2** Valider avec script test Lua

### Créer profils

- [ ] **2.1** Créer `config/radical_red.lua`:
  ```lua
  return {
    name = "Pokémon Radical Red",
    gameId = "BPRE",  -- FireRed base
    version = "3.0",
    description = "ROM hack by Soupercell",

    offsets = {
      playerX = 0x02????,  -- À trouver
      playerY = 0x02????,
      -- etc.
    }
  }
  ```

- [ ] **2.2** Créer `config/unbound.lua`

### Auto-détection ROM

- [ ] **3.1** Améliorer `detectROM()` dans `main.lua` (ligne 59):

  ```lua
  local function detectROM()
    -- Lire game code (0x080000AC)
    local code = readGameCode()

    -- Lire game title (0x080000A0)
    local title = readGameTitle()

    -- Map vers config
    local configMap = {
      ["BPEE"] = "emerald_us",
      ["BPRE"] = "fire_red",  -- Ou radical_red si détecté
      ["BPGE"] = "leaf_green",
      ["AXVE"] = "ruby",
      ["AXPE"] = "sapphire"
    }

    -- Charger config correspondant
    local configName = configMap[code]
    if configName then
      return require("config." .. configName)
    end

    return nil
  end
  ```

- [ ] **3.2** Détection ROM hacks spécifiques:
  - Lire titre ROM (peut contenir "RadicalRed", "Unbound", etc.)
  - Comparer checksums ROM

---

## Tests

- [ ] **Test 1:** Radical Red détecté et config chargée
- [ ] **Test 2:** Positions lues correctement sur Radical Red
- [ ] **Test 3:** Idem pour Unbound
- [ ] **Test 4:** Multi-ROM dans même room (mix Run & Bun + Radical Red + Unbound)

---

## Fichiers à créer

| Fichier | Description |
|---------|-------------|
| `config/radical_red.lua` | Profil Radical Red |
| `config/unbound.lua` | Profil Unbound |

## Fichiers à modifier

| Fichier | Modifications |
|---------|--------------|
| `client/main.lua:59-79` | Améliorer detectROM() avec auto-sélection config |

---

## Notes

**Run & Bun:** Maintenant géré dans **PHASE0_MEMORY_OFFSET_DISCOVERY.md** (priorité absolue avant même Phase 1).

Pour Radical Red et Unbound, utiliser la même méthodologie que Phase 0:
1. Tester offsets FireRed vanilla
2. Si échec, scanner avec debugger Lua mGBA
3. Identifier type (statique/dynamique)
4. Créer profil config
5. Tester et valider

**Référence:** `docs/MEMORY_SCANNING_GUIDE.md`

---

## Prochaine étape

Après cette tâche → **PHASE5_DOCUMENTATION.md**
