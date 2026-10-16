---
description: How to design standing/scheduled agents with checkable goals - role, schedule, delivery, and a goal reality can be measured against. Use when creating recurring agents, routines, or monitoring loops.
---

# Goal loops — designing standing agents that actually work

**Owner:** `teams/ai-engineer` — accountable for how standing and scheduled agents are given checkable goals.

_How to write an agent (hub Agents tab / Vesper "spin up an agent"). The frame:
you're onboarding an employee. A good loop = a clear role + a schedule + a delivery +
a CHECKABLE goal. The last one is where people trip._

## The anatomy of a loop
1. **Role** — what they review/do each run, concretely. ("Review all portfolio activity:
   tenant requests, renewals, maintenance, arrears, follow-ups. Flag what should've been
   delegated, automated, or escalated.")
2. **Schedule** — when it runs. `weekly:fri:17:00`, `monthly:01:09:00`, `daily:07:00`.
3. **Delivery** — where the report lands. Telegram, email, or kept in the hub.
4. **Goal** — the outcome to measure reality against. THIS is the hard part (below).

## The goal must be checkable (the #1 failure)
"Good investment" is not a goal — there's no way to check a portfolio against it. A
checkable goal names the criteria:
- ❌ "Make good investments."
- ✅ "Allocation within 5% of my target mix; no single position over 10%; on track for
  £X by 2035."
- ❌ "Keep the properties running well."
- ✅ "Every unit occupied at target rent; arrears under 5%; zero missed compliance dates."

Rule: if the agent can't compare reality to the goal and say "on track / off by this
much", the goal is too vague. The hub prompt enforces this — given a vague goal, the
agent is told to say so and state what criteria would make it measurable. (This is CP-1
and Definition of Done applied to a standing worker: no checkable target, no real loop.)

## Two worked examples (the owner's)
**Property Manager** — `weekly:fri:17:00`, deliver Telegram.
Role: review all portfolio activity (tenant requests, renewals, maintenance, leasing,
arrears, follow-ups); flag what should've been delegated/automated/escalated.
Goal: full occupancy at target rent, arrears < 5%, no missed compliance dates.
Output: highest-leverage actions for the coming week.

**Investment Strategist** — `monthly:01:09:00`, deliver Telegram.
Role: evaluate the portfolio against my investment criteria and long-term goals.
Goal: allocation within 5% of target; no position > 10%; on pace for the 2035 number.
Output: where reality is diverging from strategy + corrective actions.

## The safety line (unchanged)
An agent observes, measures against the goal, and REPORTS. It never acts — every
suggested action is for the owner (or a gated engine) to execute. A loop can tell you
the rent is overdue and draft the chase; sending it stays behind the rituals.
