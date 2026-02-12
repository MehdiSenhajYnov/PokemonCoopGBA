# Scripts - Pokemon Co-op Framework

Collection de scripts de debug, reverse et tests.

## Arborescence utile

```text
scripts/
  README.md
  start-server.bat
  start-server.sh
  test-server.bat
  interactive_play.lua
  diag_textbox.lua
  test_textbox.lua
  testing/       # runner + suites
  scanners/      # scanners Lua orientés offsets/adresses
  debug/         # scripts de diagnostic runtime
  discovery/     # scripts de recherche mémoire/fonctions
  ghidra/        # scripts Python orientés analyse ROM
  ToUse/         # scripts en cours d'usage
  archive/       # historique / superseded
```

## Entrypoints frequents

- `start-server.bat` / `start-server.sh`: lance le serveur Node (`server/server.js`).
- `test-server.bat`: lance le smoke test TCP (`server/test-connection.js`).
- `testing/run_all.lua`: point d'entree du framework de tests Lua.
- `diag_textbox.lua` / `test_textbox.lua`: diagnostic du flux textbox natif.

## Notes

- Plusieurs scripts sont experimentaux et assumes pour un contexte local (chemins absolus possibles).
- Certains anciens commentaires parlent encore de "WebSocket", mais le systeme actif utilise TCP brut.
- Pour les offsets/profils ROM, la verite terrain est dans `config/*.lua` puis `docs/RUN_AND_BUN.md`.
