# Quick Start - Pokemon Co-op Framework

## Prerequis

- mGBA development build (0.11+ avec support canvas/scripting)
- Node.js installe
- ROM Pokemon Emeraude US (BPEE) ou Run & Bun

---

## Lancer le systeme (1 joueur)

### Etape 1 : Demarrer le serveur

```bash
cd server
node server.js
```

### Etape 2 : Lancer mGBA avec le script

1. Lance mGBA (version development build)
2. Charge ta ROM Pokemon
3. Ouvre la console Lua : `Tools > Scripting...`
4. Charge le script : `File > Load script...` -> `client/main.lua`

Tu devrais voir a l'ecran :
- Une barre noire semi-transparente en haut
- "Players: 1" en vert
- "ONLINE" si connecte
- Ta position (X, Y, Map) si DEBUG active

---

## Tester avec 2 joueurs

### Setup

```
Terminal:    node server/server.js
mGBA 1:     charger client/main.lua
mGBA 2:     charger client/main.lua
```

C'est tout. Chaque instance genere un player ID unique automatiquement et se connecte directement au serveur TCP via le socket integre de mGBA. Pas de proxy, pas de copie de dossier.

### Resultat attendu

- Chaque mGBA affiche "Players: 2"
- Un carre vert semi-transparent apparait a la position de l'autre joueur
- Le mouvement du ghost est fluide (interpolation)

---

## Depannage

### "Failed to connect to server"
- Verifie que le serveur tourne
- Verifie que le port 8080 n'est pas bloque

### "Failed to read player position"
- Verifie que tu as charge une ROM
- Verifie que tu utilises Pokemon Emeraude US (BPEE) ou Run & Bun
- Essaye de demarrer une nouvelle partie

### Pas d'overlay a l'ecran
- Verifie que tu utilises la version **development build** de mGBA
- La version stable 0.10 n'a pas l'API canvas

---

## Configuration

### Changer le taux d'envoi

Dans `client/main.lua` :
```lua
local UPDATE_RATE = 60  -- Frames entre chaque envoi (60 = 1x/sec a 60fps)
```

### Activer/desactiver le debug

```lua
local ENABLE_DEBUG = true  -- false pour desactiver les logs
```

### Changer le serveur

```lua
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 8080
```

---

## Documentation

- `CLAUDE.md` - Architecture complete du projet
- `Tasks/README.md` - Liste des taches et progression
