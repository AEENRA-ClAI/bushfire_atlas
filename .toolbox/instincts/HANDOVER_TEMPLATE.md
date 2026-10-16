# Handover — <YYYY-MM-DD> <session topic>

<!--
CANONICAL HANDOVER SHAPE (toolbox — author here, apps read the checked-out copy).

The housekeeper fills this at session cleanup. Two machine-read sections close the memory loop:
`handover.py` (shipped in the `instincts` bundle, run by the SessionStart hook) finds the NEWEST
handover, reads the **Roster** line and the **Leftover / for review** checklist, and prints them at
the start of the next session — so the next session opens already knowing WHICH agents to pull in and
WHAT to pick up. Keep the two headings recognisable; the prose around them is free.
-->

**Roster:** <comma-separated agents / rosters the next session's work needs>

<!--
One line. List the rosters (crew, reviewers, data_reviewers, harness) and/or single agent slugs the
LEFTOVER work below actually needs — e.g. a data-pipeline task lists `data_reviewers, security-reviewer,
deep-research`; a UI polish lists `crew, designer`. The reader splits on commas/semicolons/"and".
Omit the line entirely if the next session needs nothing special (honest-empty — it just prints nothing).
-->

## Sprint goal and gates

<!--
OWNER 2026-10-13: "go back to this idea of having like a scrum master and like having project review
objectives and … gates on whether things passed or not."

Written at the START of the session (the scrum-master's sprint planning) and scored at the END. At
most three objectives, each with a gate that can actually be checked. Score each one:
- PASS only with evidence the gate ran;
- PARTIAL when the gate needs the owner's box (give the exact command);
- FAIL with what was learned (and carry it to Leftover).

Then a three-line retro, and the ideas parked this session (they live in docs/IDEAS.md).
-->

**Brief at the start:** <where the thread stood, what was open, what the last session said to do next>

| objective | gate | result | evidence |
|---|---|---|---|
| <the objective, in the owner's terms> | <the check that fails if it is not done> | PASS / PARTIAL / FAIL | <test name, output, commit — or the command for her box> |

**Retro:** helped — <…> · got in the way — <…> · next time — <…>

**Ideas parked (in docs/IDEAS.md):** <her words, or "none">

## What shipped this session

- <the done, merged, promoted work — for the human, not the reader>

## Conversation map (how the ideas connected)

<!--
OWNER 2026-10-13: "kind of like the map of how the conversation is going. So not just like general
anecdotes, but like how we connect different ideas."

"What shipped" lists the RESULTS. This section is the ROUTE: which idea led to which, and what
linked them. It is what a session cannot get back from the diff: why a question about X ended up
as a change to Y, which turn the owner made and why, what was tried and dropped. Without it, the
next session sees the destination and not the reasoning, and re-proposes the road already rejected.

One bullet per LINK, in the order the conversation took them, each in this shape:

    - <idea A> → <idea B>: <what joined them>

The arrow word says what kind of link it was. Use one of these, so the map can be scanned:
  * `→`            led to (A raised B, or doing A showed B was needed);
  * `⇢ turned:`    the owner changed direction (quote the sentence that turned it);
  * `✗ dropped:`   tried or proposed, then set aside (say why, so it is not re-proposed);
  * `↺ back to:`   returned to an earlier thread (name the earlier bullet's idea);
  * `⏸ parked:`    raised and left open (it should also be in Leftover below).

The "what joined them" half is the point. Prefer the owner's own words where they made the link
(quoted, dated if not today), or the finding that made it ("the run showed …", MEASURED / REASONED).
A bullet with an idea on each side and nothing joining them is an anecdote; leave it out.

Start with the first ask, in the owner's words. End with where the thread stands. Five to fifteen
links is usual; a session that was one ask and one answer is one line. The reader (`handover.py`)
prints the first 15 links at the next session start, so keep each to one line.

Honest-empty: a session with no turns worth mapping writes "one thread: <ask> → <result>". Never
an empty section — that reads as "not written".
-->

- **Start:** "<the owner's first ask, verbatim>"
- <idea A> → <idea B>: <what joined them — the owner's words, or the finding>
- <idea B> ⇢ turned: <idea C>: "<the owner's sentence that turned it>"
- <idea C> ✗ dropped: <why, so it is not re-proposed>
- **Where it stands:** <the thread as the session left it>

## Decisions recorded

<!--
OWNER 2026-10-13 (the decision register). Every standing decision the owner made this session —
a rule, a change of direction, a "from now on" — goes in `docs/DECISIONS.md` as a row with its
exact words, and the handover names the rows added. When a decision REPLACES an earlier one, the
new row's `supersedes` names the old id and the old row's status becomes `superseded by D<n>`;
`doc_records.py decisions` fails if only one side says so. That is the whole point: a rule that
outlived its reason ("run the gate before a merge", after Actions was gone) is caught when its
replacement is written, not weeks later.

A feature request is not a decision ("add a search box"); a rule about HOW work is done, what is
allowed, or which way a design goes, is. Honest-empty: "none this session".
-->

- D<n> — "<the owner's words>" (supersedes D<m> / new)

## Full suite at cleanup

<!--
THE FULL SUITE RUNS EXACTLY TWICE A SESSION: at START (the precondition that makes every scoped
run in between attributable) and HERE at cleanup. It is NOT run per merge — owner 2026-09-19:
"Only run it at the very beginning when we start a session, and only when I essentially say let's
run the handover documents. And then anything in between, only on the work that you've actually
done."

THIS SECTION IS WHY THE CLEANUP RUN IS WORTH PAYING FOR. A run whose result is not written down
has been paid for and thrown away: the next session takes its own START run with nothing to
compare against, so it cannot tell a failure it caused from one it inherited. Record the command,
the counts, and EVERY failure BY NAME — the owner's instruction is that those are where the next
session begins ("maybe those are the errors that we start with the fixing in the next one").

Name them even when they are pre-existing or environmental, and say which: a failure that is red
for a missing dependency reads exactly like a code regression, and a next session that cannot tell
the difference stops trusting the baseline entirely.
-->

**Command:** `<the repo's own full run — e.g. python scripts/gate.py, python -m pytest tests -q,
python -m unittest discover -s tests/unit_root_tests>`
**Result:** `<N passed, M failed>` at `<commit sha>`

- `<test::nodeid>` — <one line: what it asserts, and CAUSED-HERE / PRE-EXISTING / ENVIRONMENT>

<!-- No failures → say so explicitly ("0 failed"). An empty section reads as "not run". -->

## Fault hunt

<!--
RUN `fault-hunter` ON THIS REPO AT CLEANUP, once, and paste what it found.

WHY IT IS PART OF THE RITUAL rather than something to remember (owner 2026-09-24: "run the
fault hunter on each repo as part of the handover process"). The fleet has a ledger of the
faults it keeps paying for — 13 classes, and roughly half with no mechanism behind them, which
means the only thing that finds those is somebody looking. "Somebody looking" is a habit, and
this fleet has written down what habits are worth more than once. The ledger itself exists
because writing an incident up ONCE was not stopping it recurring.

It is the natural PAIR to the two sections above. `fault-analyst` works backwards over the
session record; the hunter works forwards over the code. The suite says what is RED; the hunter
says what is quietly wrong in a way no test is looking for.

WHAT TO RECORD, and this is the part that has to survive: what it SCANNED (the mechanisms it
ran, and the ones it could not, and why), then the findings with their class ids and the fix
each one's class already carries. A clean hunt is written as "scanned X, ran Y and Z, no
findings" — never as an empty section, because an empty section and an unrun hunter are the
same document, which is F008 pointed at the ritual.

A FINDING IS NOT AN OBLIGATION TO FIX IT HERE. The hunter reports; most findings belong in
Leftover below, routed to the agent its class names. Fixing one at cleanup is how a cleanup
becomes a second session.

Honest-empty is fine and normal: a repo with its mechanisms wired and nothing new to say should
produce a short section. A LONG one two sessions running is the signal.
-->

- **Scanned:** <directories, file count; which mechanisms ran, which did not and why>
- **Findings:** <class id · file:line · what triggers it · the fix from the class note — or "none">
- **Could not check:** <honest; never omitted>

## Error lessons (strategies found)

<!--
OWNER 2026-09-30: "incorporate that into the handover documents so that any lessons when we do
this pipeline build or when we're working with these errors, that we also figure out strategies to
get around things."

WHY IT IS A SECTION rather than prose somewhere below: a strategy found in one session and written
into a handover is read once, by the next session, and then lost in a folder of 130 handovers. In a
repo that has an error plan (data_library: `python -m scripts.error_manager`), a lesson recorded in
its lessons file (`catalog/error_lessons.json`, via `python -m scripts.error_lessons add`) is
PRINTED UNDER ITS ERROR GROUP in every plan after — that is the difference between a note and a
mechanism. This section is the receipt that it was recorded.

For every error this session worked, or every pipeline it built that hit a wall, list:
  * the GROUP (the error plan's key: moved-404, auth-or-gate, challenge-wall, not-json …);
  * what the label got wrong, or the way round that worked — one sentence, naming the tool/rung;
  * the evidence (a test, a PR, a plan line) and MEASURED / SIMULATED / REASONED;
  * whether it is RECORDED in the repo's lessons file (and the command used), or why not.

A lesson with no evidence is not a lesson; leave it out rather than write it up as one.
Honest-empty: "no errors worked this session" or "none new: the plan's checks covered it". Never
an empty section — that reads as "not looked at".
-->

| group | what the label got wrong / the way round | evidence (label) | recorded |
|---|---|---|---|
| moved-404 | a 404 on a GUESSED sitemap path is not a move; check whether another rung landed rows | tests/test_x.py (SIMULATED) | yes — `python -m scripts.error_lessons add …` |

## Leftover / for review (agent → item)

<!--
Every open item the next session should pick up, one bullet each. Prefix with the OWNING agent in
(parens) or [brackets] so startup routes it — `(security-reviewer) …`, `(python-reviewer) …`. An item
with no clear owner is fine (leave the parens off); it still surfaces. This is also where work an agent
SHOULD HAVE looked over but didn't gets parked, so it's reviewed next startup. Honest-empty: no open
items → drop the section (or leave it empty) and the reader prints nothing.
-->

- (<agent>) <what to do / what to look over>
- <plain item with no specific owner>

## Deliberate gaps between branches (required when any exist)

<!--
REQUIRED whenever a branch and another branch differ on purpose. "Deliberate" means someone decided the
difference should exist, so it is not an oversight waiting to be merged. Write one bullet per difference,
naming:
  - the file or feature, and the two branches (e.g. `development` vs `main`);
  - which side is intended, and the commit or PR that made the decision;
  - who decided (the owner, or the session that followed their instruction) and when.

If a difference is NOT deliberate, it is not a gap to record here. It is a leftover, and it goes under
`## Leftover / for review`. A gap recorded here is the only record that the difference was chosen, so a
later audit can tell a decision from a mistake.

Drop the section when no branch pair differs on purpose.
-->

- `<file or feature>` — `<intended branch>` is correct, `<other branch>` is behind/ahead. Decided in
  `<commit or PR>` by `<owner or session>` on `<date>`: `<why>`.

## Copy-paste (owner-side commands)

<!--
Every command this session handed the owner, VERBATIM, in fenced blocks tagged with the shell
(```powershell / ```bash). The housekeeper's `copy_paste.py` (this bundle) harvests them — and any
same-day sibling write-up's — into `docs/COPY_PASTE.md` beside `CIRCLE_BACK.md`: ONE rolling sheet, a
dated section per session, newest first (owner 2026-09-13: "a file of any copy-paste code that was in
the session … an md file that lives near the circle back"). No <angle-bracket>
placeholders: a command with one is not copy-paste and is marked ⚠. Honest-empty: no commands →
drop the section.

OUTPUTS GO TO THE DATA SIDE (owner 2026-10-12: *"the relative outputs … should follow … the file
config"*). A handed-over command never writes into the code checkout: no `> file` redirect (it lands
in whatever folder the terminal is in, which is the repo), and no hand-written script saved into the
checkout to run. Give the script's own `--out` / `--json`; in data_library and smart_analyst a
relative name there already goes to the machine's data folder (`config.paths.output_path` /
`analyst.paths.output_path`). A Windows PowerShell block starts with `cd` and has one command per
line, never `&&`; a `stash@{0}` style ref is quoted `'stash@{0}'` (PowerShell reads `{0}` as code).
-->

```powershell
git pull origin development
```

## Defaults baked in (no env var required)

<!--
STANDING RULE (owner 2026-09-15): *"every single time you start something, or you build something,
these environmental variables should be baked in with a default … this $ENV variable doesn't work
when we run, let's say, the daily briefing."*

An automation has NO environment. A Janet job, a run-queue worker, a scheduled task and the daily
brief each start from nothing — none of them inherits the env of the terminal a human typed in. So
anything that only works because a shell exported it works on the laptop and silently degrades
everywhere else, and the degradation usually looks like "no data" rather than "misconfigured".

So for every knob this session introduced, list it here with the REAL default now baked in:

| knob | baked default | where it lives |
|---|---|---|
| ANALYST_FLOW_CONCURRENCY | 1 | analyst/flows.py:_concurrency() |

Three rules for what goes in that middle column:

  * A REAL value, never a `<placeholder>` and never an ellipsis. If a human must supply it, use a
    greppable word (`paste_your_key_here`) so a missed edit is findable.
  * Env var FIRST (a human can still override), then the baked default — never env-only.
  * SECRETS ARE THE EXCEPTION and are never baked. What gets baked is the committed PATH the secret
    is read from, so an automation finds the file with nothing exported. Name that path here.

Honest-empty: introduced no knobs → drop the section.
-->

## Notes / context

- <anything the next session needs that isn't a roster or a leftover item>
