# Duel PvP System — Vrai combat joueur contre joueur

> **Statut:** Partial (code structure complete, awaiting address scan)
> **Type:** Feature majeure — systeme de combat PvP complet
> **Priorite:** Haute
> **Prerequis:** P3_09A_WARP_MECHANISM_FIX.md (warp fonctionnel via save state hijack)
> **Date implementation:** 2026-02-05

---

## Implementation Status

### Completed (2026-02-05)
- [x] Created `scripts/scan_battle_addresses.lua` — memory scanner for battle addresses
- [x] Created `client/battle.lua` — PvP battle module with:
  - Party reading (readLocalParty)
  - Party injection (injectEnemyParty)
  - Battle triggering (startBattle with BATTLE_TYPE_SECRET_BASE)
  - AI interception (tick, injectRemoteChoice)
  - Choice capture (captureLocalChoice, hasPlayerChosen)
  - RNG sync (readRng, writeRng, onRngSync)
  - Outcome detection (isFinished, getOutcome)
- [x] Updated `config/run_and_bun.lua` — added battle section with placeholder addresses
- [x] Updated `server/server.js` — added handlers for:
  - duel_party (party data relay)
  - duel_choice (battle choice relay)
  - duel_rng_sync (RNG synchronization)
  - duel_end (battle completion)
  - duelOpponent tracking for message routing
- [x] Updated `client/main.lua` — integrated battle module with:
  - New warp phases: waiting_party, in_battle, returning, loading_return
  - Origin position saving for return after battle
  - Party exchange after warp completes
  - Battle tick every frame
  - Choice capture and sending
  - Remote choice timeout handling
  - Return to origin after battle ends

### Pending (requires manual work)
- [ ] **Run scanner to find actual battle addresses** — load scan_battle_addresses.lua in mGBA
- [ ] **Fill addresses in config/run_and_bun.lua** — update battle section with found addresses
- [ ] Test party exchange and injection
- [ ] Test battle trigger
- [ ] Test AI choice interception
- [ ] Test RNG synchronization
- [ ] Test battle completion and return
- [ ] Test disconnect during battle

---

## Vision utilisateur

**Experience souhaitee:**
1. Joueur A appuie sur A pres du ghost de Joueur B
2. Joueur B voit un prompt "Duel?" et accepte
3. Les deux joueurs sont teleportes dans une salle de duel
4. Un **vrai combat PvP** commence — chaque joueur controle ses propres Pokemon
5. Le combat se deroule comme un link battle classique
6. A la fin, les deux joueurs retournent a leur position d'origine

**Ce qui est deja fait:**
- Trigger de duel (proximity + A button)
- UI de request/accept/decline
- Warp vers une salle (save state hijack)

**Ce qui manque:**
- Declenchement du combat
- Synchronisation des equipes
- Controle PvP reel (pas une IA)
- Detection fin de combat
- Retour a l'origine

---

## Analyse technique : Pourquoi le Link Cable ne marche pas

### Le probleme fondamental

Le Link Cable GBA utilise le protocole SIO (Serial I/O) avec synchronisation frame-perfect:
- `SendBlock()` / `GetBlockReceivedStatus()` pour echanger des donnees
- `GetMultiplayerId()` pour determiner master/slave
- Lockstep parfait entre les deux GBA

**mGBA supporte le link cable** mais uniquement via son systeme `MultiplayerController` en C++.
**Ce n'est PAS expose via l'API Lua** — on ne peut pas controler SIO depuis un script.

Les projets comme `mgba-online` ont du **forker mGBA en C++** pour ajouter le support reseau.

### La solution : Dual Parallel Battle

Au lieu de simuler un link cable, on fait tourner **deux combats reels en parallele**:

```
Machine Joueur A                    Serveur                   Machine Joueur B
─────────────────                   ───────                   ─────────────────
Combat REEL contre                  Relaye                    Combat REEL contre
l'equipe de B                       choix + RNG               l'equipe de A
       │                                                            │
Joueur A choisit                                              Joueur B choisit
son move normalement                                          son move normalement
       │                                                            │
       └──────────────────→ ECHANGE ←──────────────────────────────┘
       │                                                            │
L'IA de "B" est                                               L'IA de "A" est
REMPLACEE par le                                              REMPLACEE par le
vrai choix de B                                               vrai choix de A
       │                                                            │
       └──────────────────→ SYNC RNG ←─────────────────────────────┘
       │                                                            │
Tour s'execute                                                Tour s'execute
RESULTATS IDENTIQUES ←──────────────────────────────────────→ RESULTATS IDENTIQUES
```

Chaque joueur:
1. Combat contre l'equipe **reelle** de l'autre joueur
2. Controle ses **propres** Pokemon normalement
3. Voit les **vrais choix** de l'adversaire (pas une IA)
4. Obtient les **memes resultats** grace a la synchronisation RNG

---

## Architecture technique detaillee

### 1. Le moteur de combat Pokemon (comment ca marche)

#### Systeme de controlleurs

Chaque "battler" (participant au combat) a un **controlleur** qui gere ses decisions:
- `PlayerBufferRunCommand` — joueur humain (affiche UI, attend input)
- `OpponentBufferRunCommand` — IA adversaire (calcule et decide instantanement)

Les controlleurs communiquent via des buffers:
- `gBattleBufferA[battler]` — commandes du moteur vers le controlleur
- `gBattleBufferB[battler]` — reponses du controlleur vers le moteur

#### Execution synchronisee

Le moteur attend que **tous** les battlers aient decide avant d'executer le tour:
```c
// Tant que gBattleControllerExecFlags != 0, le moteur attend
if (gBattleControllerExecFlags)
    return;  // Ne pas avancer
```

Chaque controlleur clear son bit quand il a fini:
```c
gBattleControllerExecFlags &= ~gBitTable[gActiveBattler];
```

#### Notre strategie d'interception

1. L'IA adversaire decide en **1 frame** et clear son bit
2. On **remet le bit a 1** immediatement → le moteur attend
3. On attend le choix du joueur distant via le reseau
4. On **ecrit le vrai choix** dans `gBattleBufferB[opponent]`
5. On clear le bit → le tour s'execute avec le vrai choix

C'est le **meme mecanisme** que les link battles utilisent pour attendre l'autre joueur!

### 2. Determinisme et synchronisation RNG

#### Le moteur est 100% deterministe

Meme seed RNG + memes inputs = memes resultats. C'est prouve par:
- Le systeme de **Recorded Battle** (replay parfait avec juste seed + inputs)
- Les **link battles** (deux GBA avec meme seed = memes degats/crits)

#### Variable RNG

| Variable | Adresse (vanilla) | Region | Description |
|----------|-------------------|--------|-------------|
| `gRngValue` | 0x03005D80 | IWRAM | Seed RNG principale (32 bits) |

Algorithme LCG: `seed = seed * 0x41C64E6D + 0x6073`

#### Protocole de synchronisation

1. Au debut du combat, le **master** (initiateur du duel) envoie sa `gRngValue`
2. Le **slave** ecrit cette valeur dans sa propre `gRngValue`
3. **A chaque tour**, avant execution, le master renvoie sa `gRngValue` actuelle
4. Les deux machines ont le meme RNG → memes jets de degats, crits, accuracy

#### Flag BATTLE_TYPE_LINK

Si on set `BATTLE_TYPE_LINK` (bit 1) dans `gBattleTypeFlags`:
```c
// Dans VBlankCB_Battle():
if (!(gBattleTypeFlags & BATTLE_TYPE_LINK))
    Random();  // Advance RNG each VBlank
```
Le RNG **n'avance plus automatiquement** entre les frames → pas de derive.

### 3. Adresses memoire (a scanner pour Run & Bun)

#### Adresses connues (vanilla Emerald US — reference)

| Variable | Adresse | Taille | Description |
|----------|---------|--------|-------------|
| `gMain` | 0x030022C0 | struct | Structure principale (IWRAM) |
| `gMain.callback1` | gMain + 0x00 | 4 | Callback principal 1 |
| `gMain.callback2` | gMain + 0x04 | 4 | Callback principal 2 |
| `gMain.savedCallback` | gMain + 0x08 | 4 | Callback de retour post-combat |
| `gMain.state` | gMain + 0x35 | 1 | Etat de la state machine |
| `gMain.inBattle` | gMain + 0x37 | 1 | 1 = en combat, 0 = hors combat |
| `gPlayerParty` | 0x020244EC | 600 | Equipe du joueur (6 x 100 octets) |
| `gEnemyParty` | 0x02024744 | 600 | Equipe adverse (6 x 100 octets) |
| `gBattleTypeFlags` | 0x02022FEC | 4 | Flags de type de combat |
| `gTrainerBattleOpponent_A` | 0x02038BCA | 2 | ID du trainer adverse |
| `gBattleControllerExecFlags` | 0x02024068 | 4 | Bits d'execution des controlleurs |
| `gBattleBufferA` | 0x02023064 | 2048 | Buffer commandes (4 x 512) |
| `gBattleBufferB` | 0x02023864 | 2048 | Buffer reponses (4 x 512) |
| `gBattleCommunication` | 0x02024332 | 8 | Communication inter-systeme |
| `gActiveBattler` | 0x02024064 | 1 | Battler actif actuel |
| `gBattlersCount` | 0x0202406C | 1 | Nombre de battlers (2 ou 4) |
| `gChosenMoveByBattler` | 0x02024274 | 8 | Move ID choisi par battler |
| `gBattleOutcome` | a scanner | 1 | Resultat (1=win, 2=lose, 7=flee) |
| `gRngValue` | 0x03005D80 | 4 | Seed RNG (IWRAM) |

#### Adresses deja trouvees pour Run & Bun

| Variable | Adresse R&B | Source |
|----------|-------------|--------|
| `gMain.callback2` | 0x0202064C | config/run_and_bun.lua |
| `CB2_LoadMap` | 0x08007441 | config/run_and_bun.lua |
| `CB2_Overworld` | 0x080A89A5 | config/run_and_bun.lua |
| `playerX/Y` | 0x02024CBC/BE | config/run_and_bun.lua |
| `mapGroup/Id` | 0x02024CC0/C1 | config/run_and_bun.lua |
| Camera offsets | 0x03005DFC/DF8 | config/run_and_bun.lua (IWRAM, unchanged) |

#### Delta observe

PlayerX vanilla (0x02024844) vs R&B (0x02024CBC) = **+0x878**

Prediction: les variables battle sont probablement decalees de ~0x878 aussi.
Mais certaines (comme facing a +0x120EC) different beaucoup → scan obligatoire.

### 4. Structures de donnees Pokemon

#### Pokemon struct (100 octets par Pokemon)

```
Offset  Taille  Champ
------  ------  -----
0x00    4       Personality Value
0x04    4       OT ID
0x08    10      Nickname
0x12    1       Language
0x13    1       Flags (isBadEgg, hasSpecies, isEgg)
0x14    7       OT Name
0x1B    1       Markings
0x1C    2       Checksum
0x1E    2       Padding
0x20    48      Encrypted Data (4 substructures x 12 bytes)
0x50    4       Status Condition
0x54    1       Level
0x55    1       Mail ID
0x56    2       Current HP ← utile pour scanner
0x58    2       Max HP
0x5A    2       Attack
0x5C    2       Defense
0x5E    2       Speed
0x60    2       Sp. Attack
0x62    2       Sp. Defense
```

**Total**: 100 octets (0x64) par Pokemon, **600 octets** pour l'equipe complete.

**Note**: Les donnees aux offsets 0x20-0x4F sont **chiffrees** avec `personality XOR otId`.
Mais on copie les octets bruts de `gPlayerParty` → deja chiffres et valides!

### 5. BATTLE_TYPE flags

| Flag | Bit | Valeur | Description |
|------|-----|--------|-------------|
| `BATTLE_TYPE_DOUBLE` | 0 | 0x00000001 | Combat double |
| `BATTLE_TYPE_LINK` | 1 | 0x00000002 | Link battle (desactive idle RNG) |
| `BATTLE_TYPE_IS_MASTER` | 2 | 0x00000004 | Ce joueur est le master |
| `BATTLE_TYPE_TRAINER` | 3 | 0x00000008 | Combat trainer (pas wild) |
| `BATTLE_TYPE_FIRST_BATTLE` | 4 | 0x00000010 | Premier combat (tutorial) |
| `BATTLE_TYPE_RECORDED` | 24 | 0x01000000 | Combat enregistre |
| `BATTLE_TYPE_SECRET_BASE` | 27 | 0x08000000 | Combat base secrete |

**Configuration recommandee pour le duel:**
```
gBattleTypeFlags = BATTLE_TYPE_TRAINER | BATTLE_TYPE_SECRET_BASE
                 = 0x08 | 0x08000000
                 = 0x08000008
```

Pourquoi `SECRET_BASE`:
- `CreateNPCTrainerParty()` **n'ecrase pas** `gEnemyParty` pour ce type
- Post-combat propre: pas de whiteout, pas de perte d'argent

### 6. TRAINER_SECRET_BASE

```c
#define TRAINER_SECRET_BASE  1024
```

Quand `gTrainerBattleOpponent_A == 1024`:
```c
// Dans CreateNPCTrainerParty():
if (trainerNum == TRAINER_SECRET_BASE)
    return 0;  // Sort immediatement — gEnemyParty preserve!
```

C'est exactement ce qu'on veut: on pre-ecrit l'equipe adverse, et le jeu ne l'ecrase pas.

---

## Plan d'implementation

### Phase 1: Scanner les adresses battle pour Run & Bun

**Objectif:** Trouver toutes les adresses memoire necessaires.

#### 1.1 Creer le script de scan

**Fichier:** `scripts/scan_battle_addresses.lua`

```lua
--[[
  Battle Address Scanner pour Run & Bun

  USAGE:
  1. Charger le script dans mGBA
  2. Suivre les instructions dans la console
  3. Les adresses trouvees seront affichees
]]

local EWRAM_START = 0x02000000
local EWRAM_SIZE = 0x40000

-- Resultats du scan
local results = {}

-- Scan EWRAM pour une valeur 32-bit
function scan32(target)
  local matches = {}
  for offset = 0, EWRAM_SIZE - 4, 4 do
    local ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  return matches
end

-- Scan EWRAM pour une valeur 16-bit
function scan16(target)
  local matches = {}
  for offset = 0, EWRAM_SIZE - 2, 2 do
    local ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  return matches
end

-- Scan EWRAM pour une valeur 8-bit
function scan8(target)
  local matches = {}
  for offset = 0, EWRAM_SIZE - 1 do
    local ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    if ok and val == target then
      matches[#matches + 1] = EWRAM_START + offset
    end
  end
  return matches
end

-- Rescan: garde seulement les adresses qui matchent la nouvelle valeur
function rescan(candidates, target, size)
  local kept = {}
  for _, addr in ipairs(candidates) do
    local offset = addr - EWRAM_START
    local ok, val
    if size == 1 then
      ok, val = pcall(emu.memory.wram.read8, emu.memory.wram, offset)
    elseif size == 2 then
      ok, val = pcall(emu.memory.wram.read16, emu.memory.wram, offset)
    else
      ok, val = pcall(emu.memory.wram.read32, emu.memory.wram, offset)
    end
    if ok and val == target then
      kept[#kept + 1] = addr
    end
  end
  return kept
end

-- Afficher les resultats
function show(candidates, name)
  console:log(string.format("=== %s: %d match(es) ===", name, #candidates))
  for i, addr in ipairs(candidates) do
    if i <= 10 then
      console:log(string.format("  0x%08X", addr))
    end
  end
  if #candidates > 10 then
    console:log(string.format("  ... et %d de plus", #candidates - 10))
  end
end

-- Exposer les fonctions globalement
_G.scan32 = scan32
_G.scan16 = scan16
_G.scan8 = scan8
_G.rescan = rescan
_G.show = show
_G.results = results

console:log("==============================================")
console:log("Battle Address Scanner charge!")
console:log("==============================================")
console:log("")
console:log("ETAPE 1: Trouver gBattleTypeFlags")
console:log("  a) Entre dans un combat TRAINER")
console:log("  b) Execute: btf = scan32(0x8)")
console:log("  c) Fuis ou gagne le combat")
console:log("  d) Execute: btf = rescan(btf, 0, 4)")
console:log("  e) Execute: show(btf, 'gBattleTypeFlags')")
console:log("")
console:log("ETAPE 2: Trouver gEnemyParty (via HP)")
console:log("  a) Entre en combat, note les HP de l'adversaire (ex: 45)")
console:log("  b) Execute: hp = scan16(45)")
console:log("  c) Attaque pour changer les HP (ex: 32)")
console:log("  d) Execute: hp = rescan(hp, 32, 2)")
console:log("  e) Execute: show(hp, 'EnemyHP')")
console:log("  f) gEnemyParty = adresse trouvee - 0x56")
console:log("")
console:log("ETAPE 3: Trouver gBattleControllerExecFlags")
console:log("  a) Pendant le combat, au moment de choisir un move")
console:log("  b) Execute: ef = scan32(0x3) -- les deux battlers pending")
console:log("  c) Choisis un move, attends que l'adversaire agisse")
console:log("  d) Execute: ef = rescan(ef, 0, 4) -- tout est fini")
console:log("  e) Execute: show(ef, 'gBattleControllerExecFlags')")
console:log("")
console:log("ETAPE 4: Trouver gMain.inBattle")
console:log("  a) Pendant un combat: ib = scan8(1)")
console:log("  b) Hors combat: ib = rescan(ib, 0, 1)")
console:log("  c) show(ib, 'inBattle')")
console:log("")
```

#### 1.2 Executer le scan et documenter

Executer le script dans mGBA pendant differentes phases de jeu.
Documenter les adresses trouvees dans `config/run_and_bun.lua`.

#### 1.3 Trouver les pointeurs de fonction ROM

**CB2_InitBattle**:
- Mettre un watchpoint sur `gMain.callback2`
- Entrer en combat trainer
- Noter la valeur ecrite (adresse ROM 0x08XXXXXX)

**CB2_ReturnToFieldContinueScriptPlayMapMusic**:
- Noter callback2 juste apres la fin d'un combat

---

### Phase 2: Implementer le module battle.lua

**Fichier:** `client/battle.lua`

#### 2.1 Structure du module

```lua
--[[
  Battle Module — Gestion des combats PvP

  Gere:
  - Injection de l'equipe adverse
  - Declenchement du combat
  - Interception des choix IA
  - Synchronisation RNG
  - Detection de fin de combat
]]

local Battle = {}

-- Configuration (a remplir apres scan)
local ADDRESSES = {
  gMain = 0x030022C0,           -- A VERIFIER pour R&B
  gMainCallback2 = 0x0202064C,  -- Deja connu
  gMainInBattle = nil,          -- gMain + 0x37, a calculer
  gMainSavedCallback = nil,     -- gMain + 0x08
  gMainState = nil,             -- gMain + 0x35

  gPlayerParty = nil,           -- A scanner
  gEnemyParty = nil,            -- A scanner
  gBattleTypeFlags = nil,       -- A scanner
  gTrainerBattleOpponent_A = nil, -- A scanner
  gBattleControllerExecFlags = nil, -- A scanner
  gBattleBufferB = nil,         -- A scanner
  gBattleOutcome = nil,         -- A scanner
  gRngValue = 0x03005D80,       -- IWRAM, probablement unchanged

  CB2_InitBattle = nil,         -- ROM address, a trouver
  CB2_ReturnToField = nil,      -- ROM address, a trouver
}

local TRAINER_SECRET_BASE = 1024
local BATTLE_TYPE_TRAINER = 0x08
local BATTLE_TYPE_SECRET_BASE = 0x08000000
local BATTLE_TYPE_LINK = 0x02

-- State
local battleState = {
  active = false,
  isMaster = false,
  opponentParty = nil,      -- 600 bytes de l'equipe adverse
  localChoice = nil,        -- Notre choix ce tour
  remoteChoice = nil,       -- Choix recu de l'adversaire
  waitingForRemote = false, -- On attend le choix distant
  prevExecFlags = 0,        -- Pour detecter les changements
  turnCount = 0,
}

return Battle
```

#### 2.2 Injection de l'equipe adverse

```lua
--[[
  Ecrit l'equipe adverse dans gEnemyParty.
  @param partyData table Array de 600 nombres (octets)
  @return boolean Success
]]
function Battle.injectEnemyParty(partyData)
  if not partyData or #partyData ~= 600 then
    console:log("[Battle] ERROR: Invalid party data")
    return false
  end

  local baseOffset = ADDRESSES.gEnemyParty - 0x02000000

  local ok = pcall(function()
    for i = 1, 600 do
      emu.memory.wram:write8(baseOffset + i - 1, partyData[i])
    end
  end)

  if ok then
    console:log("[Battle] Enemy party injected (600 bytes)")
  end
  return ok
end
```

#### 2.3 Lecture de l'equipe locale

```lua
--[[
  Lit gPlayerParty et retourne les 600 octets.
  @return table Array de 600 nombres, ou nil
]]
function Battle.readLocalParty()
  local baseOffset = ADDRESSES.gPlayerParty - 0x02000000
  local data = {}

  local ok = pcall(function()
    for i = 1, 600 do
      data[i] = emu.memory.wram:read8(baseOffset + i - 1)
    end
  end)

  if ok then
    return data
  end
  return nil
end
```

#### 2.4 Declenchement du combat

```lua
--[[
  Declenche un combat PvP.
  Prerequis: gEnemyParty deja injecte, golden state disponible.

  @param isMaster boolean True si ce joueur est le master (pour RNG)
  @return boolean Success
]]
function Battle.startBattle(isMaster)
  battleState.isMaster = isMaster
  battleState.active = true
  battleState.turnCount = 0

  -- 1. Set gBattleTypeFlags
  local flags = BATTLE_TYPE_TRAINER + BATTLE_TYPE_SECRET_BASE
  if isMaster then
    flags = flags + 0x04  -- BATTLE_TYPE_IS_MASTER (optionnel)
  end
  -- Optionnel: ajouter BATTLE_TYPE_LINK pour desactiver idle RNG
  -- flags = flags + BATTLE_TYPE_LINK

  local ok1 = pcall(emu.memory.wram.write32, emu.memory.wram,
    ADDRESSES.gBattleTypeFlags - 0x02000000, flags)

  -- 2. Set gTrainerBattleOpponent_A = TRAINER_SECRET_BASE
  local ok2 = pcall(emu.memory.wram.write16, emu.memory.wram,
    ADDRESSES.gTrainerBattleOpponent_A - 0x02000000, TRAINER_SECRET_BASE)

  -- 3. Set gMain.savedCallback pour le retour post-combat
  local gMainBase = ADDRESSES.gMainCallback2 - 4
  local ok3 = pcall(emu.memory.wram.write32, emu.memory.wram,
    (gMainBase + 0x08) - 0x02000000, ADDRESSES.CB2_ReturnToField)

  -- 4. Set gMain.state = 0
  local ok4 = pcall(emu.memory.wram.write8, emu.memory.wram,
    (gMainBase + 0x35) - 0x02000000, 0)

  -- 5. Set gMain.callback2 = CB2_InitBattle
  local ok5 = pcall(emu.memory.wram.write32, emu.memory.wram,
    ADDRESSES.gMainCallback2 - 0x02000000, ADDRESSES.CB2_InitBattle)

  if ok1 and ok2 and ok3 and ok4 and ok5 then
    console:log("[Battle] Combat triggered successfully")
    return true
  else
    console:log("[Battle] ERROR: Failed to trigger combat")
    battleState.active = false
    return false
  end
end
```

#### 2.5 Interception de l'IA adversaire

```lua
--[[
  Appelee chaque frame pendant le combat.
  Intercepte les decisions de l'IA et les remplace par les choix distants.
]]
function Battle.tick()
  if not battleState.active then return end

  -- Lire gBattleControllerExecFlags
  local ok, flags = pcall(emu.memory.wram.read32, emu.memory.wram,
    ADDRESSES.gBattleControllerExecFlags - 0x02000000)
  if not ok then return end

  local opponentBit = 0x02  -- Bit 1 = opponent (battler 1)

  -- Detecter: l'IA vient de decider (bit passe de 1 a 0)
  if (battleState.prevExecFlags & opponentBit) ~= 0 and (flags & opponentBit) == 0 then
    -- L'IA a decide! On freeze en remettant le bit
    pcall(emu.memory.wram.write32, emu.memory.wram,
      ADDRESSES.gBattleControllerExecFlags - 0x02000000, flags | opponentBit)

    battleState.waitingForRemote = true
    console:log("[Battle] AI decided — waiting for remote choice")
  end

  -- Si on a recu le choix distant, l'injecter
  if battleState.waitingForRemote and battleState.remoteChoice then
    Battle.injectRemoteChoice(battleState.remoteChoice)
    battleState.remoteChoice = nil
    battleState.waitingForRemote = false
    battleState.turnCount = battleState.turnCount + 1
  end

  battleState.prevExecFlags = flags
end

--[[
  Injecte le choix distant dans gBattleBufferB[opponent].
  @param choice table {action, slot, target} ou {action, switchIndex}
]]
function Battle.injectRemoteChoice(choice)
  local bufferOffset = ADDRESSES.gBattleBufferB - 0x02000000 + 0x200  -- battler 1

  if choice.action == "move" then
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 0, 0x22)  -- CONTROLLER_TWORETURNVALUES
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 1, 10)    -- action type
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 2, choice.slot)
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 3, choice.target or 0)

  elseif choice.action == "switch" then
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 0, 0x23)  -- CONTROLLER_CHOSENMONRETURNVALUE
    pcall(emu.memory.wram.write8, emu.memory.wram, bufferOffset + 1, choice.switchIndex)
    -- TODO: aussi set gChosenActionByBattler[1] = B_ACTION_SWITCH (2)
  end

  -- Degeler: clear le bit opponent
  local ok, flags = pcall(emu.memory.wram.read32, emu.memory.wram,
    ADDRESSES.gBattleControllerExecFlags - 0x02000000)
  if ok then
    pcall(emu.memory.wram.write32, emu.memory.wram,
      ADDRESSES.gBattleControllerExecFlags - 0x02000000, flags & ~0x02)
  end

  console:log(string.format("[Battle] Injected remote choice: %s", choice.action))
end
```

#### 2.6 Capture du choix local

```lua
--[[
  Lit le choix du joueur local depuis gBattleBufferB[player].
  Appelee quand le joueur confirme son choix.
  @return table {action, slot, target} ou nil
]]
function Battle.captureLocalChoice()
  local bufferOffset = ADDRESSES.gBattleBufferB - 0x02000000  -- battler 0

  local ok, cmd = pcall(emu.memory.wram.read8, emu.memory.wram, bufferOffset + 0)
  if not ok then return nil end

  if cmd == 0x22 then  -- CONTROLLER_TWORETURNVALUES (move)
    local actionType = emu.memory.wram:read8(bufferOffset + 1)
    local slot = emu.memory.wram:read8(bufferOffset + 2)
    local target = emu.memory.wram:read8(bufferOffset + 3)

    return { action = "move", slot = slot, target = target }

  elseif cmd == 0x23 then  -- CONTROLLER_CHOSENMONRETURNVALUE (switch)
    local switchIndex = emu.memory.wram:read8(bufferOffset + 1)
    return { action = "switch", switchIndex = switchIndex }
  end

  return nil
end
```

#### 2.7 Synchronisation RNG

```lua
--[[
  Lit la valeur RNG actuelle.
  @return number u32
]]
function Battle.readRng()
  local ok, val = pcall(emu.memory.iwram.read32, emu.memory.iwram, 0x5D80)
  if ok then return val end
  return 0
end

--[[
  Ecrit la valeur RNG (pour synchronisation).
  @param value number u32
]]
function Battle.writeRng(value)
  pcall(emu.memory.iwram.write32, emu.memory.iwram, 0x5D80, value)
end

--[[
  Appele par le reseau quand on recoit un sync RNG du master.
  @param rngValue number
]]
function Battle.onRngSync(rngValue)
  if not battleState.isMaster then
    Battle.writeRng(rngValue)
    console:log(string.format("[Battle] RNG synced: 0x%08X", rngValue))
  end
end
```

#### 2.8 Detection fin de combat

```lua
--[[
  Verifie si le combat est termine.
  @return boolean
]]
function Battle.isFinished()
  if not battleState.active then return false end

  -- Methode 1: gMain.inBattle
  local gMainBase = ADDRESSES.gMainCallback2 - 4
  local ok, inBattle = pcall(emu.memory.wram.read8, emu.memory.wram,
    (gMainBase + 0x37) - 0x02000000)

  if ok and inBattle == 0 then
    return true
  end

  -- Methode 2: gBattleOutcome (backup)
  if ADDRESSES.gBattleOutcome then
    local ok2, outcome = pcall(emu.memory.wram.read8, emu.memory.wram,
      ADDRESSES.gBattleOutcome - 0x02000000)
    if ok2 and outcome ~= 0 then
      return true
    end
  end

  return false
end

--[[
  Lit le resultat du combat.
  @return string "win", "lose", "flee", ou nil
]]
function Battle.getOutcome()
  if not ADDRESSES.gBattleOutcome then return nil end

  local ok, outcome = pcall(emu.memory.wram.read8, emu.memory.wram,
    ADDRESSES.gBattleOutcome - 0x02000000)

  if ok then
    if outcome == 1 then return "win"
    elseif outcome == 2 then return "lose"
    elseif outcome == 7 then return "flee"
    end
  end
  return nil
end

--[[
  Reset l'etat du module.
]]
function Battle.reset()
  battleState.active = false
  battleState.isMaster = false
  battleState.opponentParty = nil
  battleState.localChoice = nil
  battleState.remoteChoice = nil
  battleState.waitingForRemote = false
  battleState.prevExecFlags = 0
  battleState.turnCount = 0
end
```

---

### Phase 3: Protocole reseau pour le PvP

#### 3.1 Nouveaux messages

**Echange d'equipes (avant le combat):**
```json
{
  "type": "duel_party",
  "data": [/* 600 octets en array */]
}
```

**Choix de move:**
```json
{
  "type": "duel_choice",
  "choice": {
    "action": "move",
    "slot": 2,
    "target": 1
  },
  "rng": 0x12345678
}
```

**Choix de switch:**
```json
{
  "type": "duel_choice",
  "choice": {
    "action": "switch",
    "switchIndex": 3
  },
  "rng": 0x12345678
}
```

**Sync RNG (master → slave, debut de chaque tour):**
```json
{
  "type": "duel_rng_sync",
  "rng": 0x12345678
}
```

**Fin de combat:**
```json
{
  "type": "duel_end",
  "outcome": "win"
}
```

#### 3.2 Modifications serveur

**Fichier:** `server/server.js`

```javascript
case 'duel_party':
  // Stocker la party du joueur et la relayer a l'adversaire
  client.duelParty = message.data;
  if (client.duelOpponent) {
    const opponent = clients.get(client.duelOpponent);
    if (opponent) {
      sendToClient(opponent, {
        type: 'duel_party',
        playerId: client.id,
        data: message.data
      });
    }
  }
  break;

case 'duel_choice':
  // Relayer le choix a l'adversaire
  if (client.duelOpponent) {
    const opponent = clients.get(client.duelOpponent);
    if (opponent) {
      sendToClient(opponent, {
        type: 'duel_choice',
        playerId: client.id,
        choice: message.choice,
        rng: message.rng
      });
    }
  }
  break;

case 'duel_rng_sync':
  // Master envoie sync RNG au slave
  if (client.duelOpponent) {
    const opponent = clients.get(client.duelOpponent);
    if (opponent) {
      sendToClient(opponent, {
        type: 'duel_rng_sync',
        rng: message.rng
      });
    }
  }
  break;

case 'duel_end':
  // Combat termine, cleanup
  if (client.duelOpponent) {
    const opponent = clients.get(client.duelOpponent);
    if (opponent) {
      opponent.duelOpponent = null;
      opponent.duelParty = null;
    }
  }
  client.duelOpponent = null;
  client.duelParty = null;
  break;
```

---

### Phase 4: Integration dans main.lua

#### 4.1 Nouveau flow du duel

```lua
-- Dans le handler duel_warp (remplace le code actuel)
elseif message.type == "duel_warp" then
  local coords = message.coords
  local isMaster = message.isMaster or false

  -- Sauvegarder position d'origine pour le retour
  local currentPos = readPlayerPosition()
  if currentPos then
    State.duelOrigin = {
      x = currentPos.x,
      y = currentPos.y,
      mapGroup = currentPos.mapGroup,
      mapId = currentPos.mapId
    }
  end

  -- Stocker les parametres du duel
  State.duelPending = {
    mapGroup = coords.mapGroup,
    mapId = coords.mapId,
    x = coords.x,
    y = coords.y,
    isMaster = isMaster
  }

  -- Envoyer notre equipe
  local localParty = Battle.readLocalParty()
  if localParty then
    Network.send({ type = "duel_party", data = localParty })
  end

  -- Attendre l'equipe adverse avant de warp...
  State.warpPhase = "waiting_party"

-- Nouveau handler pour recevoir l'equipe adverse
elseif message.type == "duel_party" then
  State.opponentParty = message.data

  -- Si on etait en attente de la party, commencer le warp
  if State.warpPhase == "waiting_party" and State.duelPending then
    -- Injecter l'equipe adverse
    Battle.injectEnemyParty(State.opponentParty)

    -- Faire le warp (save state hijack existant)
    -- ... code existant ...

    State.warpPhase = "loading"
  end
```

#### 4.2 Nouvelle phase "in_battle"

```lua
elseif State.warpPhase == "in_battle" then
  -- Tick du module battle
  Battle.tick()

  -- Capturer notre choix quand on le fait
  if Battle.hasPlayerChosen() and not State.sentChoice then
    local choice = Battle.captureLocalChoice()
    if choice then
      local rng = nil
      if State.duelPending.isMaster then
        rng = Battle.readRng()
      end
      Network.send({
        type = "duel_choice",
        choice = choice,
        rng = rng
      })
      State.sentChoice = true
    end
  end

  -- Reset flag au debut du tour suivant
  if Battle.isNewTurn() then
    State.sentChoice = false

    -- Master envoie sync RNG
    if State.duelPending.isMaster then
      Network.send({
        type = "duel_rng_sync",
        rng = Battle.readRng()
      })
    end
  end

  -- Verifier fin de combat
  if Battle.isFinished() then
    local outcome = Battle.getOutcome()
    Network.send({ type = "duel_end", outcome = outcome })

    -- Declencher retour a l'origine
    State.warpPhase = "returning"
  end

-- Handler pour recevoir le choix adverse
elseif message.type == "duel_choice" then
  Battle.setRemoteChoice(message.choice)
  if message.rng and not State.duelPending.isMaster then
    Battle.onRngSync(message.rng)
  end

elseif message.type == "duel_rng_sync" then
  Battle.onRngSync(message.rng)
```

#### 4.3 Phase "returning" (retour a l'origine)

```lua
elseif State.warpPhase == "returning" then
  if State.duelOrigin then
    -- Utiliser le meme save state hijack pour retourner
    local savedData = HAL.saveGameData()
    HAL.loadGoldenState()
    HAL.restoreGameData(savedData)
    HAL.writeWarpData(
      State.duelOrigin.mapGroup,
      State.duelOrigin.mapId,
      State.duelOrigin.x,
      State.duelOrigin.y
    )

    State.warpPhase = "loading_return"
    State.unlockFrame = State.frameCounter + 300
  end

elseif State.warpPhase == "loading_return" then
  if HAL.isWarpComplete() then
    -- Cleanup complet
    State.warpPhase = nil
    State.duelPending = nil
    State.duelOrigin = nil
    State.opponentParty = nil
    State.inputsLocked = false
    Battle.reset()

    log("Returned to origin after duel!")
  end
```

---

### Phase 5: Gestion des edge cases

#### 5.1 Deconnexion pendant le combat

```lua
-- Dans handleMessage, si player_disconnected et on est en duel
if State.warpPhase == "in_battle" and message.playerId == State.duelOpponent then
  -- L'adversaire s'est deconnecte pendant le combat
  -- Option 1: Forcer la victoire (pas ideal)
  -- Option 2: Annuler le combat et retourner

  log("Opponent disconnected during battle — returning to origin")
  State.warpPhase = "returning"
end
```

#### 5.2 Timeout de choix

```lua
-- Si on attend le choix distant depuis trop longtemps (30 sec)
if Battle.isWaitingForRemote() then
  State.remoteChoiceTimeout = State.remoteChoiceTimeout or State.frameCounter

  if State.frameCounter - State.remoteChoiceTimeout > 1800 then
    -- Timeout — forcer un choix par defaut (Struggle ou switch)
    log("Remote choice timeout — using default action")
    Battle.setRemoteChoice({ action = "move", slot = 0, target = 0 })
    State.remoteChoiceTimeout = nil
  end
else
  State.remoteChoiceTimeout = nil
end
```

#### 5.3 Whiteout (defaite avec 0 Pokemon)

```lua
-- Surveiller callback2 pour detecter CB2_WhiteOut
if HAL.readCallback2() == CB2_WHITEOUT then
  -- Intercepter AVANT le whiteout
  -- Forcer le retour a l'origine a la place
  log("Preventing whiteout — returning to origin")

  -- Charger le golden state + retour
  local savedData = HAL.saveGameData()
  HAL.loadGoldenState()
  HAL.restoreGameData(savedData)
  HAL.writeWarpData(State.duelOrigin.mapGroup, State.duelOrigin.mapId,
    State.duelOrigin.x, State.duelOrigin.y)

  State.warpPhase = "loading_return"
end
```

#### 5.4 Items en combat

Pour la v1, on peut **desactiver les items** en remplacant `B_ACTION_USE_ITEM` par `B_ACTION_USE_MOVE` avec le slot 0. C'est plus simple et evite les complexites de synchronisation des items (qui Pokemon cibler, quel item, etc.).

Alternative: supporter les items avec un message `duel_choice` etendu:
```json
{
  "type": "duel_choice",
  "choice": {
    "action": "item",
    "itemId": 17,
    "targetMon": 0
  }
}
```

---

## Configuration finale run_and_bun.lua

Apres le scan, le fichier devrait ressembler a:

```lua
return {
  name = "Pokemon Run & Bun",
  gameId = "BPEE",
  version = "1.0",

  offsets = {
    playerX = 0x02024CBC,
    playerY = 0x02024CBE,
    mapGroup = 0x02024CC0,
    mapId = 0x02024CC1,
    facing = 0x02036934,
    cameraX = 0x03005DFC,
    cameraY = 0x03005DF8,
  },

  warp = {
    callback2Addr = 0x0202064C,
    cb2LoadMap = 0x08007441,
    cb2Overworld = 0x080A89A5,
  },

  -- NOUVELLES ADRESSES POUR LE COMBAT (a remplir apres scan)
  battle = {
    gPlayerParty = nil,           -- A scanner (vanilla: 0x020244EC)
    gEnemyParty = nil,            -- A scanner (vanilla: 0x02024744)
    gBattleTypeFlags = nil,       -- A scanner (vanilla: 0x02022FEC)
    gTrainerBattleOpponent_A = nil, -- A scanner (vanilla: 0x02038BCA)
    gBattleControllerExecFlags = nil, -- A scanner (vanilla: 0x02024068)
    gBattleBufferB = nil,         -- A scanner (vanilla: 0x02023864)
    gBattleOutcome = nil,         -- A scanner
    gRngValue = 0x03005D80,       -- IWRAM, probablement unchanged

    CB2_InitBattle = nil,         -- A trouver via watchpoint
    CB2_ReturnToField = nil,      -- A trouver via watchpoint
    CB2_WhiteOut = nil,           -- A trouver via watchpoint
  },

  duelRoom = {
    mapGroup = 28,
    mapId = 24,
    playerAX = 3,
    playerAY = 5,
    playerBX = 10,
    playerBY = 5
  },

  -- ... reste de la config
}
```

---

## Estimation de travail

| Phase | Description | Effort |
|-------|-------------|--------|
| 1 | Scanner les adresses battle | 2-3 heures |
| 2 | Module battle.lua (core) | 4-6 heures |
| 3 | Protocole reseau | 2-3 heures |
| 4 | Integration main.lua | 3-4 heures |
| 5 | Edge cases et tests | 4-6 heures |

**Total estime: 15-22 heures de travail**

---

## Risques et mitigations

| Risque | Probabilite | Impact | Mitigation |
|--------|-------------|--------|------------|
| Adresses R&B introuvables | Faible | Bloquant | Scripts de scan exhaustifs |
| Desync RNG | Moyenne | Derangeant | Sync a chaque tour + flag LINK |
| Crash au trigger combat | Moyenne | Bloquant | Tests incrementaux, verifier chaque ecriture |
| Latence reseau elevee | Faible | Derangeant | Le jeu est "gele" pendant l'attente, acceptable |
| Whiteout non intercepte | Moyenne | Derangeant | Watchpoint sur CB2_WhiteOut |

---

## Fichiers concernes

### A creer
| Fichier | Description |
|---------|-------------|
| `scripts/scan_battle_addresses.lua` | Script de scan pour trouver les adresses |
| `client/battle.lua` | Module de gestion des combats PvP |

### A modifier
| Fichier | Modifications |
|---------|--------------|
| `config/run_and_bun.lua` | Ajouter section `battle` avec les adresses |
| `client/main.lua` | Integrer battle.lua, nouvelles phases warp |
| `client/hal.lua` | Ajouter `HAL.readInBattle()` si necessaire |
| `server/server.js` | Handlers `duel_party`, `duel_choice`, `duel_rng_sync`, `duel_end` |

---

## Test plan

### Test 1: Scan d'adresses
- [ ] Scanner gBattleTypeFlags pendant combat trainer
- [ ] Scanner gEnemyParty via HP
- [ ] Scanner gBattleControllerExecFlags
- [ ] Trouver CB2_InitBattle via watchpoint
- [ ] Documenter toutes les adresses

### Test 2: Injection equipe
- [ ] Lire gPlayerParty (600 octets)
- [ ] Ecrire dans gEnemyParty
- [ ] Verifier que les Pokemon apparaissent en combat

### Test 3: Trigger de combat
- [ ] Trigger CB2_InitBattle manuellement
- [ ] Verifier que le combat demarre
- [ ] Verifier que gEnemyParty n'est pas ecrase (TRAINER_SECRET_BASE)

### Test 4: Interception IA
- [ ] Detecter quand l'IA decide
- [ ] Geler le combat (remettre bit exec)
- [ ] Injecter un choix manuel
- [ ] Verifier que le tour s'execute avec notre choix

### Test 5: Combat complet 2 joueurs
- [ ] Echange d'equipes via reseau
- [ ] Warp vers salle de duel
- [ ] Combat avec vrais choix synchronises
- [ ] Sync RNG (memes degats des deux cotes)
- [ ] Fin de combat et retour

### Test 6: Edge cases
- [ ] Deconnexion pendant combat
- [ ] Timeout de choix
- [ ] Switch de Pokemon
- [ ] Defaite (pas de whiteout)
