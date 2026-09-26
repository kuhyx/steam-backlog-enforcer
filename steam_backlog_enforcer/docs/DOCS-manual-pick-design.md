Add an option to pick a specific game manually (by providing its steam id)
Picking a game should work like this:
1. user invokes script with specific flag for picking a game manually
2. user provides game steam id (in testing use 489830)
3. Script shows what game it believes this id means (in this case it should show The Elder Scrolls V: Skyrim Special Edition)
4. user confirms that this is the game they want to pick and confirm that they will not be able to use the script for up to 2 weeks or until they earn one new achievement in it (originally: 100% achievements; see "Release rule" below)

When user picks a game manually this should override the current pick if it exists
After picking manually backlog enforcer should make a note of that and very aggressively disallow user to do anything else
for a period of 2 weeks or until user earns a new achievement in the given game
Logic should be as follows:
    1. backlog checks if a user picked game manually
        a. if not -> continue as before
    2. if yes check if the game earned a new achievement since it was picked
        a. if yes -> continue as before
    3. if NOT show info that user picked a specific game manually and they have to earn a new achievement in it before using ANY OTHER functionality of backlog enforcer

test the functionality with 489830 (The Elder Scrolls V: Skyrim Special Edition)
as always first write full functionality confirm that it works alone and with the user and only AFTER that write tests and coverage and fix issues

## Abandoning a pick (added 2026-07-19, grace window removed 2026-08-24)

A manual pick can be a mistake, and with no way out the user is stuck for the
full 2 weeks. A pick is never irreversible:

- `abandon-pick <app_id>` backs out of a pick at any time, however long ago
  it was made. There is no grace window.
- The app_id must be passed explicitly and must match the active pick, so an
  abandon cannot be triggered by muscle memory.
- `abandon-pick` is in `_MANUAL_LOCK_EXEMPT_COMMANDS` — otherwise the
  pre-dispatch lock check in `main()` would block the only way out.
- Abandoning clears the lock **and** the assignment, uninstalls the game, and
  puts it on the existing `skipped_until` cooldown for
  `ABANDON_COOLDOWN_DAYS = 30` so `scan` does not hand it straight back.
- `_actions.abandon_manual_pick` is state-only (no uninstall), matching the
  `apply_manual_pick` rule, so the MCP `abandon_pick` tool can reuse it. Both
  MCP tools stay gated behind `confirm=True`.

The lock-active message advertises `abandon-pick` for every active pick, and
the `pick-manual` warning mentions it up front.

## Concurrent manual picks (added 2026-07-19)

`Config.max_manual_picks` (default 2) is how many games may be locked in at
once. All active picks stay installed, visible and un-killed; the lock
releases only when every pick is released (one new achievement), finished or
past its own 14-day deadline.

- `State.manual_picks` is the list of `{app_id, game_name, started_at}`
  entries. The old single-slot `manual_pick_*` fields are still read on load,
  migrated into the list, then cleared — a live lock survives the upgrade.
- `_actions.allowed_app_ids(state)` (assignment ∪ active picks) is the single
  source of truth for "may exist". `uninstall_other_games`,
  `hide_other_games`, `enforce_allowed_game` and `_guard_installed_games` all
  take that set instead of one app id.
- `pick-manual` is in `_MANUAL_LOCK_EXEMPT_COMMANDS` so another game can be
  added while earlier picks hold the lock; the cap is what limits it. Its
  post-pick cascade operates on the whole allowed set, so adding a pick never
  tears down an earlier one.
- `abandon-pick <app_id>` drops only that pick; a survivor inherits the
  assignment and keeps the lock.
- `cmd_done` still releases `current_app_id` and auto-picks a replacement, so
  the remaining picks stay queued. A released pick leaves the active set
  automatically via its `released_at` stamp (or `finished_app_ids` at 100%) —
  no pruning needed — but *something* has to stamp it; see the next point.
- **The release rule is checked per pick, not just for the assignment**
  (`_pick_completion.py`). Picks used to be released only from
  `cmd_done`/`do_check`, and both look at `current_app_id` alone — so a pick
  that was not the current assignment had no achievement-based release path
  and sat on its slot until the 14-day expiry. `retire_completed_manual_picks`
  now re-checks every active pick and releases the ones with a new
  achievement, so the cap can never refuse on behalf of one. It runs from
  `pick-manual`, `status`, `check`, the MCP `pick_manual` tool, and the enforce
  loop (throttled to once every `MANUAL_PICK_RECHECK_TTL_SECONDS`, since that
  loop ticks every 3s).
  - A pick whose achievements cannot be read — the game has none, or Steam is
    unreachable — stays locked. Unknown must never look like progress.
  - Retiring frees the slot and nothing more: it never calls `pick_next_game`,
    so freeing a slot cannot hand you an unrequested extra game.
  - Releasing never evicts. A released, finished or expired pick stays in
    `State.manual_picks`, and therefore in `allowed_app_ids`, installed and
    playable for as long as the user wants. Only an explicit choice of another
    game — a new `pick-manual`, or accepting the next assignment in
    `done`/`check`/`pick`/`scan` — calls `drop_inactive_picks`, after which
    enforcement may remove them. `abandon-pick` works on them too. When no
    replacement is accepted, the current game stays assigned.
  - `mark_finished` is the single writer of `finished_app_ids`, so the sweep
    and `done`/`check` cannot both record the same completion.

## Release rule: one new achievement (changed 2026-09-26)

Requiring 100% achievements locked the user onto one game for weeks, which
proved ineffective. Now the assignment and every manual pick release as soon as
**one achievement is unlocked after the game was assigned**
(`_assignment_progress.py`).

- "After" is judged by Steam's per-achievement `unlock_time` against a
  baseline: an active pick's `started_at`, otherwise
  `State.current_assigned_at`. `record_assignment` is the only writer of that
  field and of `last_assigned_at`. An unknown baseline never releases.
- On upgrade, `State.load` backfills the baseline once and saves it: a pick
  keeps its `started_at`; a plain assignment gets "now", so older unlocks do
  not count.
- `finished_app_ids` still means **100% complete** and nothing else. A game
  released below 100% gets `released_at` (on the pick and in
  `State.released_at`) and a 7-day `skipped_until` cooldown, then returns to
  the pool.
- Next pick order: least recently assigned first (never-assigned games lead),
  then shortest HLTB time, so the same short game does not come straight back.
- Tampering detection compares a released game by unlock time after
  `released_at`, because its snapshot row predates the legitimate unlocks.
- The enforce daemon now reloads every `State` field each tick. It saves state
  from its pick sweep, and a stale copy of any field would overwrite what the
  CLI wrote.

**Deployment note:** the enforce daemon holds the allowed set in code, so
`sudo systemctl restart steam-backlog-enforcer` is required after upgrading.
A pre-upgrade daemon only knows `current_app_id` and will uninstall the other
pick as "unauthorized" within seconds — this happened once during development.
