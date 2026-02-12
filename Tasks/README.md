# Tasks

Backlog et historique des travaux du projet.

## Structure Reelle

```text
Tasks/
  todo/   # travaux a faire
  done/   # travaux termines / historiques
  ideas/  # notes et pistes
  README.md
```

## Convention de Nommage

Format prefere:
- `P{phase}_{numero}_{slug}.md`

Exemples:
- `P2_08_FINAL_TESTING.md`
- `P4_10_MULTI_ROM.md`

## Utilisation

- Ajouter une nouvelle tache dans `todo/`.
- Quand la tache est terminee: deplacer vers `done/`.
- Garder les fichiers `done/` comme journal technique (ils peuvent decrire des approches superseded).

## Remarque Importante

Les fichiers de `Tasks/done/` documentent l'historique d'implementation, pas forcement l'etat courant exact du code.
La source de verite actuelle reste:
- code dans `client/`, `server/`, `config/`
- docs actives dans `README.md`, `QUICKSTART.md`, `docs/`

## Liens utiles

- `docs/TESTING.md`
- `docs/RUN_AND_BUN.md`
- `docs/MEMORY_GUIDE.md`
- `docs/CHANGELOG.md`

Derniere mise a jour: 2026-02-12
