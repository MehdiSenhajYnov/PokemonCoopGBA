# Pokémon Unified Co-op Framework (mGBA + Lua)

## 1. CONTEXTE ET VISION

Framework générique pour multijoueur "Seamless" sur ROM et ROM hacks GBA Pokémon.

### Objectifs
- **Ghosting**: Voir les autres joueurs en temps réel (Overlay)
- **Generic Architecture**: Support multi-jeux via profils d'offsets
- **Synchronized Duel (PvP Battle)**: Combat PvP Link via buffer relay (pas de warp physique)

### Cible Prioritaire
**Pokémon Run & Bun** - ROM hack avancé basé sur **pokeemerald-expansion** (RHH). Créateur: dekzeh.

**Architecture connue**: Run & Bun est construit sur le projet pokeemerald-expansion (ROM Hacking Hideout), qui étend Émeraude vanilla avec:
- Gen 1-8 Pokémon (1234 espèces dont formes), 782 attaques, 267 abilities
- Battle Engine V2 (physical/special split, Mega, Z-Moves, Dynamax)
- Structs modifiées (hidden nature, 3-ability slots, tera type dans expansion)

**Données de référence locales** (clonées dans `refs/`):
- `refs/pokemon-run-bun-exporter` — Script Lua avec adresses party validées par la communauté
- `refs/runandbundex` — Tables de données officielles (species, moves, abilities) par dekzeh
- `refs/pokeemerald-expansion` — Code source decomp (structs, constantes, headers)

## 1B. RÈGLE FONDAMENTALE: RECHERCHE AVANT DÉVELOPPEMENT

**⚠️ OBLIGATOIRE — Ne JAMAIS coder sans avoir vérifié la documentation officielle.**

### Principe
Avant d'écrire du code utilisant une API externe (mGBA Lua, Node.js, LuaSocket, etc.), il faut **systématiquement**:
1. **Rechercher** la documentation officielle à jour (WebSearch + WebFetch)
2. **Lire attentivement** les signatures de fonctions, paramètres, types de retour
3. **Vérifier la version** — les APIs changent entre versions (ex: mGBA 0.10 vs 0.11)
4. **Trouver des exemples fonctionnels** dans les repos officiels ou la communauté
5. **Ne JAMAIS deviner** un nom de fonction ou un paramètre — toujours confirmer dans la doc

### Pourquoi
- L'API Lua de mGBA n'est PAS du Lua standard — elle a ses propres objets (`canvas`, `callbacks`, `emu`, `console`)
- Les fonctions changent entre versions (ex: le dessin overlay n'existe PAS dans mGBA 0.10, seulement 0.11+)
- Deviner les appels API mène à des scripts qui crashent silencieusement

### Références API clés
| API | URL Documentation | Notes |
|-----|-------------------|-------|
| mGBA 0.11+ Scripting (dev) | https://mgba.io/docs/dev/scripting.html | Canvas, Painter, Image, CanvasLayer, callbacks |
| mGBA 0.10 Scripting (stable) | https://mgba.io/docs/scripting.html | PAS de support overlay |
| mGBA example scripts | https://github.com/mgba-emu/mgba/tree/master/res/scripts | Exemples officiels fonctionnels |
| Node.js net module | https://nodejs.org/api/net.html | TCP server/client |
| mGBA Socket API | https://mgba.io/docs/dev/scripting.html | socket.connect(), sock:send/receive (intégré, PAS LuaSocket) |

### Version mGBA requise
- **Minimum: mGBA 0.11+ dev build** pour le support overlay (canvas API)
- Build actuel du projet: **8977** (2026-02-02)
- Les dev builds Windows: `https://s3.amazonaws.com/mgba/mGBA-build-latest-win64.7z`

## 2. STACK TECHNIQUE

- **Client**: Script Lua s'exécutant dans mGBA (socket TCP intégré de mGBA, pas de proxy)
- **Serveur**: Node.js + TCP Socket pour relais de données
- **Communication**: JSON via TCP brut (socket intégré mGBA → serveur Node.js directement)
- **Cible**: Pokémon Run & Bun (moteur Émeraude fortement modifié)

## 3. ARCHITECTURE MODULAIRE

### 3 Couches Principales

#### Hardware Abstraction Layer (HAL)
- Gestion sécurisée de la mémoire
- Pointers, DMA handling
- Sanity Checks

#### Core Engine
- Gestion serveur local
- Envoi/réception positions
- Logique d'overlay

#### Game Profiles
- Configuration ROM-spécifique
- Adresses RAM par Game ID
- Support multi-ROM

## 4. SPÉCIFICATIONS TECHNIQUES

### A. Lecture Mémoire Sécurisée
- `readSafePointer(base, offsets)` avec pcall
- Vérification plage WRAM GBA (0x02000000 - 0x0203FFFF)
- Gestion pointeurs dynamiques (SaveBlock1/2)
- Protection contre DMA

### B. Système de Ghosting
**Données synchronisées:**
- PlayerX, PlayerY
- MapID, MapGroup
- FacingDirection

**Positionnement:** Relatif au centre de l'écran (pas d'offsets caméra).
Le joueur GBA est toujours centré à l'écran (120, 80). Le ghost est positionné par delta de tiles: `ghostScreen = (112, 72) + (ghostTile - playerTile) * 16`.

**Features:**
- Interpolation de mouvement (FIFO waypoint queue avec catch-up adaptatif doux `duration / (1 + 0.5*(N-1))`, 8% padding, os.clock realDt)
- Rendu via Painter API de mGBA (canvas overlay)
- Sprites extraits dynamiquement de VRAM/OAM/Palette (tous états visuels: marche, course, vélo, surf)
- Tailles sprite variables: 16x32 (marche/course) et 32x32 (vélo) détectées automatiquement via OAM shape/sizeCode
- Détection sprite joueur: tri par tileIndex le plus bas + OAM priority (bat NPCs et reflets d'eau), transition instantanée entre états
- Fallback vers carré semi-transparent vert (14x14) si extraction VRAM échoue
- Ghosts opaques (GHOST_ALPHA=0xFF) — l'occlusion BG gère la profondeur
- Y-sorting: ghosts triés par Y croissant (depth order correct entre ghosts)
- BG layer occlusion: les tiles du layer BG1 (toits, arbres) sont redessinées par-dessus les ghosts via Painter API
- Label joueur au-dessus du ghost

### C. Duel System (PvP Battle Trigger)
**Trigger:** Bouton A près du ghost (< 2 tiles, edge-detect)

**Workflow:**
1. Joueur A appuie sur A près d'un ghost → `duel_request` au serveur
2. Serveur forward au joueur cible uniquement → prompt affiché
3. Joueur B accepte (A) ou refuse (B)
4. Si accepté → serveur envoie `duel_warp` aux deux joueurs (isMaster flag)
5. **Pas de warp physique** — CB2_InitBattle prend le plein écran directement (GBA-PK style)
6. Échange de party et player info via TCP (`duel_party` + `duel_player_info`), suivi d'un handshake `duel_ready`
7. Battle engine link lance le combat avec buffer relay

**Battle Entry (GBA-PK style — no physical warp):**
- No map warp needed — CB2_InitBattle takes over full screen from any overworld position
- Loadscript(37) triggers battle via GBA script engine (Task_StartWiredCableClubBattle)
- Fallback: direct callback2 write to CB2_InitBattle after 30 frame timeout
- After battle, savedCallback = CB2_ReturnToField returns to overworld at original position
- Player stays on their map throughout — no colosseum warp

**Disconnect safety:** pendingDuel nettoyé au disconnect, `duel_cancelled` envoyé si nécessaire

## 5. STRUCTURE DU PROJET

```
PokemonCoop/
├── CLAUDE.md                 # Ce fichier
├── server/                   # Serveur Node.js
│   ├── package.json
│   ├── server.js
│   └── README.md
├── client/                   # Script Lua mGBA
│   ├── main.lua
│   ├── hal.lua              # Hardware Abstraction Layer (WRAM + IWRAM + VRAM/OAM/Palette + BG I/O registers, static + dynamic)
│   ├── network.lua          # Direct TCP client (mGBA socket API, auto-reconnect with backoff)
│   ├── render.lua           # Ghost player rendering (Painter API + camera correction + occlusion call)
│   ├── sprite.lua           # VRAM sprite extraction (OAM scan, tile decode, palette, cache, network sync)
│   ├── occlusion.lua        # BG layer occlusion (reads BG1 tilemap, redraws cover tiles over ghosts via Painter)
│   ├── interpolate.lua      # Smooth ghost movement (FIFO waypoint queue + adaptive catch-up)
│   ├── duel.lua             # Duel warp system (trigger, request/accept UI, proximity detection)
│   ├── battle.lua           # PvP battle system (Link Battle Emulation: buffer relay, ROM patching, state machine)
│   ├── core.lua             # Core Engine
│   └── README.md
├── config/                   # Profils ROM
│   ├── run_and_bun.lua      # Profil principal (adresses validées + constantes)
│   ├── emerald_us.lua       # Référence vanilla
│   ├── radical_red.lua      # Future extension
│   └── unbound.lua          # Future extension
├── refs/                     # Repos de référence (git-ignored, clonés localement)
│   ├── pokemon-run-bun-exporter/  # Adresses party validées (Lua)
│   ├── runandbundex/              # Données officielles R&B (species, moves, abilities)
│   └── pokeemerald-expansion/     # Source decomp (structs, headers, constantes)
├── scripts/                  # Scripts de scan mémoire mGBA
│   ├── README.md            # Guide d'utilisation
│   ├── testing/             # Autonomous test framework
│   │   ├── runner.lua       # Test runner (save state, suites, JSON output, screenshots)
│   │   ├── assertions.lua   # Assertion library (assertEqual, assertRange, etc.)
│   │   ├── run_all.lua      # Entry point (mGBA --script target)
│   │   └── suites/          # Test suites (memory, rom_patches, battle, warp, network)
│   ├── scanners/            # Scripts de scan actifs
│   ├── discovery/           # Battle system discovery scripts (P3_11)
│   ├── debug/               # Scripts de debug
│   └── archive/             # Scripts archivés
└── docs/                     # Documentation
    ├── MEMORY_GUIDE.md      # Guide complet de scan mémoire
    ├── RUN_AND_BUN.md       # Documentation offsets Run & Bun
    ├── TESTING.md
    └── CHANGELOG.md
```

## 6. ROADMAP

### Phase 1: Foundation (DONE)
- [x] Structure projet
- [x] Serveur TCP minimal
- [x] Script Lua squelette
- [x] Lecture position Émeraude vanilla (référence)
- [x] **Scripts de scan mémoire créés** (scan_*.lua dans scripts/)
- [x] Créer profil run_and_bun.lua template avec support static/dynamic
- [x] HAL amélioré pour supporter mode dynamique
- [x] ROM detection pour Run & Bun
- [x] **Scan mémoire exécuté et offsets trouvés** (2026-02-02)
- [x] **Offsets Run & Bun remplis dans config/run_and_bun.lua** (statiques)
- [x] **Implémenter module network.lua (TCP client)** (2026-02-02)
- [x] **Intégrer network.lua dans main.lua** (2026-02-02)
- [x] **Test connexion client-serveur bout en bout** (2026-02-03)

### Phase 2: Ghosting (DONE)
- [x] Synchronisation positions
- [x] Offsets caméra trouvés (IWRAM 0x03005DFC, 0x03005DF8)
- [x] Overlay graphique (render.lua) — Painter API, map filtering
- [x] Positionnement ghost corrigé — approche relative (screen center + delta tiles)
- [x] Test 2 joueurs — ghosts visibles et correctement positionnés sur toutes les cartes
- [x] Interpolation mouvement — animate-toward-target (lerp from current to new snapshot, auto-adaptive duration)
- [x] Taux d'envoi adaptatif (0 en idle, envoi à chaque changement de tile, immédiat sur changement de map)
- [x] Correction caméra sub-tile (tracking delta camera offsets pour scrolling fluide pendant animations marche)
- [x] Rendu sub-tile (math.floor pixel-perfect, marqueur direction, couleurs debug par état)
- [x] Gestion déconnexion (reconnexion auto avec backoff, server broadcast, UI statut)
- [x] Ghost sprite rendering (extraction VRAM/OAM/Palette, reconstruction Image, sync réseau)
- [x] Sprite detection reliability (lowest-tileIndex sort + OAM priority, supports 16x32 walk and 32x32 bike)
- [x] Ghost semi-transparency (removed — ghosts now fully opaque, occlusion handles depth)
- [x] Ghost Y-sorting (drawAllGhosts sorts by Y ascending, correct depth order between ghosts)
- [x] BG layer occlusion (occlusion.lua — reads BG1 tilemap, redraws cover tiles over ghosts via Painter API)
- [x] Waypoint queue interpolation (FIFO queue + adaptive catch-up `BASE_DURATION / queueLength`, exact path fidelity at any speedhack rate)
- [x] Interpolation smoothness (receive-before-step reorder, os.clock realDt, timestamp>hint priority, 1.08x padding, soft catch-up curve)

### Phase 3: Duel Warp (DONE)
- [x] Système de trigger (duel.lua — proximity detection + A button edge detect)
- [x] Synchronisation téléportation (server coordinates both players → duel_warp)
- [x] Verrouillage inputs (180 frames lock after warp)
- [x] Interface utilisateur (Painter API overlay — request prompt + accept/decline)
- [x] Disconnect handling (pendingDuel cleanup, duel_cancelled message)
- [x] No physical warp — CB2_InitBattle takes over full screen directly (GBA-PK style)

### Phase 3B: PvP Battle System — Link Battle Emulation (CURRENT)
- [x] Battle module architecture (client/battle.lua — Link Battle Emulation: buffer relay, ROM patching, state machine)
- [x] Memory scanner script (scripts/scan_battle_addresses.lua — scan gBattleTypeFlags, gEnemyParty, etc.)
- [x] Config placeholder (config/run_and_bun.lua — battle section with nil addresses)
- [x] Server protocol (duel_party, duel_buffer, duel_stage, duel_end messages)
- [x] Main.lua integration (phases: waiting_party, preparing_battle, in_battle, waiting_master_outcome)
- [x] Battle addresses scanned and filled in config/run_and_bun.lua
- [x] Fix 5 PvP bugs (P3_10B): server coords, triggerMapLoad, battle trigger, isFinished transition tracking, getOutcome HP fallback
- [x] HAL.readInBattle() + inBattle tracking in main.lua
- [x] **Party addresses corrected** via cross-ref with pokemon-run-bun-exporter (gPlayerParty=0x02023A98, gEnemyParty=0x02023CF0)
- [x] **Reference data repos cloned** (pokemon-run-bun-exporter, runandbundex, pokeemerald-expansion)
- [x] **Config enriched** with Pokemon struct constants, battle flags, outcome codes from decomp
- [x] **P3_11 Rewrite**: battle.lua rewritten for Link Battle Emulation (buffer relay, ROM patching, state machine)
- [x] **Discovery scripts** created (scripts/discovery/: test_cart0_write, find_battle_functions, ewram_battle_diff, find_rom_functions)
- [x] **Server updated** for duel_buffer/duel_stage (replaced duel_choice/duel_rng_sync)
- [x] **Config restructured** with battle_link section for discovery targets
- [x] Cart0 write confirmed working (mGBA ROM = RAM, no MMU)
- [x] **All battle_link addresses found** via Python ROM scanners + runtime verification
- [x] **gBattleTypeFlags CORRECTED** (0x020090E8→0x02023364 via CB2_InitBattle disassembly)
- [x] **CB2_InitBattle found** (0x080363C1, 204 bytes, 8 literal pool refs)
- [x] **Config fully populated** with CB2_InitBattle, SetMainCallback2, gBattleCommunication
- [x] **battle.lua rewritten** for proper init chain (CB2_InitBattle, callback1 save/restore)
- [x] **Battle screen WORKING** (2026-02-08): Full Pokemon sprites, health boxes, Fight/Bag/Pokemon/Run menu
- [x] **Critical fix**: Clear BATTLE_TYPE_LINK + swap ctrl[1] to OpponentBufferRunCommand after BattleMainCB2
- [x] **gBattlerControllerFuncs found** in IWRAM at 0x03005D70 (was misidentified as EWRAM)
- [x] **MarkBattler exec local patches** (added then REMOVED — engine uses bits 28-31 for link exec natively)
- [x] **Real PvP buffer relay** (2026-02-10): GBA-PK HOST/CLIENT protocol via duel_buffer_cmd/duel_buffer_resp TCP
- [x] **Auto-fight** for automated testing (A button press every 15 frames during HTASS)
- [x] **localPartyBackup** to counter Cases 4/6 gPlayerParty overwrite
- [x] **Force-end** when opponent's battle ends (duel_end mirrored outcome: win↔lose)
- [x] **2-player PvP end-to-end VERIFIED** (2026-02-08): both enter battle, exchange moves, both exit cleanly
- [x] **DoBattleIntro fix** (2026-02-09→10): LINK stays active throughout. IS_MASTER only on HOST eliminates DMA corruption root cause.
- [x] **NOP HandleLinkBattleSetup** (2 call sites) + NOP TryReceiveLinkBattleData in VBlank — prevents link buffer tasks and VBlank corruption
- [x] **InitBtlControllersInternal slave path** — CLIENT follows slave path (reversed positions/controllers), gBattleMainFunc = BeginBattleIntro written by Lua
- [x] **Loadscript(37)** battle entry via GBA script engine (GBA-PK style) + direct write fallback
- [x] **initLocalLinkPlayer** — reads SaveBlock2 for real player name on VS screen
- [x] **killLinkTasks** — scans gTasks IWRAM, kills link-range tasks every 30 frames
- [x] **gBattleStruct found** (0x02023A0C ptr, eventState.battleIntro at offset 0x2F9)
- [x] **PvP battle REPRODUCIBLY WORKING** (2026-02-09): both players enter, intro completes, battle resolves, outcomes detected
- [x] **Outcome detection FIXED** (2026-02-09): master-authoritative — slave waits for master's duel_end and mirrors outcome. gBattleOutcome cached at detection time.
- [x] **Opponent name exchange** via `duel_player_info` TCP message (Battle.getLocalPlayerInfo/setOpponentInfo, cachedOpponentName in maintainLinkPlayers)
- [x] **Battle.forceEnd()** injects CMD_GET_AWAY_EXIT (0x37) into bufferA + sets exec flags. main.lua calls forceEnd on duel_end/disconnect during in_battle.
- [x] **Forward declarations** fix: initLocalLinkPlayer and triggerLoadscript37 declared before state machine, defined after startLinkBattle
- [x] **duel_ready handshake** (2026-02-10): 3-phase waiting_party (EXCHANGE→READY→GO) fixes VS screen "RIVAL" name race condition
- [x] **Context vars found** (2026-02-10): gBattlerAttacker=0x0202358C, gBattlerTarget=0x0202358D, gEffectBattler=0x0202358F, gAbsentBattlerFlags=0x02023591 (BSS layout analysis from battle_main.c anchors)
- [x] **Stuck detection** (2026-02-10): relay timeout (600f/10s) + ping timeout (900f/15s) + forceEnd multi-frame 0x37 injection (GBA-PK approach)
- [x] **forceEnd rewrite** (2026-02-10): forceEndPending flag + 30-frame 0x37 re-injection loop (was single-shot). Safety timeout 5min→1min.
- [x] **Per-frame buffer re-write** (2026-02-10): bufferA re-written every frame on CLIENT while controller processes (activeCmd pattern). HOST re-writes CLIENT's bufferB every frame (lastClientBufB). Fix: onRemoteBufferCmd now stores bufB from HOST.
- [x] **4 bug fixes** (2026-02-10): (1) maintainLinkState no longer zeroes vsScreenHealthFlagsLo — VS screen pokeballs correct, (2) ~~gBattlerControllerFuncs cleared at comm skip~~ REVERTED — clearing after case 1 nulls controllers → crash, (3) gBlockReceivedStatus starts at 0x00 not 0x0F (GBA-PK staging), (4) context vars written once per command not per-frame (ctxWritten flag — prevents overwriting engine state during multi-frame commands)
- [x] **Fix gBattlerControllerFuncs null crash** (2026-02-10): Removed comm skip clear of gBattlerControllerFuncs — InitBtlControllersInternal sets them (HOST=master path, CLIENT=slave path with reversed positions)
- [x] **CLIENT 100% HOST-driven** (2026-02-10): Removed Priority 2 (local byte3 handling) + `byte3 = 0` blanket clear. CLIENT stays blocked on byte3 until HOST relays command via TCP. Fixes: (1) byte3 blanket clear skipping commands, (2) double-processing local then HOST, (3) processingCmd race condition.
- [x] **Optional fixes** (2026-02-10): maintainLinkState(0x0F→0x00) in MAIN_LOOP every-frame + gBattleTypeFlags OR merge (preserves engine-set bits like LINK_IN_BATTLE)
- [x] **CRITICAL: R&B comm skip 12→7** (2026-02-11): R&B CB2_HandleStartBattle has 11 states (0-10), NOT 17 like expansion. Old comm=12 was OUT OF RANGE (CMP #10, BHI→exit), so SetMainCallback2(BattleMainCB2) at state 10 never ran → RunTextPrinters() never called → empty textboxes after "Go [PokemonName]!". Fix: skip to state 7 (InitBattleControllers). States 7-10 auto-advance with existing ROM patches.
- [x] **8 NOP memcpy patches** (2026-02-11): NOP'd 4 memcpy BL calls in CB2_HandleStartBattle states 4/6 that copy from gBlockRecvBuffer (garbage) into gPlayerParty/gEnemyParty. States are skipped by comm advancement (2→7), NOP'd as defense-in-depth.
- [x] **CLIENT slave path fix** (2026-02-11): Removed InitBtlControllersInternal NOP — BEQ skips ENTIRE master path (controllers+positions), not just BeginBattleIntro. CLIENT follows slave path (reversed positions matching relay mapping). gBattleMainFunc = BeginBattleIntro written by Lua.
- [ ] Multi-turn PvP battles (current: 1-turn KO due to save state Pokemon levels)
- [ ] BATTLE_FLAGS system (items, exp, heal, level cap, overwrite — GBA-PK feature parity)

### Phase 4: Multi-ROM Support
- [ ] Profils additionnels (Radical Red, Unbound)
- [ ] Auto-détection ROM
- [ ] Configuration dynamique

### Phase 5: Polish
- [ ] Gestion erreurs robuste
- [ ] Optimisation performance
- [ ] Documentation complète
- [ ] Interface configuration

### Autonomous Test Framework (DONE)
- [x] Test runner (`scripts/testing/runner.lua`) — save state + suites + JSON + screenshots
- [x] Assertions library (`scripts/testing/assertions.lua`)
- [x] 5 test suites: memory, rom_patches, battle, warp, network
- [x] Async multi-frame test support (waitFrames + done)
- [x] Auto-screenshot on failure

**Run tests:** `mGBA.exe --script scripts/testing/run_all.lua "rom/Pokemon RunBun.gba"`
**Results:** `test_results.json` + `test_screenshots/`
**Kill after:** `powershell -Command "Stop-Process -Name mGBA -Force -ErrorAction SilentlyContinue"`

## 7. NOTES TECHNIQUES

### Adresses Mémoire

#### Pokémon Émeraude US (Base de référence)
- **PlayerX**: 0x02024844
- **PlayerY**: 0x02024846
- **MapID**: 0x02024842
- **MapGroup**: 0x02024843
- **WRAM Range**: 0x02000000 - 0x0203FFFF

**⚠️ IMPORTANT pour Run & Bun:**
Ces adresses sont celles d'Émeraude vanilla. Run & Bun modifiant énormément le code, ces offsets sont à considérer comme des POINTS DE DÉPART pour la recherche, pas des valeurs définitives. Il faudra utiliser Cheat Engine ou des outils de memory scanning pour trouver les vrais offsets de Run & Bun.

#### Pokémon Run & Bun (Trouvés 2026-02-02/05)

**Overworld (scanner mGBA, 2026-02-02/03):**
- **PlayerX**: 0x02024CBC (16-bit, EWRAM)
- **PlayerY**: 0x02024CBE (16-bit, EWRAM)
- **MapGroup**: 0x02024CC0 (8-bit, EWRAM)
- **MapID**: 0x02024CC1 (8-bit, EWRAM)
- **FacingDirection**: 0x02036934 (8-bit, EWRAM)
- **CameraX**: IWRAM+0x5DFC (s16, gSpriteCoordOffsetX)
- **CameraY**: IWRAM+0x5DF8 (s16, gSpriteCoordOffsetY)

**Party (cross-ref pokemon-run-bun-exporter, 2026-02-05):**
- **gPlayerParty**: 0x02023A98 (600 bytes, 6×100)
- **gPlayerPartyCount**: 0x02023A95 (8-bit)
- **gEnemyParty**: 0x02023CF0 (= gPlayerParty + 0x258)
- **gPokemonStorage**: 0x02028848 (PC box storage)

**Battle state (corrected 2026-02-07/10 via ROM disassembly):**
- **gBattleTypeFlags**: 0x02023364 (32-bit)
- **gMainInBattle**: 0x03002AF9 (gMain+0x439, IWRAM, bitfield bit 1)
- **gBattleCommunication**: 0x0202370E (u8[8], MULTIUSE_STATE at [0])
- **gRngValue**: IWRAM 0x03005D90 (32-bit)
- **CB2_InitBattle**: 0x080363C1 (ROM, 204 bytes) — proper battle init entry point
- **CB2_InitBattleInternal**: 0x0803648D (ROM, ~4KB) — multi-frame init state machine
- **CB2_HandleStartBattle**: 0x08037B45 (ROM, ~0x620 bytes) — 11 states (0-10), NOT 17 like expansion
- **CB2_BattleMain (BattleMainCB2)**: 0x0803816D (ROM) — CORRECTED (was 0x08094815)
- **SetMainCallback2**: 0x08000544 (ROM)
- **gBattlerAttacker**: 0x0202358C (u8, BSS layout from battle_main.c)
- **gBattlerTarget**: 0x0202358D (u8)
- **gEffectBattler**: 0x0202358F (u8)
- **gAbsentBattlerFlags**: 0x02023591 (u8)
- **gBattlescriptCurrInstr**: 0x02023594 (u32 ptr, anchor — 548 ROM refs)

**Warp system (corrected 2026-02-07):**
- **gMain.callback2**: 0x030022C4 (IWRAM, gMain+0x04) — CORRECTED (was 0x0202064C EWRAM)
- **CB2_LoadMap**: 0x080A3FDD (ROM) — CORRECTED (was 0x08007441 = SpriteCallbackDummy)
- **CB2_Overworld**: 0x080A89A5 (ROM)

**Mode**: STATIQUE (pas de pointeurs dynamiques)

**Pokemon struct**: 100 bytes party / 80 bytes box, encrypted substructs (XOR otId^personality, personality%24 permutation). Hidden nature R&B-specific (bits 16-20 growth substruct, value 26=PID nature). 3 ability slots (2 bits at ss3[2] bits 29-30).

### Sources d'adresses

| Source | Fiabilité | Contenu |
|--------|-----------|---------|
| `refs/pokemon-run-bun-exporter` | Haute (testé communauté) | gPlayerParty, gPlayerPartyCount, gPokemonStorage, struct layout |
| `refs/pokeemerald-expansion` | Haute (source decomp) | Structs, constantes, battle flags |
| Scanner mGBA | Moyenne (scan unique) | gBattleTypeFlags, gRngValue, callbacks |
| `refs/runandbundex` | Haute (officiel dekzeh) | Species/moves/abilities data tables |

### Méthodologie pour trouver les offsets

**Approche recommandée** (mise à jour 2026-02-05):

1. **D'abord**: Chercher dans les références existantes (`refs/`) — adresses validées gratuitement
2. **Ensuite**: Ghidra + symboles pokeemerald-expansion pour analyse statique
3. **Enfin**: Scanner mGBA en live si les deux premières méthodes échouent

### TCP Protocol (JSON-based)
Messages envoyés ligne par ligne (délimités par `\n`)

```json
{
  "type": "position",
  "playerId": "unique-id",
  "data": {
    "x": 10,
    "y": 15,
    "mapId": 3,
    "mapGroup": 0,
    "facing": 1
  }
}
```

**Sprite synchronisation:**
```json
{
  "type": "sprite_update",
  "playerId": "unique-id",
  "data": {
    "width": 16,
    "height": 32,
    "__comment": "width/height are dynamic: 16x32 for walk/run, 32x32 for bike",
    "hFlip": false,
    "tiles": [0, 15, 240, ...],
    "palette": [0, 4294901760, ...]
  }
}
```
Sent only when sprite changes (tile index, palette bank, or flip changes).

**Duel protocol (no physical warp — GBA-PK style, 3-phase handshake):**
```json
{"type":"duel_request","targetId":"player_xxx"}
{"type":"duel_accept","requesterId":"player_xxx"}
{"type":"duel_decline","requesterId":"player_xxx"}
{"type":"duel_warp","isMaster":true}
{"type":"duel_declined","playerId":"player_xxx"}
{"type":"duel_cancelled","requesterId":"player_xxx"}
{"type":"duel_ready"}
```
After `duel_warp`, the `waiting_party` phase uses a 3-phase handshake: (1) EXCHANGE: both send `duel_party` + `duel_player_info`, (2) READY: when both received, send `duel_ready`, (3) GO: when opponent's `duel_ready` received, inject party and start battle. This prevents the race condition where `setOpponentInfo` was called before `duel_player_info` arrived.

**Player info exchange (VS screen name):**
```json
{"type":"duel_player_info","name":"ASH","gender":0,"trainerId":12345}
```
Sent during `waiting_party` phase. Server relays to duel opponent. Used by `Battle.setOpponentInfo()` for VS screen real player name.

**PvP battle protocol (v8 — HOST/CLIENT Buffer Relay):**
```json
{"type":"duel_party","data":[/* 600 bytes as array */]}
{"type":"duel_buffer_cmd","battler":0,"bufA":[/* 256 bytes */],"ctx":{"attacker":0,"target":1}}
{"type":"duel_buffer_resp","battler":0,"bufB":[/* 256 bytes */]}
{"type":"duel_stage","stage":3}
{"type":"duel_stage","stage":"mainloop_ready"}
{"type":"duel_end","outcome":"win"}
{"type":"duel_opponent_disconnected","playerId":"player_xxx"}
```

**Note**: TCP brut via l'API socket intégrée de mGBA (pas LuaSocket — c'est l'implémentation propre à mGBA)

## 8. DÉPENDANCES

### Serveur
- Node.js 18+
- net (built-in TCP library)

### Client
- mGBA 0.11+ dev build (REQUIS pour overlay/canvas API + socket TCP intégré)
- Support Lua activé
- Socket TCP via API mGBA intégrée (socket.connect, sock:send, sock:receive)
- Custom JSON encoder/decoder (built-in, no external dependencies)
- Pas de proxy ni de dépendance externe côté client

## 9. SÉCURITÉ

- Validation de toutes les lectures mémoire
- Protection contre écritures hors limites
- Timeouts sur communications réseau
- Sanity checks sur coordonnées

## 10. RESSOURCES

### Documentation
- [mGBA Scripting API](https://mgba.io/docs/scripting.html) - API Lua pour mGBA
- [pokeemerald-expansion](https://github.com/rh-hideout/pokeemerald-expansion) - Base code de Run & Bun (structs, constantes, battle engine)
- [Pokémon Emerald Decomp](https://github.com/pret/pokeemerald) - Référence vanilla Émeraude
- [Node.js TCP/Net](https://nodejs.org/api/net.html) - Documentation TCP Node.js

### Références Run & Bun spécifiques (clonées dans refs/)
- [pokemon-run-bun-exporter](https://github.com/luisvega23/pokemon-run-bun-exporter) - Adresses party validées + code lecture Pokémon
- [runandbundex](https://github.com/dekzeh/runandbundex) - Tables données officielles (species, moves, abilities, wild encounters)
- [PokeCommunity Thread](https://www.pokecommunity.com/threads/pok%C3%A9mon-run-bun-v1-07.493223/) - Page officielle Run & Bun

### Outils Essentiels
- **mGBA 0.11+ dev build** (CRITIQUE) - Émulateur avec console Lua + canvas API pour overlay
- **Ghidra + GBA loader** - Pour analyse statique ROM (trouver adresses battle system restantes)
- **PKHex** - Pour ROM exploration (structures de données)

### Notes sur Run & Bun
- Construit sur **pokeemerald-expansion** (RHH) — structs expansion sont la référence correcte
- 1234 espèces (Gen 1-8 + formes), 782 moves, 267 abilities
- Trade evolutions converties en level-up (Haunter→Gengar lvl 40, Kadabra→Alakazam lvl 36, etc.)
- Hidden Nature system (champ custom dans growth substruct)
- Offsets décalés vs vanilla Émeraude (PlayerX: +0x878, Facing: +0x120EC)
- Mode STATIQUE confirmé (pas de pointeurs dynamiques SaveBlock)

---

**Dernière mise à jour**: 2026-02-11
**Version**: 0.7.6-alpha
**Status**: Phase 3B - PvP Battle System (FIX: CLIENT slave path — reversed positions, gBattleMainFunc via Lua)
