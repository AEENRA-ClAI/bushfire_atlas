# The project file — `docs/projects/<id>.md`

<!-- CANONICAL in toolbox/library/pm/ (checked out to .toolbox/pm/). Edit here, then check out.
     Decision F26 (owner 2026-10-14). -->

A project is a piece of work with a scope and pass/fail gates that may span several repos. It is
declared **once, in its home repo**, as `docs/projects/<id>.md`, and read headless by `pm.py` and
by `handover.py` at session start. The file is the store: no database, no copy in another repo.

## The shape

```
---
id: headless-pm
title: Headless project management
status: active
owner: Alicia
home: toolbox
repos: toolbox, janet_lite, project-management
horizon: 2026-11
---

# Headless project management

## Scope

| side | item |
|---|---|
| in | the project file format and the `pm` CLI |
| out | a UI, a database |

## Objectives

| id | objective | gate (checkable) | status | evidence |
|---|---|---|---|---|
| O1 | the format and the CLI | `python -m pytest tests/test_pm.py -q` passes | PASS | PR #288 |
| O2 | a weekly roll-up to Telegram | the owner receives one | open | |

## Owner decisions

| date | decision | where |
|---|---|---|
| 2026-10-14 | option B: a file per project in its home repo | project-management docs/HEADLESS_PM_DESIGN.md |

## Next

- free text; backlog rows that serve the project carry `[P:<id>]`
```

## The rules `pm` enforces (a broken rule is "could not read <file>: <why>", never a blank)

- **The front block** is the first thing in the file, between two `---` lines, one `key: value`
  per line. Required: `id`, `title`, `status`, `repos`. Optional: `owner`, `home`, `horizon`,
  `started`. Any other key is an error, so a typo cannot pass as an empty field.
- **`id`** is lower-case letters, digits and dashes, and equals the file name.
- **`status`** is one of `proposed`, `active`, `paused`, `done`, `dropped`. Only `active`
  projects are printed at session start and by `pm next` with no id.
- **`repos`** is comma-separated: every repo the work touches, the home repo included.
- **`## Scope`** is a table whose rows start with `in` or `out`.
- **`## Objectives`** has at least one row: `id | objective | gate | status | evidence`. The gate
  is required and must be checkable (a named test, a command's output, something she sees on her
  box). Status is `open`, `PASS`, `PARTIAL` or `FAIL`, scored at a session's end, by the session
  or the owner, never by an agent on its own.
- **`## Owner decisions`** (optional) is `date | decision | where`. It points at the repo's
  `docs/DECISIONS.md` rows rather than replacing them.
- The **next open objective** is the first row, in file order, that is not `PASS`.

## The commands

| command | what it does |
|---|---|
| `pm.py status [--fleet ROOT]` | every project here, or in every repo under ROOT, with its score and next open objective |
| `pm.py scope <id>` | the scope, objectives and decisions of one project |
| `pm.py next [<id>]` | the open objectives (of every active project, or one), plus `[P:<id>]` backlog rows |
| `pm.py score <id>` | the PASS / PARTIAL / FAIL / open tally and the evidence |
| `pm.py new <id> --title "…"` | scaffolds the file; refuses to overwrite. The only command that writes |

Every read command takes `--json` and `--root`. Exit code 1 means the named project was not
found or could not be read.
