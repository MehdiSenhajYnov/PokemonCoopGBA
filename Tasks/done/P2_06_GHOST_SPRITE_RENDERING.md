# Phase 2 - Ghost Sprite Rendering

> **Statut:** Completed (2026-02-03)
> **Type:** Update — Remplacer les carres verts par les vrais sprites du joueur extraits de la VRAM
> **Objectif:** Rendre les ghosts avec les vrais sprites overworld du GBA (tous etats: marche, course, velo, surf, etc.) au lieu de rectangles verts, via extraction dynamique VRAM/OAM/Palette.

---

## Vue d'ensemble

Actuellement, les ghosts sont des rectangles verts semi-transparents 14x14 dessines via `painter:drawRectangle()` dans `client/render.lua:190-199`. L'objectif est de les remplacer par les vrais sprites overworld tels qu'affiches par le jeu.

**Approche: Extraction dynamique VRAM (zero assets manuels)**

Le GBA stocke les sprites affiches a l'ecran dans des zones memoire hardware fixes (VRAM, OAM, Palette). En lisant ces zones, on capture automatiquement **tous les etats visuels du joueur** sans avoir a les connaitre a l'avance:
- Marche, course, velo, surf, peche, etc.
- Toutes les directions et frames d'animation
- Tout changement de sprite specifique au ROM hack

Le jeu gere lui-meme les changements de tiles en VRAM. On ne fait que **lire ce qui est affiche**.

**Aucune intervention manuelle requise** — pas d'extraction de sprites, pas de PNGs, pas d'assets. Tout est lu depuis la memoire GBA a runtime.

---

## Recherche API mGBA (Confirmee)

### Primitives Image disponibles
```lua
-- Creation
image.new(width, height)              -- Image vierge
image.load(path)                      -- Charger PNG

-- Manipulation pixel
img:setPixel(x, y, color)            -- ARGB 0xAARRGGBB
img:getPixel(x, y)                   -- Lire pixel

-- Composition (PAS sur Painter, directement sur Image)
targetImg:drawImage(srcImg, x, y, alpha)      -- Avec blending alpha
targetImg:drawImageOpaque(srcImg, x, y)       -- Rapide, sans alpha

-- PAS de resize/scale/rotate/crop sur Image
```

### Acces memoire GBA (adresses hardware fixes, identiques pour TOUS les jeux)
```lua
emu.memory.vram      -- VRAM (tiles sprites a offset 0x10000)
emu.memory.oam       -- OAM (128 entrees x 8 bytes, attributs sprites)
emu.memory.palette   -- Palette RAM (palettes sprites a offset 0x200)

domain:readRange(offset, length)  -- Lecture bulk (bytes bruts, performant)
domain:read8/read16/read32(offset)
```

### Format sprites GBA
- **OAM** (8 bytes/entree): attr0 (Y, shape, bpp), attr1 (X, flip, size), attr2 (tile index, palette bank)
- **Tiles 4bpp**: 32 bytes par tile 8x8, 2 pixels par byte (nibble bas = pixel gauche)
- **Palette BGR555**: 16 couleurs par bank, 2 bytes chacune, index 0 = transparent
- **Sprite joueur typique**: 16x32 pixels = 2x4 tiles = 8 tiles x 32 bytes = 256 bytes par frame
- **Taille sprite variable**: Le shape+size dans OAM attr0/attr1 donne la vraie taille (peut varier selon l'etat: velo, surf, etc.)

### Decodage OAM
```lua
-- Lecture d'une entree OAM (8 bytes)
local attr0 = emu.memory.oam:read16(index * 8)
local attr1 = emu.memory.oam:read16(index * 8 + 2)
local attr2 = emu.memory.oam:read16(index * 8 + 4)

-- Extraction champs
local yPos       = attr0 & 0xFF
local shape      = (attr0 >> 14) & 0x3
local is4bpp     = ((attr0 >> 13) & 0x1) == 0  -- 0=4bpp, 1=8bpp
local xPos       = attr1 & 0x1FF
local hFlip      = ((attr1 >> 12) & 0x1) == 1
local vFlip      = ((attr1 >> 13) & 0x1) == 1
local sizeCode   = (attr1 >> 14) & 0x3
local tileIndex  = attr2 & 0x3FF
local palBank    = (attr2 >> 12) & 0xF

-- Table taille (shape x sizeCode) → {largeur, hauteur} en pixels
-- shape=0 (Square): 8x8, 16x16, 32x32, 64x64
-- shape=1 (Wide):   16x8, 32x8, 32x16, 64x32
-- shape=2 (Tall):   8x16, 8x32, 16x32, 32x64
```

### Conversion BGR555 -> ARGB
```lua
function bgr555ToARGB(bgr555)
    local r5 = bgr555 & 0x1F
    local g5 = (bgr555 >> 5) & 0x1F
    local b5 = (bgr555 >> 10) & 0x1F
    local r8 = (r5 << 3) | (r5 >> 2)
    local g8 = (g5 << 3) | (g5 >> 2)
    local b8 = (b5 << 3) | (b5 >> 2)
    return 0xFF000000 | (r8 << 16) | (g8 << 8) | b8
end
-- Palette index 0 = transparent → utiliser 0x00000000 (alpha=0)
```

---

## Implementation

### Section 1 — Module `sprite.lua` (nouveau)

**Fichier a creer:** `client/sprite.lua`

Module dedie a l'extraction VRAM, la reconstruction et la mise en cache des sprites joueur.

**API publique:**
```lua
Sprite.init()                          -- Initialiser le module
Sprite.captureLocalPlayer()            -- Lire sprite du joueur local depuis VRAM/OAM
Sprite.getImageForPlayer(playerId)     -- Retourne Image cachee pour un ghost
Sprite.updateFromNetwork(playerId, spriteData)  -- Mettre a jour cache depuis donnees reseau
```

**Principe: chaque client capture son propre sprite et l'envoie aux autres.**

**Etape 1 — Trouver l'entree OAM du joueur local:**
- Le joueur est toujours au centre de l'ecran GBA (~120, ~80 en coords ecran)
- Scanner les 128 entrees OAM, chercher celle dont les coords (xPos, yPos) sont proches du centre
- Filtrer par taille attendue (shape=2/Tall, sizeCode=2 → 16x32 pour un personnage standard)
- Gerer le cas ou la taille change (velo, surf → potentiellement shape different)
- Strategie de fallback: si aucun sprite 16x32 au centre, chercher n'importe quel sprite au centre

**Etape 2 — Lire les tiles depuis VRAM:**
```lua
-- Calculer taille en tiles depuis shape+sizeCode
local widthTiles = spriteWidth / 8    -- ex: 16px → 2 tiles
local heightTiles = spriteHeight / 8  -- ex: 32px → 4 tiles
local numTiles = widthTiles * heightTiles  -- ex: 8 tiles

-- Lire les tiles (4bpp: 32 bytes par tile)
local tileData = emu.memory.vram:readRange(
    0x10000 + tileIndex * 32,
    numTiles * 32
)
```

**Etape 3 — Lire la palette:**
```lua
-- 16 couleurs, 2 bytes chacune (BGR555)
local palette = {}
for i = 0, 15 do
    local bgr = emu.memory.palette:read16(0x200 + palBank * 32 + i * 2)
    palette[i] = bgr555ToARGB(bgr)
end
palette[0] = 0x00000000  -- Index 0 = transparent
```

**Etape 4 — Reconstruire l'image pixel par pixel:**
```lua
local img = image.new(spriteWidth, spriteHeight)

-- GBA 1D tile mapping: tiles stockees sequentiellement
for tileIdx = 0, numTiles - 1 do
    local tileRow = math.floor(tileIdx / widthTiles)
    local tileCol = tileIdx % widthTiles
    local baseOffset = tileIdx * 32

    for py = 0, 7 do
        for px = 0, 3 do  -- 4bpp: 2 pixels par byte
            local byte = tileData[baseOffset + py * 4 + px + 1]  -- +1 car Lua 1-indexed
            local leftPixel = byte & 0x0F
            local rightPixel = (byte >> 4) & 0x0F

            local screenX = tileCol * 8 + px * 2
            local screenY = tileRow * 8 + py

            -- Appliquer H-flip si necessaire (depuis attr1)
            if hFlip then screenX = spriteWidth - 1 - screenX end
            if vFlip then screenY = spriteHeight - 1 - screenY end

            img:setPixel(screenX, screenY, palette[leftPixel])
            img:setPixel(screenX + 1, screenY, palette[rightPixel])
        end
    end
end
```

**Etape 5 — Cache et detection de changement:**
- Stocker le `tileIndex` et `palBank` actuels
- A chaque frame (ou toutes les N frames), relire OAM attr2
- Si `tileIndex` ou `palBank` a change → reconstruire l'image
- Sinon → reutiliser l'image cachee (zero cout)
- Frequence de verification recommandee: toutes les 4-8 frames (~15-8fps) pour equilibrer reactivite et performance

---

### Section 2 — Modification `render.lua`

**Fichier concerne:** `client/render.lua`

**Remplacement du dessin rectangle par sprite:**

Actuellement (lignes 189-199):
```lua
painter:setFill(true)
painter:setFillColor(fillColor)
painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)
```

Remplacer par:
```lua
local spriteImg = Sprite.getImageForPlayer(playerId)
if spriteImg then
    -- drawImage sur overlay.image (PAS sur painter — c'est l'API Image, pas Painter)
    -- Ancrage: pieds du sprite alignes sur la tile
    -- Pour un sprite 16x32: offset Y de -(hauteur - 16) pour aligner les pieds
    local spriteH = spriteImg.height  -- Dynamique: 32 pour marche, potentiellement different pour velo/surf
    overlay.image:drawImage(spriteImg, screenX, screenY - (spriteH - 16))
else
    -- Fallback: carre colore (mode actuel)
    painter:setFill(true)
    painter:setFillColor(fillColor)
    painter:drawRectangle(screenX + 1, screenY + 1, GHOST_SIZE, GHOST_SIZE)
end
```

**Modifications necessaires:**

1. **`Render.drawGhost()`** (ligne 163):
   - Recevoir `overlay` en parametre (necessaire pour `overlay.image:drawImage()`)
   - Supprimer le marqueur de direction 4x4 (lignes 202-217) — le sprite montre deja la direction
   - Conserver le label joueur au-dessus du sprite (lignes 224-230)
   - Ajuster position Y du label: `screenY - spriteH - 8` au lieu de `screenY - 8`

2. **`isOnScreen()`** (ligne 149):
   - Ajuster bornes pour sprite potentiellement plus grand: Y de -64 a 192 (au lieu de -GHOST_SIZE)

3. **`Render.drawAllGhosts()`** (ligne 241):
   - Passer `overlay` en parametre

4. **`drawOverlay()`** dans `main.lua` (ligne 297):
   - Passer `overlay` a `Render.drawAllGhosts()`

**Note technique:** `drawImage()` est sur l'objet Image, pas sur le Painter. Il faut acceder a `overlay.image` pour dessiner les sprites. Le Painter reste utilise pour le texte (label) et le fallback rectangles.

---

### Section 3 — Extension `hal.lua`

**Fichier concerne:** `client/hal.lua`

Ajouter l'acces aux domaines memoire VRAM, OAM et Palette:

**Nouvelles fonctions:**
```lua
HAL.readOAMEntry(index)                    -- Lire attr0, attr1, attr2 (3x u16)
HAL.readSpriteTiles(tileIndex, numTiles)   -- Lire tiles 4bpp depuis VRAM
HAL.readSpritePalette(bank)                -- Lire 16 couleurs BGR555
```

**Details:**
- Ajouter references `emu.memory.vram`, `emu.memory.oam`, `emu.memory.palette` dans `HAL.init()` (apres ligne 16 actuelle pour wram/iwram)
- `readOAMEntry(index)`: lire 3x `read16()` a `index * 8`, `index * 8 + 2`, `index * 8 + 4`
- `readSpriteTiles(tileIndex, numTiles)`: `emu.memory.vram:readRange(0x10000 + tileIndex * 32, numTiles * 32)`
- `readSpritePalette(bank)`: boucle de 16x `emu.memory.palette:read16(0x200 + bank * 32 + i * 2)`
- Wraper dans `pcall()` comme les lectures existantes (lignes 57-77)
- Validation offsets: OAM index 0-127, VRAM sprite range 0x10000-0x17FFF, Palette bank 0-15

---

### Section 4 — Synchronisation reseau des sprites

**Fichiers concernes:** `client/network.lua`, `client/main.lua`, `server/server.js`

Chaque client doit envoyer son sprite actuel aux autres joueurs. Deux approches possibles:

**Approche A — Envoyer les donnees brutes du sprite (recommandee):**

Quand le sprite du joueur local change (nouveau tileIndex/palBank detecte), envoyer un message:
```json
{
  "type": "sprite_update",
  "playerId": "player_xxx",
  "data": {
    "width": 16,
    "height": 32,
    "hFlip": false,
    "tiles": "<base64 des bytes tiles 4bpp>",
    "palette": [0, 4294901760, ...]
  }
}
```

- Taille: ~256 bytes tiles + 64 bytes palette = ~450 bytes base64 par update
- Envoye seulement quand le sprite change (pas a chaque frame)
- Le serveur relay tel quel via `broadcastToRoom()`
- Le client recepteur reconstruit l'Image depuis les donnees recues

**Approche B — Envoyer uniquement les metadonnees OAM:**
```json
{
  "type": "sprite_update",
  "playerId": "player_xxx",
  "data": {
    "tileIndex": 256,
    "palBank": 0,
    "shape": 2,
    "sizeCode": 2,
    "hFlip": false
  }
}
```
- Beaucoup plus leger (~50 bytes)
- MAIS: necessite que les deux clients aient les memes tiles en VRAM → ne fonctionne PAS car chaque joueur a sa propre instance GBA

**→ Approche A obligatoire**: chaque instance GBA a sa propre VRAM, donc il faut envoyer les pixels/tiles reels.

**Modifications serveur (`server/server.js`):**
- Dans `handleMessage()` (ligne 100): ajouter case `'sprite_update'` → `broadcastToRoom()` comme pour `position`
- Optionnel: cacher le dernier `sprite_update` par joueur pour l'envoyer aux nouveaux arrivants

**Modifications client (`client/main.lua`):**
- Detecter changement de sprite local (comparer tileIndex/palBank avec frame precedente)
- Envoyer `sprite_update` uniquement au changement
- A la reception d'un `sprite_update`, appeler `Sprite.updateFromNetwork(playerId, data)`

---

### Section 5 — Modification `main.lua`

**Fichier concerne:** `client/main.lua`

**Initialisation** (apres ligne 26):
```lua
local Sprite = require("sprite")
```

**Dans la boucle `update()`** (ligne 370):
```lua
-- Apres la lecture de position (ligne 378)
-- Capturer le sprite du joueur local
Sprite.captureLocalPlayer()

-- Si le sprite a change, envoyer aux autres
if Sprite.hasChanged() then
    Network.send({
        type = "sprite_update",
        data = Sprite.getLocalSpriteData()
    })
end
```

**Dans la boucle de reception** (lignes 410-442):
```lua
-- Ajouter handling du message sprite_update
if message.type == "sprite_update" then
    Sprite.updateFromNetwork(message.playerId, message.data)
end
```

**Dans `drawOverlay()`** (ligne 297):
- Passer `overlay` a `Render.drawAllGhosts()`

---

## Fichiers a creer

| Fichier | Description |
|---------|-------------|
| `client/sprite.lua` | Module extraction VRAM, reconstruction Image, cache, serialisation reseau |

## Fichiers a modifier

| Fichier | Modifications |
|---------|--------------|
| `client/render.lua` | Remplacer `drawRectangle` par `overlay.image:drawImage()` avec fallback, recevoir `overlay`, ajuster ancrage dynamique, ajuster `isOnScreen()` |
| `client/hal.lua` | Ajouter acces `emu.memory.vram/oam/palette` + `readOAMEntry()`, `readSpriteTiles()`, `readSpritePalette()` |
| `client/main.lua` | `require("sprite")`, capturer sprite local, envoyer `sprite_update`, recevoir `sprite_update`, passer overlay au rendu |
| `client/network.lua` | Aucune modification structurelle (les messages passent deja par JSON, `sprite_update` utilise le meme pipeline) |
| `server/server.js` | Ajouter case `sprite_update` dans `handleMessage()` → broadcast |

---

## Considerations performance

- `overlay.image:drawImage()` = operation C-side unique → rapide, pas de souci
- `setPixel()` en boucle (512 appels pour sprite 16x32) → faire uniquement au changement de sprite, pas chaque frame
- `readRange()` pour lecture VRAM bulk → bien plus rapide que des `read8()` individuels
- Detection changement: relire seulement attr2 de l'OAM (1 seul `read16()`) pour detecter si le tileIndex a change
- `sprite_update` reseau: envoye seulement au changement (~quelques fois par seconde max, pas 60fps)
- Taille message `sprite_update`: ~450 bytes base64 — acceptable pour TCP local/LAN

---

## Avantages de l'approche VRAM dynamique

- **Tous les etats captures automatiquement**: marche, course, velo, surf, peche, vol, acro bike, etc.
- **Compatible ROM hacks**: sprites custom de Run & Bun captures tels quels
- **Zero assets manuels**: pas de PNGs a extraire, pas de maintenance
- **Animations natives**: le jeu gere les frames d'animation, on les capture
- **Taille sprite dynamique**: si le velo utilise un sprite 32x32 au lieu de 16x32, on le detecte via shape/sizeCode dans OAM

---

## Criteres de succes

- [x] Ghosts rendus avec les vrais sprites GBA au lieu de carres verts
- [x] Tous les etats visuels captures (marche, course, velo, surf, etc.)
- [x] Directions et animations correctement refletees
- [x] Sprite mis a jour dynamiquement quand l'etat du joueur change
- [x] Pas de degradation de performance visible (maintenir 60fps)
- [x] Fallback gracieux vers carres colores si extraction VRAM echoue
- [x] Synchronisation reseau fonctionnelle (chaque joueur voit le bon sprite des autres)
- [x] Fonctionne avec les sprites specifiques du ROM hack Run & Bun

---

## Prochaine etape

Apres cette tache → **P2_07_OPTIMIZATION.md** (profiling et optimisation performance)
