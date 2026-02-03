# Scripts — Pokémon Co-op Framework

Outils de diagnostic et utilitaires pour mGBA.

## Structure

```
scripts/
├── ghost_diagnostic.lua   # Diagnostic position des ghosts (ACTIF)
├── start-server.bat       # Lancer le serveur (Windows)
├── start-server.sh        # Lancer le serveur (Linux/Mac)
├── test-server.bat        # Tester la connexion serveur
├── README.md              # Ce fichier
└── archive/               # Scripts terminés (Phase 0 + caméra)
    ├── scan_vanilla_offsets.lua
    ├── scan_wram.lua
    ├── find_saveblock_pointers.lua
    ├── validate_offsets.lua
    ├── scan_camera_auto.lua
    └── verify_camera.lua
```

## Scripts actifs

### `ghost_diagnostic.lua`

Diagnostic visuel pour vérifier la formule de positionnement des ghosts.

**Usage:** `Tools > Scripting > Load Script > scripts/ghost_diagnostic.lua`

Affiche deux croix sur l'écran :
- **Rouge** = formule `tile*16 + cam`
- **Verte** = formule `tile*16 + 8 + cam`

Celle qui est sur le personnage est la bonne formule.

## Utilitaires serveur

| Script | Description |
|--------|-------------|
| `start-server.bat` | Lance `node server/server.js` (Windows) |
| `start-server.sh` | Lance `node server/server.js` (Linux/Mac) |
| `test-server.bat` | Teste la connexion TCP au serveur |

## Archive

Scripts de Phase 0 (memory scanning) et Phase 2 (caméra) — terminés et archivés.
Ces scripts ont été utilisés pour découvrir les offsets mémoire de Run & Bun.
Voir `docs/MEMORY_GUIDE.md` pour la documentation complète.
