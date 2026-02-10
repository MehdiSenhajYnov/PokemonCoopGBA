# Hybrid OAM Injection for Ghost Rendering

> **Statut:** En attente d'implementation
> **Type:** Improvement — Reecriture majeure du systeme de rendu des ghosts
> **Objectif:** Remplacer le rendu overlay (Painter API) par une injection directe dans l'OAM/VRAM du GBA, en gardant notre extraction dynamique de sprites
> **Priorite:** Moyenne (amelioration qualite de vie, pas bloquant)
> **Prerequis:** `P2_09_HIDE_GHOSTS_OUTSIDE_OVERWORLD.md` (fix rapide en attendant)
> **Reference:** `refs/GBA-PK-multiplayer-main/` (projet qui utilise deja cette approche en OAM pur)

---

## Vue d'ensemble

### Probleme actuel

Le systeme de rendu actuel utilise le **Painter API overlay** de mGBA 0.11+ pour dessiner les ghosts. Cette approche a plusieurs defauts :

1. **Ghosts visibles hors overworld** — L'overlay est une couche independante du jeu, elle dessine par-dessus tout (menus, sac, combats)
2. **Occlusion manuelle couteuse** — `occlusion.lua` doit lire la tilemap BG1, decoder les tiles 4bpp, et redessiner les pixels de couverture par-dessus les ghosts via Painter API
3. **Pas pixel-perfect** — L'overlay est visuellement distincte des vrais sprites GBA
4. **mGBA 0.11+ dev build obligatoire** — La canvas API n'existe pas dans la version stable

### Solution proposee : Hybrid OAM

**Garder** notre extraction dynamique de sprites (pas de tables hardcodees = compatible tout ROM hack).
**Remplacer** le rendu Painter par une injection directe dans la VRAM et l'OAM du GBA.

### Pourquoi ca resout les problemes

- **Masquage automatique hors overworld** — Quand le jeu ouvre un menu/combat, il reecrit l'OAM entierement → nos sprites injectes disparaissent naturellement, sans aucun code de detection
- **Occlusion gratuite** — La priority OAM native du GBA gere automatiquement la profondeur (derriere arbres, toits, etc.) → `occlusion.lua` peut etre supprime
- **Pixel-perfect** — Les ghosts sont de vrais sprites GBA, indistinguables de NPCs
- **Compatible mGBA 0.10+** — Plus besoin de la canvas API pour les ghosts (la garder uniquement pour l'UI : labels, duel prompts)

### Reference : GBA-PK-multiplayer

Le projet `refs/GBA-PK-multiplayer-main/` utilise deja l'injection OAM pour afficher les autres joueurs. Leur approche :
- **Sprites pre-compiles** en tables Lua hardcodees (~3000 lignes de raw tile data)
- **Injection VRAM** a `0x6013C00 - (id * 0x600)` (1536 bytes par ghost)
- **3 entrees OAM** par ghost (24 bytes), ecrites a `gSprite - (id * 24)`
- **Max 8 ghosts** (8 slots OAM reserves)

Notre approche hybride garde l'extraction dynamique et remplace seulement le rendu.

---

## Implementation

### Section 1 — Trouver des OAM slots libres

**Fichiers concernes:**
- `client/hal.lua` — Ajouter `HAL.findFreeOAMSlots(count)`

**Details:**

La GBA a 128 entrees OAM (Object Attribute Memory) a l'adresse `0x07000000`, chaque entree = 8 bytes.
Le jeu en utilise ~80-100 (sprites NPCs, joueur, effets, UI). Les entrees inutilisees ont typiquement `Y >= 160` (hors ecran).

```
OAM entry format (8 bytes):
  attr0 (u16): bits 0-7 = Y position, bits 8-9 = mode, bits 12-13 = shape, bit 13 = 256-color
  attr1 (u16): bits 0-8 = X position, bit 12 = hFlip, bit 13 = vFlip, bits 14-15 = size
  attr2 (u16): bits 0-9 = tile index, bits 10-11 = priority (0=highest), bits 12-15 = palette bank
  pad  (u16): unused (rotation/scaling data)
```

**Algorithme :**
1. Scanner les 128 entrees OAM depuis `0x07000000`
2. Collecter celles avec `Y >= 160` ou `Y == 0 and tileIndex == 0` (inutilisees)
3. Retourner les N premieres (N = nombre de ghosts a afficher)
4. Scanner **chaque frame** car le jeu peut reclamer des slots entre deux frames
5. Privilegier les slots a index eleve (moins de chances de conflit avec le jeu)

**Fallback :** Si pas assez de slots libres, ne pas afficher les ghosts les plus eloignes.

### Section 2 — Allouer de la VRAM pour les tiles des ghosts

**Fichiers concernes:**
- `client/hal.lua` — Ajouter `HAL.writeGhostTilesToVRAM(ghostId, tileData)`

**Details:**

La VRAM OBJ du GBA va de `0x06010000` a `0x06017FFF` (32 KB).
Le jeu utilise la partie basse pour ses propres sprites. La partie haute (~0x06013C00+) est generalement libre.

**Strategie (identique a GBA-PK-multiplayer) :**
- Base address : `0x06013C00`
- Chaque ghost recoit `0x600` bytes (1536 bytes = 48 tiles de 32 bytes chacun en mode 4bpp)
- Ghost N utilise l'adresse `0x06013C00 - (N * 0x600)`
- Max recommande : 4-6 ghosts (= 6 * 0x600 = 0x2400 bytes, restant au-dessus de 0x06011800)

**Ecriture :**
```lua
-- Ecrire les tile data du ghost dans VRAM
local baseAddr = 0x06013C00 - (ghostId * 0x600)
for i = 0, #tileData - 1 do
    emu.memory.vram:write8(baseAddr - 0x06000000 + i, tileData[i])
end
```

**Le tile data provient de notre extraction dynamique existante** (`sprite.lua:captureLocalPlayer()` → envoi reseau → reception). On garde ce pipeline intact, on change juste la destination (VRAM au lieu de Image overlay).

### Section 3 — Ecrire les attributs OAM

**Fichiers concernes:**
- `client/render.lua` — Reecrire `drawGhost()` pour ecrire dans l'OAM au lieu du Painter

**Details:**

Pour chaque ghost visible, ecrire 3 entrees OAM (tete + torse + jambes pour un sprite 16x32) :

```
Sprite 16x32 → 2 OAM entries de 16x16 (ou 1 entry en mode 16x32 si shape=tall)

attr0: Y position (ecran) | shape=10 (tall) | mode=00 (normal)
attr1: X position (ecran) | size=10 (16x32) | hFlip si necessaire
attr2: tileIndex (base dans VRAM) | priority=2 (meme que le joueur) | paletteBank
```

**Positionnement :**
Meme calcul que actuellement dans `Render.ghostToScreen()` (render.lua:136-140) :
```lua
screenX = 112 + (ghostX - playerX) * 16 + subTileX
screenY = 72  + (ghostY - playerY) * 16 + subTileY
```
Sauf qu'au lieu de passer les coords au Painter, on les ecrit dans attr0.Y et attr1.X de l'OAM.

**Clipping :** Si `screenX < -16` ou `screenX > 240` ou `screenY < -32` ou `screenY > 160`, ne pas ecrire l'entree OAM (ghost hors ecran = on efface le slot en mettant Y=160).

### Section 4 — Gestion de la palette

**Fichiers concernes:**
- `client/hal.lua` — Ajouter `HAL.writeGhostPalette(paletteSlot, paletteData)`

**Details:**

La GBA a 16 palettes OBJ de 16 couleurs chacune a `0x05000200` (palette RAM OBJ).
Le jeu en utilise typiquement 12-13. Les slots 13-15 sont generalement libres.

**Strategie :**
- Reserver 1-2 slots palette pour les ghosts (ex: slot 14 et 15)
- Ecrire la palette du ghost distant (recue via reseau) dans le slot reserve
- Mettre le paletteBank correspondant dans attr2 de l'OAM

```lua
-- Palette OBJ slot 14 : adresse 0x050002E0 (0x200 + 14*0x20)
local palAddr = 0x050002E0
for i = 0, 15 do
    emu.memory.palette:write16(palAddr - 0x05000000 + i * 2, paletteColors[i])
end
```

**Si 2 ghosts ont des palettes differentes :** Utiliser 2 slots differents. Avec 3+ ghosts a palettes differentes, on peut soit :
- Partager les slots (risque de clignotement au changement)
- Limiter a 2-3 palettes uniques et assigner les ghosts similaires au meme slot

### Section 5 — Suppression de l'overlay pour les ghosts

**Fichiers concernes:**
- `client/render.lua` — Supprimer le code Painter pour les ghosts (garder pour UI)
- `client/occlusion.lua` — **Supprimer entierement** (plus necessaire)
- `client/main.lua` — Retirer les appels a `Occlusion.beginFrame()` et `Occlusion.drawOcclusionForGhost()`
- `client/sprite.lua` — Adapter `buildImage()` pour retourner du raw tile data au lieu d'un objet Image mGBA

**Details:**

Le Painter API reste utilise pour :
- Labels des joueurs (noms au-dessus des ghosts) — via Painter `drawText()`
- UI duel (prompts request/accept) — via `duel.lua`
- Indicateur connexion (ONLINE/OFFLINE) — via main.lua

Seul le rendu des sprites ghosts passe en OAM. Le canvas overlay reste actif pour le texte.

### Section 6 — Boucle de rendu frame-par-frame

**Fichiers concernes:**
- `client/main.lua` — Modifier `drawOverlay()` et la boucle frame

**Details:**

Chaque frame (60 FPS) :

```
1. Scanner les OAM slots libres (HAL.findFreeOAMSlots)
2. Pour chaque ghost visible (trie par distance) :
   a. Calculer la position ecran (ghostToScreen)
   b. Si hors ecran → effacer le slot OAM (Y=160)
   c. Si visible :
      - Ecrire les tiles dans VRAM (si changement de sprite)
      - Ecrire la palette (si changement)
      - Ecrire les attributs OAM (position, tileIndex, priority, palette, flip)
3. Effacer les slots non utilises (Y=160)
4. Dessiner les labels via Painter overlay (text seulement)
```

**Optimisation importante :** Ne reecrire VRAM/palette que quand le sprite change (detection via hash ou flag `spriteChanged`). La position OAM doit etre reecrite chaque frame.

---

## Risques et mitigations

| Risque | Probabilite | Impact | Mitigation |
|--------|-------------|--------|------------|
| OAM slots voles par le jeu mid-frame | Moyenne | Ghost disparait 1 frame | Re-scanner chaque frame, re-injecter |
| VRAM zone utilisee par R&B | Faible | Corruption graphique | Tester avec 0x06013C00, ajuster si conflit |
| Palette slots utilises par R&B | Faible | Mauvaises couleurs | Scanner les palettes OBJ utilisees, prendre les libres |
| OAM write timing (mid-VBlank) | Faible | Tearing | mGBA frame callback = entre VBlanks, timing OK |
| Sprites 32x32 (velo) | Faible | Mauvais rendu | Adapter le code pour detecter la taille et ajuster les OAM entries |
| R&B efface toute l'OAM periodiquement | Moyenne | Ghosts clignotent | Ecrire apres le jeu (frame callback = apres le jeu) |

---

## Fichiers a modifier

| Fichier | Modification |
|---------|-------------|
| `client/hal.lua` | +3 fonctions : `findFreeOAMSlots()`, `writeGhostTilesToVRAM()`, `writeGhostPalette()` |
| `client/render.lua` | Reecriture `drawGhost()` : OAM write au lieu de Painter. Garder `drawText` pour labels |
| `client/sprite.lua` | Adapter `buildImage()` pour retourner raw tile data + palette au lieu d'Image mGBA |
| `client/main.lua` | Retirer `Occlusion.beginFrame()`, adapter `drawOverlay()` pour OAM + labels-only overlay |
| `client/occlusion.lua` | **Supprimer** (plus necessaire — OAM priority gere la profondeur) |

## Fichiers a creer

Aucun — tout se fait dans les fichiers existants.

---

## Plan d'implementation

### Phase 1 : Proof of Concept (1 ghost statique)
- [ ] Implementer `HAL.findFreeOAMSlots(1)` — scanner 128 entries, retourner 1 slot libre
- [ ] Implementer `HAL.writeGhostTilesToVRAM(0, data)` — ecrire 0x600 bytes a 0x06013C00
- [ ] Implementer `HAL.writeGhostPalette(14, colors)` — ecrire 16 couleurs au slot 14
- [ ] Ecrire un ghost en dur dans l'OAM (position fixe, tiles fixes) et verifier qu'il s'affiche
- [ ] Verifier qu'il disparait quand on ouvre le sac/menu

### Phase 2 : Integration dynamique
- [ ] Adapter `sprite.lua:buildImage()` pour retourner raw 4bpp tile data + palette array
- [ ] Connecter l'extraction reseau existante au pipeline OAM (recevoir sprite → ecrire VRAM)
- [ ] Implementer le positionnement dynamique (ghostToScreen → OAM attr0/attr1)
- [ ] Gerer le hFlip (bit 12 de attr1)

### Phase 3 : Multi-ghost + cleanup
- [ ] Supporter N ghosts (scan N slots, N blocs VRAM, gestion palettes)
- [ ] Gerer les sprites 32x32 (velo) vs 16x32 (marche)
- [ ] Supprimer `occlusion.lua` et ses appels dans main.lua/render.lua
- [ ] Adapter le canvas overlay pour ne dessiner que les labels texte
- [ ] Tests complets : overworld, menu, combat, multi-ghost, velo, surf

---

## Notes techniques GBA OAM

### Adresses memoire
- **OAM** : `0x07000000` — 128 entries de 8 bytes = 1024 bytes
- **VRAM OBJ** : `0x06010000` — `0x06017FFF` (32 KB, mode bitmap: 16KB)
- **Palette OBJ** : `0x05000200` — `0x050003FF` (256 bytes = 16 palettes de 16 couleurs)

### Format OAM entry (8 bytes)
```
Offset 0 — attr0 (u16):
  bits 0-7   : Y coordinate (0-255, wraps)
  bits 8-9   : OBJ Mode (00=normal, 01=semi-transparent, 10=OBJ window)
  bit  12    : Mosaic enable
  bit  13    : Color mode (0=16 colors/4bpp, 1=256 colors/8bpp)
  bits 14-15 : Shape (00=square, 01=wide, 10=tall)

Offset 2 — attr1 (u16):
  bits 0-8   : X coordinate (0-511, wraps, 9-bit signed)
  bit  12    : Horizontal flip
  bit  13    : Vertical flip
  bits 14-15 : Size (depends on shape)

Offset 4 — attr2 (u16):
  bits 0-9   : Tile index (base tile in VRAM OBJ)
  bits 10-11 : Priority (0=highest/front, 3=lowest/back)
  bits 12-15 : Palette bank (0-15, for 4bpp mode)

Size table (shape x size):
  Square: 8x8, 16x16, 32x32, 64x64
  Wide:   16x8, 32x8, 32x16, 64x32
  Tall:   8x16, 8x32, 16x32, 32x64
```

### Tile index calcul
En mode 4bpp, chaque tile = 32 bytes. Le tile index dans attr2 est relatif a `0x06010000`.
Pour un ghost a VRAM `0x06013C00` : `tileIndex = (0x13C00 - 0x10000) / 32 = 0x1E0 = 480`.

### Priority et le joueur
Le sprite du joueur a typiquement `priority = 2`. Pour que les ghosts soient au meme niveau : `priority = 2`. Pour qu'ils soient derriere les objets de premier plan (priority 0-1) : laisser a 2.
