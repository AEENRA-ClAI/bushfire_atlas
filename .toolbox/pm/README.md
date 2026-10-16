# pm — headless project management

`pm.py` reads the fleet's project files (`docs/projects/<id>.md`, format in
[PROJECT_FORMAT.md](PROJECT_FORMAT.md)) and writes nothing except a new one. Stdlib only.

```
python .toolbox/pm/pm.py status --fleet ..     # in an app checkout
python library/pm/pm.py status --json          # in the toolbox
```

`handover.py` (bundle `instincts`) imports `pm.py` from the sibling folder to print the active
projects at session start; with no project file it prints nothing. The story is
`docs/features/headless-pm.md` in the toolbox.
