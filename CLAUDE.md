# Pokémon Unified Co-op Framework (mGBA + Lua)

## 1. CONTEXTE ET VISION

Framework générique pour multijoueur "Seamless" sur ROM et ROM hacks GBA Pokémon.

### Objectifs
- **Ghosting**: Voir les autres joueurs en temps réel (Overlay)
- **Generic Architecture**: Support multi-jeux via profils d'offsets
- **Synchronized Duel (Warp Mode)**: Téléportation synchronisée dans une salle de combat Link

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

### C. Duel Warp (Feature Signature)
**Trigger:** Bouton A près du ghost (< 2 tiles, edge-detect)

**Workflow:**
1. Joueur A appuie sur A près d'un ghost → `duel_request` au serveur
2. Serveur forward au joueur cible uniquement → prompt affiché
3. Joueur B accepte (A) ou refuse (B)
4. Si accepté → serveur envoie `duel_warp` aux deux joueurs avec coords différentes
5. Warp via save state hijack (mode principal) ou door interception (fallback)
6. Verrouillage inputs pendant le chargement (5 secondes timeout)
7. Placement dans MAP_BATTLE_COLOSSEUM_2P (mapGroup=28, mapId=24)
   - Player A: (3, 5) | Player B: (10, 5)

**Warp Mechanism (save state hijack):**
- WRITE_CHANGE watchpoint on gMain.callback2 detects natural warps (door transitions)
- First natural warp: capture "golden state" (clean mid-warp emulator state via `emu:saveStateBuffer()`)
- Duel warp: save 16KB SaveBlock1 → load golden state → restore SaveBlock1 → write duel destination
- CB2_LoadMap executes in clean state → no freeze
- Door fallback: if no golden state yet, intercept next door warp and redirect to duel room

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
│   ├── battle.lua           # PvP battle system (party injection, AI interception, RNG sync)
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
│   ├── scanners/            # Scripts de scan actifs
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

### Phase 2: Ghosting (CURRENT)
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
- [x] Duel room: MAP_BATTLE_COLOSSEUM_2P (mapGroup=28, mapId=24)
- [x] Disconnect handling (pendingDuel cleanup, duel_cancelled message)
- [x] Warp mechanism fix — save state hijack + door fallback (watchpoint on callback2, golden state capture, SaveBlock1 preservation)

### Phase 3B: PvP Battle System (CURRENT)
- [x] Battle module architecture (client/battle.lua — party read/write, AI interception, RNG sync)
- [x] Memory scanner script (scripts/scan_battle_addresses.lua — scan gBattleTypeFlags, gEnemyParty, etc.)
- [x] Config placeholder (config/run_and_bun.lua — battle section with nil addresses)
- [x] Server protocol (duel_party, duel_choice, duel_rng_sync, duel_end messages)
- [x] Main.lua integration (warp phases: waiting_party, in_battle, returning)
- [x] Battle addresses scanned and filled in config/run_and_bun.lua
- [x] Fix 5 PvP bugs (P3_10B): server coords, door fallback→triggerMapLoad, battle trigger, isFinished transition tracking, getOutcome HP fallback
- [x] HAL.readInBattle() + inBattle tracking in main.lua
- [x] **Party addresses corrected** via cross-ref with pokemon-run-bun-exporter (gPlayerParty=0x02023A98, gEnemyParty=0x02023CF0)
- [x] **Reference data repos cloned** (pokemon-run-bun-exporter, runandbundex, pokeemerald-expansion)
- [x] **Config enriched** with Pokemon struct constants, battle flags, outcome codes from decomp
- [ ] Verify gBattleBufferB address (was derived from wrong gPlayerParty base, needs re-scan)
- [ ] Test party exchange and injection
- [ ] Test battle trigger with BATTLE_TYPE_SECRET_BASE
- [ ] Test AI choice interception
- [ ] Test RNG synchronization
- [ ] Test battle completion and return to origin
- [ ] Test disconnect handling during battle

### Phase 4: Multi-ROM Support
- [ ] Profils additionnels (Radical Red, Unbound)
- [ ] Auto-détection ROM
- [ ] Configuration dynamique

### Phase 5: Polish
- [ ] Gestion erreurs robuste
- [ ] Optimisation performance
- [ ] Documentation complète
- [ ] Interface configuration

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

**Battle state (scanner mGBA, 2026-02-05):**
- **gBattleTypeFlags**: 0x020090E8 (32-bit)
- **gMainInBattle**: 0x020206AE (gMain+0x66)
- **gRngValue**: IWRAM 0x03005D90 (32-bit)
- **CB2_BattleMain**: 0x08094815 (ROM)

**Warp system (scanner mGBA, 2026-02-03):**
- **gMain.callback2**: 0x0202064C (EWRAM)
- **CB2_LoadMap**: 0x08007441 (ROM)
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

**Duel warp protocol:**
```json
{"type":"duel_request","targetId":"player_xxx"}
{"type":"duel_accept","requesterId":"player_xxx"}
{"type":"duel_decline","requesterId":"player_xxx"}
{"type":"duel_warp","coords":{"mapGroup":28,"mapId":24,"x":3,"y":5},"isMaster":true}
{"type":"duel_declined","playerId":"player_xxx"}
{"type":"duel_cancelled","requesterId":"player_xxx"}
```

**PvP battle protocol:**
```json
{"type":"duel_party","data":[/* 600 bytes as array */]}
{"type":"duel_choice","choice":{"action":"move","slot":2,"target":1},"rng":305419896}
{"type":"duel_choice","choice":{"action":"switch","switchIndex":3}}
{"type":"duel_rng_sync","rng":305419896}
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

**Dernière mise à jour**: 2026-02-05
**Version**: 0.5.1-alpha
**Status**: Phase 3B - PvP Battle System (party addresses corrected, reference data integrated)
