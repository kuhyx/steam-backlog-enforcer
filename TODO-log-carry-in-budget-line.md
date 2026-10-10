# Log the Fri->Sat/Sun/Mon carry in the budget resolver line

Carried over from the 2026-10-10 tutor-cutover handoff (item 4b, optional).

## what
Saturday's budget showed 15144 s = 14400 + 744 s carried over from Friday
(`_gaming_days.py` `pass_on`, commit 9586128). That is intended, but the
"Gaming budget ..." log line (`_budget_resolve.py` ~:176) does not show the
carry, so the number looks wrong. Include the carry seconds in that line.

## where
`steam_backlog_enforcer/_budget_resolve.py`, carry from
`_playtime_budget.py` (`PlaytimeState.carry`).

## must
- must not: change the budget arithmetic — log only.

## done
On a carry day the journal line reads like
`Gaming budget ... (+744 s carried from Fri)`; a unit test asserts it.

REMOVE ME AFTER FINISH
