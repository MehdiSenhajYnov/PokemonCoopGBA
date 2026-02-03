# Guide - Version File-Based (sans LuaSocket)

Cette version fonctionne **sans avoir besoin d'installer LuaSocket**. Elle utilise des fichiers comme pont entre mGBA et le serveur.

## Architecture

```
mGBA (Lua)  <--files-->  proxy.js  <--TCP-->  server.js
```

## Installation en 3 étapes

### 1. Démarrer le serveur

Ouvre un terminal dans `server/` :

```bash
node server.js
```

Tu devrais voir :
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - TCP Server               ║
╚═══════════════════════════════════════════════════════╝
[Server] Listening on port 8080
```

✅ Laisse ce terminal ouvert !

---

### 2. Démarrer le proxy

Ouvre un **NOUVEAU** terminal dans `client/` :

```bash
node proxy.js
```

Tu devrais voir :
```
╔═══════════════════════════════════════════════════════╗
║   Pokémon Co-op Framework - File Proxy               ║
╚═══════════════════════════════════════════════════════╝
[Proxy] Connected to server!
[Proxy] Registered with ID: player_123456_abc
[Proxy] Joined room: default
```

✅ Laisse ce terminal ouvert aussi !

---

### 3. Lancer mGBA

1. Ouvre mGBA
2. Charge ta ROM Pokémon Émeraude
3. Ouvre la console Lua : `Tools > Scripting...`
4. Charge le script : `File > Load script...` → `client/main.lua`

Tu devrais voir dans la console mGBA :
```
[PokéCoop] Initializing...
[PokéCoop] Connected to server!
[PokéCoop] Script loaded successfully!
```

✅ C'est bon ! Le client est connecté.

---

## Tester avec 2 joueurs

1. Garde tout ouvert (serveur + proxy + mGBA)
2. Lance une **2ème instance de mGBA**
3. Charge la même ROM
4. Ouvre un **2ème terminal** dans `client/` et lance un 2ème proxy :
   ```bash
   node proxy.js
   ```
   (Les 2 proxies doivent tourner en parallèle)
5. Charge le script dans le 2ème mGBA

Maintenant :
- Déplace le personnage dans mGBA 1
- Tu devrais voir apparaître "Players: 2" dans mGBA 2 !

---

## Fichiers créés automatiquement

Quand tu lances le script, ces fichiers apparaissent dans `client/` :

- `client_outgoing.json` - Positions envoyées par Lua
- `client_incoming.json` - Positions reçues des autres joueurs
- `client_status.json` - Statut de connexion

Tu peux les ignorer (ils se mettent à jour automatiquement).

---

## Dépannage

### "Cannot open outgoing file"
- Vérifie que le proxy tourne AVANT de lancer mGBA
- Vérifie les permissions du dossier `client/`

### Le proxy se déconnecte
- Vérifie que le serveur est bien démarré
- Vérifie le port 8080 n'est pas bloqué par un firewall

### Les positions ne se synchronisent pas
- Vérifie que les 2 proxies tournent (1 par client)
- Regarde les logs du serveur pour voir si les positions arrivent
- Déplace le personnage dans le jeu (ça n'envoie que quand tu bouges)

---

## Performances

Cette version est un peu plus lente que TCP direct (lecture/écriture fichier), mais ça reste imperceptible pour du ghosting de position (quelques millisecondes de délai).

---

## Prochaine étape

Une fois que ça marche, tu peux faire les tests de `Tasks/todo/P1_02_TCP_TESTING.md` !
