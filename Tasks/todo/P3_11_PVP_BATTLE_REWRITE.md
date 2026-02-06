# PvP Battle System Rewrite — Link Battle Emulation (approche PK-GBA)

> **Statut:** A faire
> **Type:** Feature majeure — reecriture complete du systeme de combat PvP
> **Priorite:** P0 - CRITIQUE
> **Prerequis:** Aucun (remplace P3_10_DUEL_BATTLE_AND_RETURN.md)
> **Date creation:** 2026-02-06
> **Supersedes:** P3_10_DUEL_BATTLE_AND_RETURN.md (approche BATTLE_TYPE_SECRET_BASE abandonnee)

---

## CONTEXTE : Pourquoi une reecriture complete

### L'ancien systeme (BATTLE_TYPE_SECRET_BASE + AI interception) est mort

**Problemes fondamentaux (pas juste des bugs d'adresses) :**

1. **Mauvais trigger** : On ecrivait `callback2 = CB2_LoadMap` ce qui charge une CARTE, pas un combat
2. **BATTLE_TYPE_SECRET_BASE** lance un combat contre une IA locale — pas un vrai combat link
3. **AI interception** (gBattleControllerExecFlags bit toggle) est fragile et non-prouve
4. **RNG sync** insuffisant : le jeu appelle le RNG des dizaines de fois par tour (degats, precision, crits, effets secondaires), une seule sync par tour ne suffit pas
5. **Adresses manquantes** : `gBattleBufferB = nil`, `gBattleControllerExecFlags` suspect (derive d'une mauvaise base)

### La nouvelle approche : Link Battle Emulation (prouvee par PK-GBA Multiplayer)

Le projet [PK-GBA Multiplayer](https://github.com/TheHunterManX/GBA-PK-multiplayer) fait du PvP fonctionnel sur Gen 3 en Lua pur. Leur technique :

1. **Patcher la ROM en live** via `emu.memory.cart0` — neutraliser les checks cable link
2. **Appeler les vraies fonctions du jeu** via ASM inline — `CreateTask(Task_StartWiredCableClubBattle)`
3. **Relayer les battle buffers** (`gBattleBufferA/B`) via TCP — faux cable link logiciel

Le jeu pense qu'un vrai cable est branche. Toute la logique native de combat link fonctionne (menus, animations, attente de l'autre joueur, etc.)

**Avantages :**

| Aspect | Ancien systeme | Nouveau systeme |
|--------|---------------|-----------------|
| Trigger combat | Ecrire callback2 (casse) | Appel natif Task_StartWiredCableClubBattle |
| Type combat | SECRET_BASE (IA locale) | Vrai combat link (attend l'autre joueur) |
| Sync actions | Intercepter IA + sync RNG (fragile) | Relay gBattleBufferA/B (meme interface que le cable) |
| Ecriture ROM | Non | Oui (emu.memory.cart0) |
| Lieu combat | Warp force vers colosseum | N'importe ou (pas de warp necessaire) |
| Robustesse | Fragile, beaucoup d'edge cases | Solide, utilise le vrai systeme natif |

---

## ETAPE 0 : Supprimer l'ancien systeme

### 0.1 Fichiers a supprimer ou vider

| Fichier | Action |
|---------|--------|
| `client/battle.lua` | **REECRIRE ENTIEREMENT** (garder le squelette module, supprimer tout le contenu) |

### 0.2 Code a retirer dans d'autres fichiers

**`client/main.lua` :**
- Supprimer tout le code lie a `Battle.tick()`, `Battle.captureLocalChoice()`, `Battle.hasPlayerChosen()`
- Supprimer la logique d'interception IA (prevExecFlags, bit toggle)
- Supprimer la sync RNG (duel_rng_sync send/receive)
- Garder : warp phases (waiting_party, in_battle, returning), party exchange, duel request/accept

**`config/run_and_bun.lua` section battle :**
- Supprimer : `gBattleControllerExecFlags`, `gBattleOutcome`, `CB2_BattleMain` (plus necessaires)
- Garder : `gPlayerParty`, `gEnemyParty`, `gBattleTypeFlags`, `gRngValue`
- Ajouter : nouvelles adresses (voir Phase 2)

**`server/server.js` :**
- Supprimer : `duel_rng_sync` handler
- Modifier : `duel_choice` handler (relay buffer data au lieu de choice struct)
- Ajouter : `duel_buffer` handler (relay de gBattleBufferA/B)

---

## ETAPE 1 : Script de Discovery (trouver les adresses)

### Prerequis API mGBA decouverts

On ne le savait pas, mais mGBA 0.11+ dev expose deja :

```lua
-- Breakpoints CPU (callback quand le PC atteint une adresse ROM)
local bpId = emu:setBreakpoint(callback, romAddress)

-- Watchpoints memoire (callback quand une adresse RAM est ecrite)
local wpId = emu:setWatchpoint(callback, ramAddress, C.WATCHPOINT_TYPE.WRITE)

-- Watchpoints sur plage
local wpId = emu:setRangeWatchpoint(callback, minAddr, maxAddr, C.WATCHPOINT_TYPE.WRITE)

-- Registres ARM (dans les callbacks)
local pc = emu:readRegister("pc")   -- quelle fonction ROM a fait l'ecriture
local lr = emu:readRegister("lr")   -- qui l'a appelee

-- Ecriture ROM (!!!)
emu.memory.cart0:write16(offset, value)  -- patcher la ROM en live

-- Evenements souris (!!!)
callbacks:add("mouseButton", function(ev) ... end)
callbacks:add("mouseMove", function(ev) ... end)
```

### 1.1 Script watchpoint de discovery

**Fichier a creer : `scripts/discovery/find_battle_functions.lua`**

**Concept :** Poser des watchpoints sur les adresses DEJA CONNUES, puis lancer un combat dresseur normal dans le jeu. Les watchpoints capturent le registre PC = adresse de la fonction ROM qui a ecrit.

```lua
-- Adresses deja connues dans Run & Bun
local KNOWN = {
    gBattleTypeFlags       = 0x020090E8,
    gPlayerParty           = 0x02023A98,
    gEnemyParty            = 0x02023CF0,
    gMainCallback2         = 0x0202064C,
    gMainInBattle          = 0x020206AE,
    gRngValue_IWRAM_offset = 0x5D90,
}
```

**Watchpoints a poser :**

| Watchpoint sur | Ce qu'on decouvre | Quand ca fire |
|----------------|-------------------|---------------|
| `gBattleTypeFlags` (write) | Fonctions qui configurent le combat | Entree en combat |
| `gEnemyParty` (range write, 600 bytes) | Fonctions qui ecrivent la party adverse | Debut combat trainer |
| `gMainCallback2` (write) | Toutes les transitions de callback | Tout le temps |
| `gMainInBattle` (write) | Qui set/clear le flag inBattle | Entree/sortie combat |

**Pour chaque write capturee, logger :**
- Adresse de la variable ecrite
- Valeur ecrite
- PC (adresse de la fonction ROM)
- LR (adresse de l'appelant)
- Frame number

**Instructions utilisateur :**
1. Charger le script dans mGBA
2. Entrer dans un combat dresseur normalement
3. Combattre et gagner/perdre
4. Le script affiche toutes les fonctions ROM impliquees

### 1.2 Script diff EWRAM avant/apres combat

**Fichier a creer : `scripts/discovery/ewram_battle_diff.lua`**

**Concept :** Snapshot 256KB d'EWRAM avant et apres un combat. Les bytes qui changent revelent les adresses de toutes les variables battle.

```lua
-- AVANT le combat : snapshot
local snapshot = emu.memory.wram:readRange(0, 0x40000)

-- APRES le combat : comparer
-- Filtrer les changements significatifs (pas les variables qui changent tout le temps)
-- Regrouper les changements contigus (blocs = structs/arrays)
```

**Variables a trouver via diff :**

| Variable | Taille | Pattern attendu |
|----------|--------|-----------------|
| `gBattleBufferA` | 4 x 512 = 2048 bytes | Grand bloc contigu, actif pendant combat |
| `gBattleBufferB` | 4 x 512 = 2048 bytes | Adjacent a gBattleBufferA |
| `gBattleCommunication` | 8 bytes | Petit bloc, valeurs 0-20 |
| `gBattleMons` | Variable | Grand bloc (stats des Pokemon en combat) |
| `gBlockReceivedStatus` | 4 bytes | Petit, valeurs bitflag |
| `gLinkPlayers` | 5 x sizeof(LinkPlayer) | Struct avec noms de joueurs |

### 1.3 Script scan ROM par signatures

**Fichier a creer : `scripts/discovery/find_rom_functions.lua`**

**Concept :** Les fonctions ROM qu'on cherche referencent des adresses EWRAM connues dans leur literal pool. Scanner la ROM pour ces references.

**Exemple :** `Task_StartWiredCableClubBattle` reference `CB2_InitBattle` dans son literal pool. Si on connait `CB2_InitBattle` (trouvee via watchpoint sur gMainCallback2), on peut scanner la ROM pour trouver toutes les fonctions qui la referencent.

**Methode (deja implementee dans hal.lua pour le warp) :**
1. `emu.memory.cart0:readRange(offset, 4096)` pour lire la ROM par blocs
2. Scanner pour les adresses EWRAM/ROM connues en little-endian
3. Pour chaque match, remonter au debut de la fonction (chercher PUSH {... LR})
4. Analyser la taille et la structure de la fonction

### 1.4 Adresses a trouver pour la nouvelle approche

**Variables EWRAM (trouvables via watchpoint + diff) :**

| Variable | Taille | Vanilla Emerald | Methode discovery | Criticite |
|----------|--------|-----------------|-------------------|-----------|
| `gBattleBufferA` | 2048 | 0x02023064 | Diff EWRAM pendant combat | CRITIQUE |
| `gBattleBufferB` | 2048 | 0x02023864 | Adjacent a gBattleBufferA | CRITIQUE |
| `gBattleCommunication` | 8 | 0x02024332 | Diff + watchpoint (valeurs 0-20) | CRITIQUE |
| `gBlockReceivedStatus` | 4 | N/A | Diff pendant combat link | HAUTE |
| `gLinkPlayers` | ~120 | N/A | Diff (contient nom joueur en ASCII) | HAUTE |
| `gWirelessCommType` | 1 | N/A | Scan ROM refs ou diff | HAUTE |
| `gBattleControllerExecFlags` | 4 | 0x02024068 | Watchpoint | MOYENNE |
| `gReceivedRemoteLinkPlayers` | 1 | N/A | Diff pendant combat | MOYENNE |
| `gLinkCallback` | 4 | N/A | Watchpoint | MOYENNE |

**Fonctions ROM (trouvables via watchpoint sur gMainCallback2 + scan ROM) :**

| Fonction | Vanilla Emerald | Methode discovery | Criticite |
|----------|-----------------|-------------------|-----------|
| `CB2_InitBattle` | 0x08036760 | Watchpoint gMainCallback2 pendant entree combat | CRITIQUE |
| `Task_StartWiredCableClubBattle` | N/A | Scan ROM pour refs a CB2_InitBattle | CRITIQUE |
| `CB2_HandleStartBattle` | N/A | Watchpoint gBattleCommunication | HAUTE |
| `SetUpBattleVarsAndBirchZigzagoon` | 0x0803269C | Scan ROM | HAUTE |
| `PlayerBufferExecCompleted` | N/A | Scan ROM (ref GetMultiplayerId) | HAUTE |
| `LinkOpponentBufferExecCompleted` | N/A | Scan ROM (ref GetMultiplayerId) | HAUTE |
| `PrepareBufferDataTransferLink` | N/A | Scan ROM | HAUTE |
| `GetMultiplayerId` | N/A | Scan ROM (ref SIO_MULTI_CNT register) | HAUTE |
| `InitLocalLinkPlayer` | N/A | Scan ROM (refs gSaveBlock2Ptr) | MOYENNE |
| `CreateTask` | N/A | Scan ROM (ref gTasks array) | MOYENNE |
| `CB2_ReturnToField` | N/A | Watchpoint gMainCallback2 apres fin combat | MOYENNE |
| `CB2_ReturnFromCableClubBattle` | N/A | Watchpoint apres combat link | MOYENNE |

**Adresses deja connues (pas besoin de re-scanner) :**

| Variable | Adresse R&B | Source |
|----------|-------------|--------|
| gPlayerParty | 0x02023A98 | pokemon-run-bun-exporter (verifie) |
| gPlayerPartyCount | 0x02023A95 | pokemon-run-bun-exporter (verifie) |
| gEnemyParty | 0x02023CF0 | pokemon-run-bun-exporter (verifie) |
| gBattleTypeFlags | 0x020090E8 | Scanner mGBA |
| gMainCallback2 | 0x0202064C | Scanner mGBA |
| gMainInBattle | 0x020206AE | gMain+0x66, verifie |
| gRngValue | 0x03005D90 | IWRAM, verifie |
| CB2_LoadMap | 0x08007441 | Scanner mGBA |
| CB2_Overworld | 0x080A89A5 | Scanner mGBA |
| CB2_BattleMain | 0x08094815 | Scanner mGBA |
| sWarpDestination | 0x020318A8 | find_sWarpDest_definitive.lua |

---

## ETAPE 2 : Execution du discovery (utilisateur)

### Workflow utilisateur

```
1. Charger find_battle_functions.lua dans mGBA
2. Entrer dans un combat dresseur normal dans Run & Bun
3. Combattre et gagner
4. Copier les logs de la console mGBA

5. Charger ewram_battle_diff.lua dans mGBA
6. Appuyer sur un bouton pour capturer le snapshot "hors combat"
7. Entrer en combat
8. Appuyer sur un bouton pour capturer le snapshot "en combat"
9. Le script affiche les blocs de memoire qui ont change

10. Charger find_rom_functions.lua dans mGBA
11. Le script scanne la ROM automatiquement avec les adresses trouvees en 1-9
12. Les fonctions ROM sont identifiees
```

### Resultat attendu

Toutes les adresses du tableau 1.4 remplies dans `config/run_and_bun.lua` section `battle_link`.

---

## ETAPE 3 : Reecriture de battle.lua (Link Battle Emulation)

### 3.1 Architecture du nouveau module

**Fichier : `client/battle.lua` (reecriture complete)**

Le module a 4 responsabilites :

1. **ROM Patching** : Neutraliser les checks cable link au debut du combat, restaurer apres
2. **Battle Setup** : Appeler Task_StartWiredCableClubBattle via le script engine ou ASM inline
3. **Buffer Relay** : Lire gBattleBufferA/B locaux, envoyer via TCP, ecrire les buffers recus
4. **State Machine** : Gerer les etapes du combat (init, exchange, main loop, cleanup)

### 3.2 ROM Patching — Neutraliser les checks link

**Principe :** Ecrire des instructions NOP (0x0000) ou des branches inconditionnelles (0xE0XX) dans la ROM pour bypass les verifications cable link.

**Patches necessaires (a adapter pour R&B, offsets relatifs aux fonctions) :**

```lua
local patches = {}  -- Sauvegarde des valeurs originales pour restauration

function Battle.applyROMPatches()
    local ROMCARD = emu.memory.cart0
    local ADDR = config.battle_link  -- adresses trouvees en Phase 1

    -- 1. Set wireless type to cable
    emu:write8(ADDR.gWirelessCommType, 0)

    -- 2. NOP les checks link dans SetUpBattleVars
    --    (empeche la creation de tasks d'erreur multijoueur)
    patches.setupVars1 = ROMCARD:read16(ADDR.SetUpBattleVars_patch1)
    patches.setupVars2 = ROMCARD:read16(ADDR.SetUpBattleVars_patch2)
    ROMCARD:write16(ADDR.SetUpBattleVars_patch1, 0x0000)  -- NOP
    ROMCARD:write16(ADDR.SetUpBattleVars_patch2, 0x0000)  -- NOP

    -- 3. Bypass le blocage dans CB2_HandleStartBattle (case 1 = attente link)
    --    Remplacer le branch conditionnel par un branch inconditionnel
    patches.handleStart = ROMCARD:read16(ADDR.CB2_HandleStartBattle_patch)
    ROMCARD:write16(ADDR.CB2_HandleStartBattle_patch, 0xE006)  -- B +12 (skip)

    -- 4. NOP le transfert de donnees dans case 12 (link data)
    patches.handleData1 = ROMCARD:read16(ADDR.CB2_HandleStartBattle_data1)
    patches.handleData2 = ROMCARD:read16(ADDR.CB2_HandleStartBattle_data2)
    ROMCARD:write16(ADDR.CB2_HandleStartBattle_data1, 0x0000)  -- NOP
    ROMCARD:write16(ADDR.CB2_HandleStartBattle_data2, 0x0000)  -- NOP

    -- 5. Skip PlayerBufferExecCompleted network check
    patches.playerExec = ROMCARD:read16(ADDR.PlayerBufferExecCompleted_patch)
    ROMCARD:write16(ADDR.PlayerBufferExecCompleted_patch, 0xE01A)  -- B over

    -- 6. Skip LinkOpponentBufferExecCompleted network check
    patches.linkOpponentExec = ROMCARD:read16(ADDR.LinkOpponentBufferExecCompleted_patch)
    ROMCARD:write16(ADDR.LinkOpponentBufferExecCompleted_patch, 0xE01A)  -- B over

    -- 7. Skip PrepareBufferDataTransfer link requirement
    patches.prepareTransfer = ROMCARD:read16(ADDR.PrepareBufferDataTransfer_patch)
    ROMCARD:write16(ADDR.PrepareBufferDataTransfer_patch, 0xE009)  -- B over

    -- 8. Patch GetMultiplayerId pour retourner 0 (host) ou 1 (client)
    patches.multiplayerId = ROMCARD:read16(ADDR.GetMultiplayerId_patch)
    if battleState.isMaster then
        ROMCARD:write16(ADDR.GetMultiplayerId_patch, 0x2000)  -- MOVS r0, #0
    else
        ROMCARD:write16(ADDR.GetMultiplayerId_patch, 0x2001)  -- MOVS r0, #1
    end

    console:log("[Battle] ROM patches applied (" .. tableSize(patches) .. " patches)")
end

function Battle.restoreROMPatches()
    local ROMCARD = emu.memory.cart0
    local ADDR = config.battle_link

    -- Restaurer toutes les valeurs originales
    for name, originalValue in pairs(patches) do
        local patchAddr = ADDR[name .. "_addr"]  -- convention de nommage
        if patchAddr then
            ROMCARD:write16(patchAddr, originalValue)
        end
    end
    patches = {}
    console:log("[Battle] ROM patches restored")
end
```

**NOTE IMPORTANTE :** Les offsets exacts des patches (ex: `SetUpBattleVars + 0x42`) doivent etre trouves specifiquement pour Run & Bun. PK-GBA les connait pour vanilla Emerald. Pour R&B, il faudra :
1. Trouver l'adresse de base de chaque fonction (Phase 1)
2. Desassembler le debut de chaque fonction pour trouver le bon offset du check a patcher
3. Ca peut se faire via `emu.memory.cart0:readRange()` + analyse des instructions Thumb

### 3.3 Battle Setup — Lancer le combat

**Methode 1 : Manipulation directe de callback2 (simple)**

```lua
function Battle.startBattle(isMaster)
    battleState.isMaster = isMaster
    battleState.active = true

    -- 1. Appliquer les patches ROM
    Battle.applyROMPatches()

    -- 2. Setup gBattleTypeFlags (vrai combat link)
    local flags = BATTLE_TYPE_TRAINER | BATTLE_TYPE_LINK
    if isMaster then
        flags = flags | BATTLE_TYPE_IS_MASTER
    end
    emu:write32(ADDR.gBattleTypeFlags, flags)

    -- 3. Setup fake gLinkPlayers
    Battle.setupFakeLinkPlayers()

    -- 4. Trigger via Task_StartWiredCableClubBattle
    --    Option A: Ecrire ASM inline dans ROM scratch area
    --    Option B: Manipuler callback2 directement
    --    (voir section 3.4)
end
```

**Methode 2 : ASM inline (robuste, comme PK-GBA)**

PK-GBA ecrit du Thumb assembly dans une zone inutilisee de la ROM, puis declenche l'execution via le script engine du jeu. L'assembly appelle `CreateTask(Task_StartWiredCableClubBattle, priority)`.

```lua
-- Ecrire dans une zone scratch de la ROM (adresse haute, inutilisee)
-- Les ROMs font typiquement 16-32MB, la zone apres les donnees est libre
local SCRATCH_ADDR = 0x08A90000  -- Zone scratch (comme PK-GBA)
local ROMCARD = emu.memory.cart0
local scratchOffset = SCRATCH_ADDR - 0x08000000

-- Thumb ASM : PUSH {LR}; MOV R0, Task_StartWiredCableClubBattle+1;
--             MOV R1, #0x80; BL CreateTask; POP {PC}
-- (Les opcodes exacts dependent des adresses trouvees)
ROMCARD:write16(scratchOffset + 0, 0xB500)   -- PUSH {LR}
ROMCARD:write16(scratchOffset + 2, 0x4801)   -- LDR R0, [PC, #4]  (literal pool)
ROMCARD:write16(scratchOffset + 4, 0x2180)   -- MOVS R1, #0x80     (priority)
ROMCARD:write16(scratchOffset + 6, 0x4A01)   -- LDR R2, [PC, #4]  (CreateTask addr)
ROMCARD:write16(scratchOffset + 8, 0x4790)   -- BLX R2             (call CreateTask)
ROMCARD:write16(scratchOffset + 10, 0xBD00)  -- POP {PC}
-- Literal pool :
ROMCARD:write32(scratchOffset + 12, ADDR.Task_StartWiredCableClubBattle + 1)  -- +1 = THUMB
ROMCARD:write32(scratchOffset + 16, ADDR.CreateTask + 1)                       -- +1 = THUMB
```

**NOTE :** L'ASM inline exact sera determine apres avoir les adresses reelles. Les opcodes ci-dessus sont un template. Il faudra verifier que la zone scratch est bien inutilisee dans Run & Bun.

### 3.4 Fake Link Players

```lua
function Battle.setupFakeLinkPlayers()
    local ADDR = config.battle_link

    -- Ecrire les infos du joueur local dans gLinkPlayers[0]
    -- Ecrire les infos du joueur distant dans gLinkPlayers[1]

    local linkPlayerSize = 28  -- sizeof(struct LinkPlayer) a verifier pour R&B
    local base0 = ADDR.gLinkPlayers
    local base1 = ADDR.gLinkPlayers + linkPlayerSize

    -- Joueur local
    emu:write16(base0 + 0, 0x0003)   -- version (Emerald = 3)
    -- Copier le nom du joueur local depuis gSaveBlock2
    -- ...

    -- Joueur distant (infos recues via reseau)
    emu:write16(base1 + 0, 0x0003)   -- version
    -- Ecrire le nom du joueur distant
    -- ...

    -- Set gReceivedRemoteLinkPlayers = 1
    emu:write8(ADDR.gReceivedRemoteLinkPlayers, 1)
end
```

### 3.5 Buffer Relay — Le coeur du systeme

**Principe :** Le jeu ecrit dans `gBattleBufferA[battler]` quand il veut communiquer avec un controlleur. Le controlleur repond dans `gBattleBufferB[battler]`. Dans un vrai combat link, ces buffers sont envoyes via le cable. On les envoie via TCP.

**State machine du relay (dans Battle.tick(), appele chaque frame) :**

```
STAGE 0-2 : Attente synchronisation (les deux joueurs prets)
STAGE 3   : InitiateBattle (patches ROM, trigger combat, exchange gSendBuffer)
STAGE 4   : Ecrire le link battle header recu dans gReceiveBuffer
STAGE 5   : Exchange Pokemon data, skip les stages de communication link
STAGE 6   : Skip video RNG (Emerald-specific)
STAGE 7   : BOUCLE PRINCIPALE DU COMBAT
            - Detecter quand gBattleControllerExecFlags a un flag set pour l'adversaire
            - Lire gBattleBufferA et gBattleBufferB du slot adversaire
            - Envoyer via TCP
            - Quand les buffers distants arrivent, les ecrire localement
            - Manipuler gBattleControllerExecFlags pour signaler la completion
STAGE 8-9 : Fin de combat, cleanup, restauration ROM patches
```

**Messages reseau (remplacent duel_choice et duel_rng_sync) :**

```json
{"type":"duel_buffer","slot":"A","battler":1,"data":[/* bytes */],"stage":7}
{"type":"duel_buffer","slot":"B","battler":1,"data":[/* bytes */],"stage":7}
{"type":"duel_stage","stage":3}
{"type":"duel_end","outcome":"win"}
```

### 3.6 Gestion de fin de combat

```lua
function Battle.checkBattleEnd()
    -- Detecter quand le jeu ecrit le command "exit" dans gBattleBufferA[0]
    -- 0x37 = exit command (fin de combat)
    local exitCmd = emu:read8(ADDR.gBattleBufferA)
    if exitCmd == 0x37 then
        Battle.restoreROMPatches()
        battleState.active = false
        return true
    end

    -- Backup : inBattle transition 1 -> 0
    local inBattle = emu:read8(ADDR.gMainInBattle)
    if battleState.prevInBattle == 1 and inBattle == 0 then
        Battle.restoreROMPatches()
        battleState.active = false
        return true
    end
    battleState.prevInBattle = inBattle

    return false
end
```

---

## ETAPE 4 : Integration main.lua

### 4.1 Nouveau flow du duel

```
Joueur A appuie A pres du ghost → duel_request
Joueur B accepte → duel_accept
Serveur envoie duel_warp aux deux joueurs

-- Phase "preparing"
Les deux joueurs echangent leurs parties (duel_party)
Les deux joueurs echangent leurs infos link player

-- Phase "starting"
Battle.startBattle(isMaster)
  → Appliquer ROM patches
  → Setup fake link players
  → Trigger Task_StartWiredCableClubBattle
  → Le jeu lance le combat nativement (VS screen, animations)

-- Phase "in_battle"
Battle.tick() chaque frame
  → Relay gBattleBufferA/B via TCP
  → Le jeu gere tout nativement (menus, animations, degats)

-- Phase "ending"
Battle.checkBattleEnd()
  → Restaurer ROM patches
  → Cleanup
  → Retour a l'overworld (gere nativement par le jeu)
```

### 4.2 Plus besoin de warp vers le colosseum ?

Avec l'approche PK-GBA, le combat link se lance **depuis n'importe ou**. Le jeu gere la transition vers l'ecran de combat tout seul. Pas besoin de teleporter les joueurs dans une salle speciale.

**Simplification majeure :** Supprimer toute la logique de warp duel (sWarpDestination, CB2_LoadMap, etc.). Le duel warp devient juste "lancer le combat link sur place".

**A garder :** Le warp reste utile si on veut placer les joueurs dans une salle specifique pour l'ambiance. C'est optionnel, pas un prerequis technique.

### 4.3 Handlers de messages reseau

**Nouveau handler pour les buffers :**

```lua
elseif message.type == "duel_buffer" then
    Battle.onRemoteBuffer(message.slot, message.battler, message.data, message.stage)

elseif message.type == "duel_stage" then
    Battle.onRemoteStage(message.stage)
```

---

## ETAPE 5 : UX amelioree (souris)

### 5.1 Context menu via mouse events

mGBA expose les evenements souris :

```lua
local lastMouseX, lastMouseY = 0, 0

callbacks:add("mouseMove", function(ev)
    lastMouseX = ev.x
    lastMouseY = ev.y
end)

callbacks:add("mouseButton", function(ev)
    if ev.button == C.MOUSE_BUTTON.SECONDARY and ev.state == C.INPUT_STATE.DOWN then
        -- Clic droit !
        local ghostUnderCursor = findGhostAt(lastMouseX, lastMouseY)
        if ghostUnderCursor then
            showContextMenu(lastMouseX, lastMouseY, ghostUnderCursor)
        end
    end
end)
```

### 5.2 Context menu overlay

**Dessiner via Painter API :**
- Rectangle semi-transparent avec bordure
- Options texte : "Invite to battle", "View profile", "Cancel"
- Detection de clic sur chaque option (hitbox rectangulaire)

### 5.3 Remplacement du trigger actuel

| Ancien trigger | Nouveau trigger |
|---------------|-----------------|
| Bouton A pres du ghost (< 2 tiles) | **Clic droit sur le ghost → context menu → "Invite to battle"** |

**Garder le trigger A en parallele** comme raccourci (pour ceux qui jouent au clavier/manette).

---

## ETAPE 6 : Modifications serveur

### 6.1 Nouveau handler duel_buffer

```javascript
case 'duel_buffer':
    // Relay le buffer au duel opponent
    if (client.duelOpponent) {
        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
            sendToClient(opponent, {
                type: 'duel_buffer',
                slot: message.slot,
                battler: message.battler,
                data: message.data,
                stage: message.stage
            });
        }
    }
    break;

case 'duel_stage':
    if (client.duelOpponent) {
        const opponent = clients.get(client.duelOpponent);
        if (opponent) {
            sendToClient(opponent, {
                type: 'duel_stage',
                stage: message.stage
            });
        }
    }
    break;
```

### 6.2 Supprimer duel_rng_sync

Le relay de buffers gere tout. Plus besoin de sync RNG separee.

---

## ETAPE 7 : Tests

### 7.0 Test discovery scripts
- [ ] find_battle_functions.lua capture les PC/LR pendant un combat dresseur
- [ ] ewram_battle_diff.lua trouve les blocs gBattleBufferA/B
- [ ] find_rom_functions.lua identifie les fonctions ROM critiques
- [ ] Toutes les adresses de 1.4 remplies dans config

### 7.1 Test ROM patching
- [ ] Les patches s'appliquent sans crash (emu.memory.cart0 write)
- [ ] Le jeu continue de tourner normalement apres les patches
- [ ] Les patches se restaurent correctement (valeurs originales)
- [ ] Pas de corruption apres restauration

### 7.2 Test battle trigger
- [ ] Task_StartWiredCableClubBattle se lance (via ASM ou callback2)
- [ ] Le jeu entre en mode combat (ecran VS, transition)
- [ ] L'adversaire link est reconnu (pas "no link partner")

### 7.3 Test buffer relay (2 joueurs)
- [ ] gBattleBufferA se lit correctement pendant le combat
- [ ] Les buffers sont envoyes/recus via TCP
- [ ] Les buffers ecrits cote distant sont reconnus par le jeu
- [ ] Le combat se deroule normalement (menus, attaques, animations)

### 7.4 Test combat complet
- [ ] Echange d'equipes fonctionne
- [ ] Le combat se deroule du debut a la fin
- [ ] Les deux joueurs voient les memes actions
- [ ] Le combat se termine proprement (victoire/defaite)
- [ ] Les ROM patches sont restaures

### 7.5 Test edge cases
- [ ] Deconnexion pendant le combat → cleanup propre
- [ ] Timeout de buffer (30 sec) → action par defaut
- [ ] Double battle (si supporte)
- [ ] Items en combat (si supporte)
- [ ] Mega Evolution / Z-Moves (Run & Bun specifique)

---

## Fichiers concernes

### A creer (nouveaux)
| Fichier | Description |
|---------|-------------|
| `scripts/discovery/find_battle_functions.lua` | Watchpoint discovery des fonctions battle ROM |
| `scripts/discovery/ewram_battle_diff.lua` | Diff EWRAM avant/apres combat |
| `scripts/discovery/find_rom_functions.lua` | Scan ROM par signatures |

### A reecrire entierement
| Fichier | Description |
|---------|-------------|
| `client/battle.lua` | Module PvP complet (ROM patching + buffer relay) |

### A modifier
| Fichier | Modifications |
|---------|--------------|
| `client/main.lua` | Nouveau flow duel (plus simple), mouse events, supprimer AI interception/RNG sync |
| `config/run_and_bun.lua` | Nouvelle section `battle_link` avec toutes les adresses |
| `server/server.js` | Handler `duel_buffer`, `duel_stage`, supprimer `duel_rng_sync` |
| `client/duel.lua` | Ajouter trigger clic droit (en plus du bouton A) |

### Optionnel a supprimer
| Fichier | Raison |
|---------|--------|
| Ancien code AI interception dans battle.lua | Remplace par buffer relay |
| Ancien code RNG sync dans main.lua | Plus necessaire |

---

## Reference : Code source pokeemerald-expansion

Les fonctions critiques sont dans ces fichiers (deja clones dans `refs/pokeemerald-expansion/`) :

| Fichier source | Fonctions |
|----------------|-----------|
| `src/cable_club.c:833` | `Task_StartWiredCableClubBattle()` |
| `src/battle_main.c:840` | `CB2_HandleStartBattle()`, `CB2_InitBattle()` |
| `src/battle_controllers.c:477` | `PrepareBufferDataTransfer()`, `PrepareBufferDataTransferLink()` |
| `src/battle_controller_player.c:166` | `PlayerBufferExecCompleted()` |
| `src/battle_controller_link_opponent.c:262` | `LinkOpponentBufferExecCompleted()` |
| `src/link.c:999` | `GetMultiplayerId()` |
| `src/link.c:313` | `InitLocalLinkPlayer()` |
| `src/task.c:27` | `CreateTask()` |
| `src/overworld.c:1892` | `CB2_ReturnToField()` |
| `include/battle.h:370` | `struct BattleResources` (gBattleBufferA/B = 4 x 512 bytes) |
| `include/battle.h:1068` | `gBattleCommunication` declaration |

---

## Reference : PK-GBA Multiplayer

Le code de reference est dans [GBA-PK-multiplayer](https://github.com/TheHunterManX/GBA-PK-multiplayer).

**Fichiers cles :**
- `GBA-PK_Client.lua` et `GBA-PK_Server.lua` (15253 lignes chacun, identiques sauf `ServerType`)
- Fonction `InitiateBattle()` (ligne 12281-12666) : applique tous les ROM patches
- Fonction `Battlescript()` (ligne 12668-13291) : state machine stages 0-9, buffer relay
- Script 37 "Initiate Link Player" (ligne 14411-14418) : ASM inline pour appeler CreateTask

**Attention :** PK-GBA supporte uniquement les ROMs vanilla (R/S/FR/LG/E). Les adresses sont differentes pour Run & Bun (pokeemerald-expansion). Tout le code est un template a adapter, pas du copier-coller.

---

**Derniere mise a jour :** 2026-02-06
