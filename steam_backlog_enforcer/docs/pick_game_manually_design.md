Add an option to pick a specific game manually (by providing its steam id)
Picking a game should work like this:
1. user invokes script with specific flag for picking a game manually
2. user provides game steam id (in testing use 489830)
3. Script shows what game it believes this id means (in this case it should show The Elder Scrolls V: Skyrim Special Edition)
4. user confirms that this is the game they want to pick and confirm that they will not be able to use the script for up to 2 weeks or until the game is completed (100% achievements)

When user picks a game manually this should override the current pick if it exists
After picking manually backlog enforcer should make a note of that and very aggressively disallow user to do anything else
for a period of 2 weeks or until user completes a given game
Logic should be as follows:
    1. backlog checks if a user picked game manually
        a. if not -> continue as before
    2. if yes check if the game is completed
        a. if yes -> continue as before
    3. if NOT show info that user picked a specific game manually and they have to finish it before using ANY OTHER functionality of backlog enforcer

test the functionality with 489830 (The Elder Scrolls V: Skyrim Special Edition)
as always first write full functionality confirm that it works alone and with the user and only AFTER that write tests and coverage and fix issues

## Grace period (added 2026-07-19)

A manual pick can be a mistake, and with no way out the user is stuck for the
full 2 weeks. There is now a short mistake-correction window:

- `MANUAL_GRACE_DAYS = 4` — for 4 days after the pick, `abandon-pick <app_id>`
  backs out of it. Outside that window the command refuses and exits 1.
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

The lock-active message advertises `abandon-pick` only while the window is
still open, and the `pick-manual` warning mentions it up front.

## Two concurrent manual picks (added 2026-07-19)

`Config.max_manual_picks` (default 2) is how many games may be locked in at
once. Both stay installed, visible and un-killed; the lock releases only when
every pick is finished or past its own 14-day deadline.

- `State.manual_picks` is the list of `{app_id, game_name, started_at}`
  entries. The old single-slot `manual_pick_*` fields are still read on load,
  migrated into the list, then cleared — a live lock survives the upgrade.
- `_actions.allowed_app_ids(state)` (assignment ∪ active picks) is the single
  source of truth for "may exist". `uninstall_other_games`,
  `hide_other_games`, `enforce_allowed_game` and `_guard_installed_games` all
  take that set instead of one app id.
- `pick-manual` is in `_MANUAL_LOCK_EXEMPT_COMMANDS` so a second game can be
  added while the first holds the lock; the cap is what limits it. Its
  post-pick cascade operates on the whole allowed set, so adding a pick never
  tears down an earlier one.
- `abandon-pick <app_id>` drops only that pick; a survivor inherits the
  assignment and keeps the lock.
- `cmd_done` still finishes `current_app_id` and auto-picks a replacement, so
  two games stay queued. A finished pick leaves the active set automatically
  via `finished_app_ids` — no pruning needed.

**Deployment note:** the enforce daemon holds the allowed set in code, so
`sudo systemctl restart steam-backlog-enforcer` is required after upgrading.
A pre-upgrade daemon only knows `current_app_id` and will uninstall the other
pick as "unauthorized" within seconds — this happened once during development.
