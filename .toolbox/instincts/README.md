# Instincts — the fleet's learned memory

`instincts.json` holds patterns the fleet earned the hard way, each with its **evidence** and a
**confidence** (0-1). `inject.py` reads them and prints the most confident, in-scope ones as a
compact markdown block, so a fresh session **starts already knowing** what we learned — the
"optimize the context window, persist everything else" idea, in our idioms.

This is the **instincts** layer of the memory model:
- **Rules** (always-loaded) = each repo's `CLAUDE.md`.
- **Instincts** (learned, confidence-scored, injected above a threshold) = *this*.
- **Hooks** (session automation) = the SessionStart hook below, which does the injecting.
- **Auto-extraction** (built) — `data_library/tools/mine_instincts.py` reads session material
  (recent commits, a handover/docs dir) and has the local brain propose grounded candidate
  instincts. Candidates are **capped below the inject threshold, marked `source: auto`, deduped**
  against this store, and written to a review file — never auto-written here. A human promotes the
  real ones into `instincts.json` (raising the confidence). The brain proposes; a human curates.
- **Handover carry-over** (built) — `handover.py` closes the loop the *other* way. Session cleanup
  writes a handover with a **Roster** line (the agents the next session's work needs) and a
  **Leftover / for review** checklist (open items, each tagged with the agent that should look at
  it — see `HANDOVER_TEMPLATE.md`). At the next SessionStart the reader finds the newest handover,
  parses those two, and prints them — so the session opens already knowing WHICH agents to pull in
  and WHAT to pick up, and the leftover work gets looked over instead of being lost.

## The handover → roster → startup loop

The housekeeper (session-cleanup) fills the handover from `HANDOVER_TEMPLATE.md`:

- **`Roster:` line** — the rosters/agents the leftover work needs (`data_reviewers, security-reviewer,
  deep-research`). A repo already loads a base roster via its manifest (`agents:`); this line names
  the extra specialists *this* leftover work wants, so the next session pulls them in deliberately.
- **`## Leftover / for review` checklist** — every open item to carry forward, each prefixed with its
  owning agent in `(parens)`. This is also where work an agent *should have* reviewed but didn't gets
  parked, so it's the first thing looked over next startup.

`handover.py` is honest-empty at every step: no handover, or no roster/leftover in it, prints nothing
and never breaks a session. It ships in this `instincts` bundle beside `inject.py`, so an app that
subscribes to `instincts` gets it on checkout and runs it from the same SessionStart hook.

Since v15 its start-of-session block also names each **active project** in the repo's
`docs/projects/` with its next open objective and gate (F26). It reads them through the `pm`
bundle's `pm.py`, from the folder beside this one; with no project file it prints nothing.

## Wiring the SessionStart hook (how a session gets them)

An app subscribes to the `instincts` bundle (manifest) and checks it out into `.toolbox/instincts/`.
Then a **SessionStart hook** in the app's `.claude/settings.json` runs the checked-out injector:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command",
        "command": "python .toolbox/instincts/inject.py --scope <app>" } ] }
    ]
  }
}
```

`--scope <app>` keeps the instincts tagged for this app plus the fleet-wide `all` ones. The hook is
**read-only and honest-empty** — if the bundle isn't checked out, or nothing clears the confidence
bar, it prints nothing and the session starts normally. Never let the memory layer break a session.

Env knobs: `INSTINCT_CONFIDENCE_THRESHOLD` (default 0.7) · `MAX_INJECTED_INSTINCTS` (default 6).

## Curating

Edit `instincts.json`: add an instinct with its evidence, raise a confidence as evidence
accumulates, lower it when it stops holding, retire one that's now a rule. Keep each `action` a
single imperative sentence and always cite real `evidence`. Author here; apps check it out.

## Since v13 (2026-10-14)

- `merge_guard.py`: run before every merge [F23]. It checks that the branch carries the latest `development`, that
  every changed file was changed by the branch's own commits, and that no line another session added
  after the branch started is removed. Exit 0 clean, 1 look, 2 could not check.
- `session_end.py`: the one command behind the owner's one word, "handover" [F24]. It runs the merge
  guard, the full suite (from CLAUDE.md's "Full suite" line), the records and a git-state check, then
  lists the steps only Claude can do.
- `WRITING_GOOD_CODE.md`: how to write good code in this fleet, read before the first line of code.

## Since v17 (2026-10-19)

- `board_items.py`: the one way a session changes its repo's cards on Janet's Runs → Board
  (`docs/board_items.json`; data_library's pipelines in `catalog/pipeline_reviews.json`): `check`,
  `summary`, `list`, `add`, `move`, `done`, `review`. Every change stamps the date and a history line,
  and a newer date in the file outranks the owner's older move on the board [F28].
- `session_end.py` step 3c runs `board_items.py summary`; the End list gained "Update the board", and
  the handover template a **Board moves** section.

## Since v18 (2026-10-19)

- `board_items.py decided` puts a decision on a card's trail; `--supersedes` marks the direction
  changing, and Janet strikes the old one through. `retire --why` sends a dropped idea to Retired
  with its reason. `--command` / `--where` put a copy-paste command on a card: Janet's board copies
  it, and sends it to Jobs when a recipe already runs it.
