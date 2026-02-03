# 🚀 Quick Start - Pokémon Co-op Framework

## ✅ Prérequis

- ✅ mGBA development build (2026-02-02 ou plus récent)
- ✅ Node.js installé
- ✅ ROM Pokémon Émeraude US (BPEE)

---

## 🎮 Lancer le système (1 joueur)

### Étape 1 : Démarrer le serveur

Ouvre un terminal dans `server/` :

```bash
cd server
node server.js
```

Tu devrais voir :
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - TCP Server               ║
╚═══════════════════════════════════════════════════════╝
[Server] Listening on port 8080
```

✅ **Laisse ce terminal ouvert !**

---

### Étape 2 : Démarrer le proxy

Ouvre un **NOUVEAU** terminal dans `client/` :

```bash
cd client
node proxy.js
```

Tu devrais voir :
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - File Proxy               ║
╚═══════════════════════════════════════════════════════╝
[Proxy] Connected to server!
[Proxy] Registered with ID: player_xxx
```

✅ **Laisse ce terminal ouvert aussi !**

---

### Étape 3 : Lancer mGBA avec le script

1. **Lance mGBA** (version development build)
2. **Charge ta ROM** Pokémon Émeraude
3. **Ouvre la console Lua** : `Tools > Scripting...`
4. **Charge le script** : `File > Load script...` → `client/main.lua`

Tu devrais voir dans la console mGBA :
```
[PokéCoop] ======================================
[PokéCoop] Pokémon Co-op Framework v0.2.0
[PokéCoop] ======================================
[PokéCoop] Initializing...
[PokéCoop] Detected ROM ID: BPEE
[PokéCoop] Connected to server!
[PokéCoop] Overlay initialized!
[PokéCoop] Script loaded successfully!
```

Et **à l'écran**, tu devrais voir :
- Une barre noire semi-transparente en haut
- "Players: 1" en vert
- "ONLINE" si connecté
- Ta position (X, Y, Map) si DEBUG activé

✅ **Tout fonctionne !** 🎉

---

## 👥 Tester avec 2 joueurs

### Pour le 2ème joueur :

1. **Copie le dossier** `client/` → `client2/`

2. **Modifie** `client2/main.lua` ligne 66 :
   ```lua
   return "player_2"  -- Au lieu de "player_1"
   ```

3. **Lance un 2ème proxy** dans un nouveau terminal :
   ```bash
   cd client2
   node proxy.js
   ```

4. **Lance une 2ème instance de mGBA** :
   - Charge la même ROM
   - Charge le script `client2/main.lua`

5. **Déplace les personnages** dans les deux instances

**Résultat attendu** :
- Chaque mGBA affiche "Players: 2"
- Tu vois les positions de l'autre joueur en jaune :
  ```
  player_2: X=10 Y=15 Map=0:3
  ```

---

## 🐛 Dépannage

### "Failed to connect to server"
- Vérifie que le serveur tourne (terminal 1)
- Vérifie le port 8080 n'est pas bloqué

### "Failed to read player position"
- Vérifie que tu as chargé une ROM
- Vérifie que tu utilises Pokémon Émeraude US (BPEE)
- Essaye de démarrer une nouvelle partie

### Pas d'overlay à l'écran
- Vérifie que tu utilises la version **development build** de mGBA
- La version stable 0.10.5 n'a pas l'API canvas

### Le proxy se déconnecte
- Vérifie que le serveur est démarré en premier
- Regarde les logs du serveur pour voir les erreurs

---

## 📝 Configuration

### Changer le taux d'envoi

Dans `client/main.lua` ligne 28 :
```lua
local UPDATE_RATE = 60  -- Frames entre chaque envoi (60 = 1x/sec à 60fps)
```

### Activer/désactiver le debug

Dans `client/main.lua` ligne 30 :
```lua
local ENABLE_DEBUG = true  -- false pour désactiver les logs
```

### Changer le serveur

Dans `client/main.lua` lignes 26-27 :
```lua
local SERVER_HOST = "127.0.0.1"  -- Localhost
local SERVER_PORT = 8080
```

---

## 🎯 Prochaines étapes

Une fois que le système fonctionne :

1. ✅ **Phase 1 terminée** - Communication TCP établie
2. 🚧 **Phase 2** - Améliorer l'overlay graphique (sprites, couleurs par joueur)
3. 🚧 **Phase 3** - Ajouter le Duel Warp (téléportation synchronisée)
4. 🚧 **Phase 4** - Support multi-ROM (Run & Bun, Radical Red)

---

## 📚 Documentation

- `CLAUDE.md` - Architecture complète du projet
- `Tasks/README.md` - Liste des tâches et progression
- `client/FILE_BASED_SETUP.md` - Détails du système file-based

---

**Amusez-vous bien ! 🎮✨**
