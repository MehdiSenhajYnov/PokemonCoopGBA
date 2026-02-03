# Fiabilite Detection Sprite Joueur

> **Statut:** Completed (2026-02-03)
> **Type:** Bug Fix — Detection OAM parfois incorrecte
> **Priorite:** Haute (impact direct sur l'experience)
> **Objectif:** Garantir que `findPlayerOAM()` identifie toujours le sprite du joueur, meme en presence de NPCs proches ou de reflets d'eau.

---

## Probleme

La fonction `findPlayerOAM()` dans `client/sprite.lua:120-155` scanne les 128 entrees OAM hardware a chaque frame pour identifier le sprite joueur. Le scoring actuel combine:

```lua
-- sprite.lua:143
local score = dist + entry.tileIndex * 0.5
```

Ce systeme **echoue** dans plusieurs cas:
1. **NPC a cote du joueur** — Un NPC 16x32 plus proche du centre ecran que le joueur obtient un meilleur score
2. **Reflet dans l'eau** — Les reflets sont des sprites 16x32 positionnes exactement sous le joueur, tres proches du centre
3. **Sprites environnementaux** — Certains elements de decor sont 16x32 et peuvent avoir un tileNum bas

**Consequence:** Le ghost chez l'autre client affiche le mauvais sprite (NPC, reflet, decor) au lieu du personnage.

---

## Donnees confirmees (sessions de memory scanning)

| Donnee | Valeur | Source |
|--------|--------|--------|
| Player tileNum dans OAM | **0** (stable sur toutes les cartes testees) | `scripts/scan_oam_tiles.lua` moniteur background |
| Player dimensions | 16x32 (shape=2, sizeCode=2) | OAM hardware confirme |
| Player position ecran | top-left ~(112, 72), centre ~(120, 88) | OAM hardware confirme |
| OAM index joueur | **Change chaque frame** (shuffle par SortSprites) | Moniteur confirme (oscille entre 1 et 2) |
| Player palette bank | **0** (stable) | `scripts/debug_oam_water.lua` confirme |
| Player OAM priority | **2** | `scripts/debug_oam_water.lua` confirme |
| Reflection tileNum | **0** (meme que joueur!) | `scripts/debug_oam_water.lua` confirme |
| Reflection palette bank | **3** (different du joueur) | `scripts/debug_oam_water.lua` confirme |
| Reflection OAM priority | **3** (derriere le joueur) | `scripts/debug_oam_water.lua` confirme |
| Reflection vFlip | **false** (pas flippe verticalement) | `scripts/debug_oam_water.lua` confirme |
| gSprites base 0x020212F0 | **INCORRECT pour Run & Bun** (donnees garbage) | `scripts/find_tile_references.lua` |
| PlayerX/Y en WRAM | 0x02024CBC / 0x02024CBE (statique) | Confirme depuis Phase 0 |

---

## Causes identifiees (par priorite)

### P0 - CRITIQUE

#### 1. Le tileNum=0 est utilise comme bonus faible au lieu de filtre strict
**Fichier:** `client/sprite.lua:143`

```lua
local score = dist + entry.tileIndex * 0.5
```

Le joueur a **toujours** `tileNum=0` dans l'OAM. Ce n'est pas un bonus de scoring, c'est un identifiant quasi-unique. Un NPC a `tileNum >= 16` typiquement.

**Impact:** Un NPC plus proche du centre (dist plus faible) bat le joueur meme avec le bonus tileNum.
**Fix:** Utiliser `tileNum == 0` comme filtre primaire. Si aucun sprite tileNum=0 n'est trouve, fallback sur le scoring actuel.

### P1 - IMPORTANT

#### 2. Aucune validation croisee avec la position joueur connue
**Fichier:** `client/sprite.lua:120-155`

On connait la position tile du joueur via `HAL.readPlayerX()` / `HAL.readPlayerY()` (adresses 0x02024CBC/CBE). Le sprite joueur devrait etre au centre ecran SI et SEULEMENT SI ces coordonnees correspondent a la position actuelle. Si un NPC est au centre et le joueur est decale (cas rare mais possible), on pourrait utiliser cette info pour valider.

**Fix:** Optionnel — ajouter une verification que le candidat est coherent avec la position joueur connue.

#### 3. Pas de tracking de consistance inter-frames
**Fichier:** `client/sprite.lua:247-249`

Chaque frame, on repart de zero. Si on a identifie tileNum=0 pendant 60 frames consecutives et que soudain on trouve tileNum=20, c'est probablement une erreur.

**Fix:** Ajouter un `lockedTileNum` qui ne change que si un nouveau tileNum est vu au centre pendant N frames consecutives (hysteresis).

---

## Plan d'implementation

### Phase 1 : Filtre strict tileNum=0 (fix principal)

- [x] **1.1** Modifier `findPlayerOAM()` dans `sprite.lua:120-155`
  - [x] Premier passage: chercher un sprite 16x32 avec **exactement** `tileNum == 0` dans un rayon de 40px du centre
  - [x] Si trouve: le retourner directement (pas de scoring)
  - [x] Si pas trouve: fallback sur le scoring actuel (distance + tileNum bonus)

### Phase 2 : Hysteresis / verrouillage tileNum

- [x] **2.1** Ajouter un etat de verrouillage dans le module sprite
  - [x] Variable `lockedTileNum = nil` (initialement pas verrouille)
  - [x] Variable `lockConfidence = 0` (compteur de frames consecutives)
  - [x] Seuil de verrouillage: `LOCK_THRESHOLD = 30` (0.5 sec a 60fps)
  - [x] Seuil de deverrouillage: `UNLOCK_THRESHOLD = 10` (si le tileNum verrouille disparait du centre pendant 10 frames)

- [x] **2.2** Logique de verrouillage dans `findPlayerOAM()`
  - [x] Si `lockedTileNum` est set: chercher uniquement ce tileNum pres du centre
  - [x] Si pas trouve pendant `UNLOCK_THRESHOLD` frames: deverrouiller et revenir au mode scanning
  - [x] Si un nouveau tileNum domine pendant `LOCK_THRESHOLD` frames: verrouiller dessus

- [x] **2.3** Reset du verrouillage dans `Sprite.init()` (changement de map, etc.)

### Phase 3 : Discrimination reflet d'eau via OAM priority

- [x] **3.1** Ajouter extraction du champ `priority` dans `parseOAMEntry()` (attr2 bits 10-11)
- [x] **3.2** Filtre strict utilise OAM priority comme discriminant primaire (joueur pri=2 bat reflet pri=3)
  - Le reflet a le meme tileNum=0 et vFlip=false que le joueur
  - Seul discriminant fiable: OAM priority (reflet=3, joueur=2)
  - Distance au centre ne suffit pas (reflet peut etre plus proche)

---

## Fichiers concernes

| Fichier | Modifications |
|---------|--------------|
| `client/sprite.lua` | `findPlayerOAM()` (lignes 120-155) — filtre tileNum=0, hysteresis, palette |
| `client/sprite.lua` | `Sprite.init()` (ligne 229) — reset du verrouillage |
| `client/sprite.lua` | Variables module (apres ligne 40) — `lockedTileNum`, `lockConfidence`, constantes |

---

## Criteres de succes

- [x] Le ghost affiche **toujours** le sprite du joueur, jamais un NPC
- [x] Le sprite ne "saute" pas vers un NPC quand celui-ci passe pres du joueur
- [x] Le reflet dans l'eau n'est jamais capture comme sprite joueur
- [x] Le sprite reste correct lors des changements de carte
- [x] Pas de regression sur l'animation (VRAM content comparison toujours fonctionnelle)

---

## Contexte technique

**Pourquoi l'OAM index n'est pas stable:** Le moteur Pokemon appelle `SortSprites()` chaque frame pour trier les sprites par priorite/Y-position. L'index OAM du joueur change de 1 a 2 et inversement selon la scene.

**Pourquoi gSprites ne marche pas:** L'adresse `0x020212F0` trouvee par scan ROM pointer ne contient pas de vrais sprites pour Run & Bun (toutes les valeurs sont garbage: tileNum=1023, pos=(1023,1023)). Run & Bun a probablement deplace ou restructure le tableau gSprites.

**Pourquoi tileNum=0 est fiable:** Le joueur est le premier sprite charge en VRAM (allocation `SpriteTileAlloc`). Son sheet commence au tile 0 (`0x06010000`). Les NPCs sont charges apres, avec des tileNum plus eleves (16, 32, etc.). Confirme par le moniteur `scan_oam_tiles.lua` sur plusieurs minutes de jeu.

**Pourquoi le reflet d'eau est difficile a filtrer:** Le reflet a exactement `tileNum=0` et `vFlip=false` — identique au joueur. Il est aussi plus proche du centre ecran (dist=14 vs 16 pour le joueur). Le seul discriminant fiable est l'OAM priority: joueur=2 (devant), reflet=3 (derriere). Confirme par `scripts/debug_oam_water.lua`.
