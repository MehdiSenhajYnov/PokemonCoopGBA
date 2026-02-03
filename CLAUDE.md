# Pokémon Unified Co-op Framework (mGBA + Lua)

## 1. CONTEXTE ET VISION

Framework générique pour multijoueur "Seamless" sur ROM et ROM hacks GBA Pokémon.

### Objectifs
- **Ghosting**: Voir les autres joueurs en temps réel (Overlay)
- **Generic Architecture**: Support multi-jeux via profils d'offsets
- **Synchronized Duel (Warp Mode)**: Téléportation synchronisée dans une salle de combat Link

### Cible Prioritaire
**Pokémon Run & Bun** - ROM hack avancé basé sur le moteur Émeraude

**IMPORTANT**: Run & Bun modifie énormément la ROM de base d'Émeraude. Les offsets mémoire standard d'Émeraude ne fonctionneront probablement PAS directement. Il faudra:
- Scanner et trouver les offsets spécifiques à Run & Bun
- Tester chaque adresse mémoire individuellement
- Créer un profil ROM dédié à Run & Bun
- Ne pas se fier aveuglément aux adresses d'Émeraude standard

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
- Interpolation de mouvement (FIFO waypoint queue avec catch-up adaptatif `BASE_DURATION / queueLength`)
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
**Trigger:** Bouton A près du ghost ou interface souris

**Workflow:**
1. Acceptation des deux joueurs
2. Écriture RAM simultanée (MapID + Coords)
3. Placement devant PNJ Colisée
4. Verrouillage inputs pendant warp

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
│   ├── core.lua             # Core Engine
│   └── README.md
├── config/                   # Profils ROM
│   ├── run_and_bun.lua      # Profil principal (template à remplir)
│   ├── emerald_us.lua       # Référence vanilla
│   ├── radical_red.lua      # Future extension
│   └── unbound.lua          # Future extension
├── scripts/                  # Scripts de scan mémoire mGBA
│   ├── README.md            # Guide d'utilisation
│   ├── scan_vanilla_offsets.lua
│   ├── scan_wram.lua
│   ├── find_saveblock_pointers.lua
│   └── validate_offsets.lua
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

### Phase 3: Duel Warp
- [ ] Système de trigger
- [ ] Synchronisation téléportation
- [ ] Verrouillage inputs
- [ ] Interface utilisateur

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

#### Pokémon Run & Bun (Trouvés 2026-02-02/03)
- **PlayerX**: 0x02024CBC (16-bit, EWRAM)
- **PlayerY**: 0x02024CBE (16-bit, EWRAM)
- **MapGroup**: 0x02024CC0 (8-bit, EWRAM)
- **MapID**: 0x02024CC1 (8-bit, EWRAM)
- **FacingDirection**: 0x02036934 (8-bit, EWRAM)
- **CameraX**: IWRAM+0x5DFC (s16, gSpriteCoordOffsetX)
- **CameraY**: IWRAM+0x5DF8 (s16, gSpriteCoordOffsetY)
- **Mode**: STATIQUE (pas de pointeurs dynamiques)

### ⚠️ CRITIQUE: Adresses Dynamiques vs Statiques

**IMPORTANT**: Les adresses peuvent être:
1. **Statiques** (offsets fixes) - facile
2. **Dynamiques** (via pointeurs SaveBlock1/2) - nécessite `readSafePointer()`

Le code HAL supporte déjà les deux modes, mais on doit d'abord IDENTIFIER lequel Run & Bun utilise.

### Méthodologie pour trouver les offsets Run & Bun

**Voir les guides complets**:
- [docs/MEMORY_GUIDE.md](docs/MEMORY_GUIDE.md) - Guide théorique complet
- [scripts/README.md](scripts/README.md) - Guide pratique d'utilisation des scripts

**Résumé rapide:**

1. **Phase 1**: Tester si offsets Émeraude vanilla fonctionnent
   - Utiliser `scripts/scan_vanilla_offsets.lua` dans mGBA console
   - Si ça marche → terminé, remplir config

2. **Phase 2**: Si échec, scanner avec `scripts/scan_wram.lua`
   - Scanner WRAM GBA (0x02000000-0x0203FFFF) pour chaque valeur
   - Utiliser fonctions `scanWRAM()`, `rescan()`, `watchAddress()`

3. **Phase 3**: Identifier si pointeurs dynamiques
   - Tester persistance des adresses trouvées
   - Si dynamiques: utiliser `scripts/find_saveblock_pointers.lua`
   - Trouver pointeurs SaveBlock et offsets relatifs

4. **Phase 4**: Valider et documenter
   - Utiliser `scripts/validate_offsets.lua` pour validation
   - Remplir `config/run_and_bun.lua` avec offsets trouvés
   - Documenter dans `docs/RUN_AND_BUN.md`

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
- [Pokémon Emerald Decomp](https://github.com/pret/pokeemerald) - ⚠️ Référence pour comprendre le moteur de base, MAIS Run & Bun modifie beaucoup le code
- [Node.js TCP/Net](https://nodejs.org/api/net.html) - Documentation TCP Node.js
- [Lua Socket](http://w3.impa.br/~diego/software/luasocket/) - Documentation Lua Socket

### Outils Essentiels
- **mGBA 0.11+ dev build** (CRITIQUE) - Émulateur avec console Lua + canvas API pour overlay. Les dev builds sont nécessaires pour le dessin à l'écran.
- **Cheat Engine** (optionnel) - Alternative pour memory scanning (plus complexe, problème d'ASLR)
- **VBA-SDL-H** - Alternative pour memory debugging
- **PKHex** - Pour ROM exploration (structures de données)

### Notes sur Run & Bun
Run & Bun étant un ROM hack avec modifications majeures:
- Les structures de données peuvent être réorganisées
- Les offsets mémoire sont probablement différents d'Émeraude vanilla
- Certaines fonctionnalités peuvent avoir été ajoutées/supprimées
- Il faudra reverse-engineer les offsets via memory scanning en live

---

**Dernière mise à jour**: 2026-02-03
**Version**: 0.3.2-alpha
**Status**: Phase 2 - Ghosting Complete (Interpolation + Camera + Network + Sprites + BG Occlusion + Waypoint Queue + Bike Sprite)
