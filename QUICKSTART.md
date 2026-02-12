# Quick Start - Pokemon Co-op Framework

## Prerequis

- Node.js 18+
- mGBA dev build avec Lua scripting + sockets TCP + canvas/Painter
- ROM supportee (`Run & Bun` prioritaire, `Emerald US` en fallback)

## Lancer le systeme (1 joueur)

### 1) Demarrer le serveur TCP

```bash
cd server
npm install
npm start
```

Port par defaut: `3333` (modifiable via variable d'environnement `PORT`).

### 2) Charger le client Lua

1. Ouvre mGBA et charge la ROM
2. `Tools > Scripting`
3. `File > Load Script...`
4. Selectionne `client/main.lua`

### 3) Verifier

- Console mGBA: logs `[PokéCoop]` (init, ROM detectee, connexion serveur)
- Overlay: `Players: <n>` + statut (`ONLINE` / `RECONNECTING` / `OFFLINE`)
- Console serveur: messages `register`, `join`, `position`

## Test 2 joueurs

1. Laisse le serveur tourne
2. Lance 2 instances mGBA
3. Charge `client/main.lua` dans les 2

Resultat attendu:
- `Players: 2` (ou plus) dans l'overlay
- Ghost visible entre les deux clients
- Synchronisation fluide des deplacements
- En overlap vertical (un joueur juste en dessous de l'autre), l'ordre visuel reste coherent

## Test auto-duel (optionnel)

Wrappers disponibles:
- `client/auto_duel_requester.lua`
- `client/auto_duel_accepter.lua`
- `client/auto_duel_requester_ss.lua`
- `client/auto_duel_accepter_ss.lua`

Ces wrappers utilisent des chemins absolus locaux (a adapter selon ta machine).

## Parametres utiles (`client/main.lua`)

```lua
local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 3333
local SEND_RATE_MOVING = 1
local SEND_RATE_IDLE = 30
local ENABLE_DEBUG = true
```

## Depannage rapide

- `Failed to connect`: verifier que le serveur tourne bien sur `127.0.0.1:3333`
- Pas de ghost: verifier que les deux clients sont dans la meme room/map
- Pas d'overlay: utiliser un build mGBA avec les APIs de scripting/canvas

## Suite

- `docs/TESTING.md` pour les scenarios de validation
- `server/README.md` pour le protocole TCP
- `docs/RUN_AND_BUN.md` pour les offsets Run & Bun
