# Scanner les adresses battle manquantes pour Run & Bun

> **Statut:** Completed (2026-02-05)
> **Type:** Update — Scripts de scan memoire pour PvP
> **Priorite:** P0 - CRITIQUE (prerequis pour P3_10B)
> **Prerequis:** Aucun
> **Date creation:** 2026-02-05

---

## Vue d'ensemble

Le systeme de combat PvP a 5 adresses manquantes dans `config/run_and_bun.lua` (lignes 55-69).
De plus, l'adresse `gMainInBattle = 0x020233E0` est **FAUSSE** (elle tombe dans `gPlayerParty` a offset +0x10).

Les scanners existants (`scripts/scanners/scan_battle_*.lua`) ont des bugs:
- `scan_battle_remaining.lua:17` utilise `gMainInBattle = 0x020233E0` (faux)
- `scan_battle_outcome.lua:68` utilise la meme adresse fausse
- Aucun script n'existe pour trouver les callbacks ROM (CB2_InitBattle etc.)

### Adresses manquantes

| Variable | Type | Region | Necessite pour |
|----------|------|--------|---------------|
| `CB2_InitBattle` | ROM function pointer | ROM (0x08xxxxxx) | Declencher le combat PvP |
| `gBattleOutcome` | u8 | EWRAM | Detecter win/lose/flee |
| `gTrainerBattleOpponent_A` | u16 | EWRAM | Preserver gEnemyParty |
| `CB2_ReturnToField` | ROM function pointer | ROM (0x08xxxxxx) | Retour post-combat |
| `CB2_WhiteOut` | ROM function pointer | ROM (0x08xxxxxx) | Intercepter defaite |

### Adresse a corriger

| Variable | Adresse actuelle (FAUSSE) | Adresse correcte | Calcul |
|----------|--------------------------|-------------------|--------|
| `gMainInBattle` | `0x020233E0` | `0x0202067F` | `callback2Addr(0x0202064C) - 4 + 0x37` |

**Pourquoi 0x020233E0 est faux:**
- `gPlayerParty = 0x020233D0` (confirme fonctionnel)
- `0x020233E0 - 0x020233D0 = 0x10` → c'est l'offset +16 dans le premier Pokemon (dans `otId`)
- Le byte a cette adresse est souvent 0 → `isFinished()` retourne true immediatement

**Pourquoi 0x0202067F est correct:**
- `gMain.callback2 = 0x0202064C` (confirme fonctionnel, `client/hal.lua:618`)
- `gMain` struct layout (`hal.lua:506-527`): callback2 est a offset +0x04
- Donc `gMain base = 0x0202064C - 0x04 = 0x02020648`
- `gMain.inBattle` est a offset +0x37 (`hal.lua:527`)
- Donc `gMainInBattle = 0x02020648 + 0x37 = 0x0202067F`

---

## Implementation

### Section 1 — Script de verification gMain (verify_gmain.lua)

**Fichier a creer:** `scripts/scanners/verify_gmain.lua`

**Objectif:** Verifier que `gMain.inBattle` est bien a `0x0202067F` et pas a `0x020233E0`

**Methode:**
1. Lire `gMain.callback2` a `0x0202064C` (doit etre une adresse ROM 0x08xxxxxx)
2. Calculer `gMain base = callback2Addr - 4`
3. Lire les champs de gMain et les afficher:
   - `+0x00` callback1 (4 bytes)
   - `+0x04` callback2 (4 bytes) — doit matcher `0x0202064C`
   - `+0x08` savedCallback (4 bytes)
   - `+0x35` state (1 byte)
   - `+0x37` inBattle (1 byte)
4. Comparer la valeur de `inBattle` entre les deux candidats:
   - Pendant un combat: `0x0202067F` doit etre 1, `0x020233E0` peut etre n'importe quoi
   - Hors combat: `0x0202067F` doit etre 0

**API mGBA a utiliser:**
- `emu.memory.wram:read8(offset)` (EWRAM, `hal.lua:72`)
- `emu.memory.wram:read32(offset)` (EWRAM, `hal.lua:76`)
- `callbacks:add("frame", tick_function)` (`scan_battle_remaining.lua:231`)
- `callbacks:remove(cbId)` (`scan_battle_remaining.lua:213`)

**Details:**
```
Adresses connues:
  gMain.callback2 = 0x0202064C → WRAM offset 0x2064C
  gMain base      = 0x02020648 → WRAM offset 0x20648

Champs a lire:
  gMain.callback1     = WRAM offset 0x20648 + 0x00 = 0x20648
  gMain.callback2     = WRAM offset 0x20648 + 0x04 = 0x2064C (verification)
  gMain.savedCallback = WRAM offset 0x20648 + 0x08 = 0x20650
  gMain.state         = WRAM offset 0x20648 + 0x35 = 0x2067D
  gMain.inBattle      = WRAM offset 0x20648 + 0x37 = 0x2067F

Adresse fausse:
  0x020233E0           = WRAM offset 0x233E0
```

---

### Section 2 — Script de capture callbacks ROM (scan_battle_callbacks.lua)

**Fichier a creer:** `scripts/scanners/scan_battle_callbacks.lua`

**Objectif:** Trouver CB2_InitBattle, CB2_ReturnToField, et potentiellement CB2_WhiteOut via watchpoint sur `gMain.callback2`

**Methode — Watchpoint flag-based (meme pattern que `hal.lua:606-636`):**

1. **Setup:**
   - Poser un watchpoint WRITE_CHANGE sur `gMain.callback2` (`0x0202064C`)
   - Dans le callback watchpoint: juste setter un flag (pas de memory access — crash risk, `hal.lua:622-623`)
   - Chaque frame: verifier le flag et lire callback2 + inBattle

2. **Auto-detection:**
   - Tracker `prevInBattle` chaque frame
   - Quand `inBattle` passe de 0 a 1:
     - Lire `callback2` → c'est `CB2_InitBattle`
     - Log l'adresse trouvee
   - Quand `inBattle` passe de 1 a 0:
     - Lire `callback2` → c'est `CB2_ReturnToField` (ou CB2_EndTrainerBattle etc.)
     - Log l'adresse trouvee
   - Aussi logger TOUTES les valeurs uniques de callback2 observees (utile pour debug)

3. **Instructions utilisateur:**
   - "Entrez dans un combat (herbes, dresseur)"
   - "Gagnez ou fuyez le combat"
   - "Les adresses seront detectees automatiquement"

**API mGBA a utiliser:**
- `emu:setWatchpoint(callback, addr, C.WATCHPOINT_TYPE.WRITE_CHANGE)` (`hal.lua:621-624`)
- `emu:clearBreakpoint(emu, wpId)` (`hal.lua:614`)
- `emu.memory.wram:read32(offset)` pour callback2 (`hal.lua:569-570`)
- `emu.memory.wram:read8(offset)` pour inBattle
- `callbacks:add("frame", tick)` pour le polling frame-by-frame

**Constantes connues (pour filtrage):**
```
CB2_LoadMap    = 0x08007441  (config/run_and_bun.lua:32)
CB2_Overworld  = 0x080A89A5  (config/run_and_bun.lua:33)
callback2Addr  = 0x0202064C  (config/run_and_bun.lua:31)
inBattle addr  = 0x0202067F  (derive, a verifier avec Section 1)
```

**Sortie attendue:**
```
[SCAN] CB2_InitBattle FOUND: 0x08XXXXXX (inBattle: 0 -> 1)
[SCAN] CB2_ReturnToField FOUND: 0x08XXXXXX (inBattle: 1 -> 0)
```

---

### Section 3 — Scanner gBattleOutcome ameliore (fix scan_battle_outcome.lua)

**Fichier a modifier:** `scripts/scanners/scan_battle_outcome.lua`

**Probleme actuel:** Utilise `gMainInBattle = 0x020233E0` (ligne 68) qui est faux.

**Fix:**
1. Changer ligne 68: `local gMainInBattle = 0x0202067F` (adresse derivee correcte)
2. La fonction `isInBattle()` (lignes 70-73) lira la bonne valeur
3. Tout le reste du script fonctionnera correctement (les transitions battle/hors-battle seront detectees)

**Ameliorations optionnelles:**
- Ajouter la methode scan large (full EWRAM scan de 0 avant combat → rescan pour 1/2/7 apres)
- L'actuel ne teste que des predictions locales (lignes 20-54)

---

### Section 4 — Fix scan_battle_remaining.lua

**Fichier a modifier:** `scripts/scanners/scan_battle_remaining.lua`

**Probleme:** Ligne 17: `gMainInBattle = 0x020233E0`

**Fix:** Changer en `gMainInBattle = 0x0202067F`

---

### Section 5 — Scanner gTrainerBattleOpponent_A

**Methode recommandee (a ajouter dans scan_battle_addresses.lua):**

Le scanner existant (`scripts/scanners/scan_battle_addresses.lua`) n'a pas d'etape pour `gTrainerBattleOpponent_A`.

**Ajouter les etapes suivantes:**

```
=== STEP 7: Find gTrainerBattleOpponent_A ===
  a) Enter a TRAINER battle (note le trainer ID si possible)
  b) Execute: top = scan16(TRAINER_ID)
     Si ID inconnu, utiliser prediction:
     Vanilla: 0x02038BCA, delta +0x878 → 0x02039442
  c) Flee/win the battle
  d) Execute: top = rescan(top, 0, 2)
  e) Execute: show(top, 'gTrainerBattleOpponent_A')
```

**Alternative:** Utiliser `predictRB(0x02038BCA)` (`scan_battle_addresses.lua:200-206`) et verifier manuellement avec `peek()`.

---

## Fichiers a creer

| Fichier | Description |
|---------|-------------|
| `scripts/scanners/verify_gmain.lua` | Verification gMain struct + inBattle corrige |
| `scripts/scanners/scan_battle_callbacks.lua` | Auto-detection CB2_InitBattle/CB2_ReturnToField via watchpoint |

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `scripts/scanners/scan_battle_outcome.lua:68` | `gMainInBattle`: `0x020233E0` → `0x0202067F` |
| `scripts/scanners/scan_battle_remaining.lua:17` | `gMainInBattle`: `0x020233E0` → `0x0202067F` |
| `scripts/scanners/scan_battle_addresses.lua` | Ajouter STEP 7 pour gTrainerBattleOpponent_A |
| `config/run_and_bun.lua:61` | `gMainInBattle`: `0x020233E0` → `0x0202067F` |

---

## Ordre d'execution recommande

1. **verify_gmain.lua** — Confirmer que 0x0202067F est la bonne adresse
2. **Fix les scanners existants** — Corriger gMainInBattle dans les 2 scripts + config
3. **scan_battle_callbacks.lua** — Trouver CB2_InitBattle (entrer dans un combat)
4. **scan_battle_outcome.lua** (corrige) — Trouver gBattleOutcome (gagner un combat)
5. **scan_battle_addresses.lua** (STEP 7) — Trouver gTrainerBattleOpponent_A
6. **Mettre a jour config/run_and_bun.lua** avec toutes les adresses trouvees

---

## Test plan

- [ ] Charger verify_gmain.lua → confirmer inBattle=0 hors combat, inBattle=1 en combat a 0x0202067F
- [ ] Charger scan_battle_callbacks.lua → entrer en combat → CB2_InitBattle detecte
- [ ] Gagner le combat → CB2_ReturnToField detecte
- [ ] Charger scan_battle_outcome.lua (corrige) → gagner un combat → gBattleOutcome detecte
- [ ] Verifier prediction gTrainerBattleOpponent_A avec peek(0x02039442, 2) pendant un combat
- [ ] Toutes les adresses remplies dans config/run_and_bun.lua
