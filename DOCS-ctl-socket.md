# Control socket: implementation notes

How the root daemon's `ctl.sock` (contract: `DOCS-web-control-api.md`, "Control
socket") is built. Code: `steam_backlog_enforcer/_ctl_*.py`; client for the web
server: `_ctl_client.py` (results in `_ctl_types.py`, errors in `_ctl_protocol.py`).

## Trust

- Root (uid 0) is admitted besides the desktop user: root can already do all of
  this directly, so refusing it protects nothing and it keeps recovery/tests on
  one interface. Any other uid is closed unanswered (client: `DaemonUnreachableError`).
- A second `enforce` (manual run, `--demo`) never takes the socket from a live
  daemon; `--demo` never serves.
- The daemon re-checks the CLI's locks with the same tables
  (`_command_locks.py`): under a total block only `gaming_unblock` works; under
  the manual-pick lock `store_unblock` and `block_gaming` are `locked`.
- Ops run on connection threads and take the enforce loop's `tick_lock`, so they
  never interleave with a pass; the loop reloads state under that lock.

## Differences from the contract

- Daemon-only error codes: `op_failed` (the privileged action ran and failed, or
  an unexpected exception) and `unsupported` (restart asked of a daemon systemd
  does not supervise: the exit would be a stop). Not in `ApiErrorCode`; the web
  server should map unknown daemon codes to a 502.
- The two-phase reply uses `pending_id` (the contract's `PendingAction.id`) and an
  extra `lapse_after_seconds`; the server maps it.
- `block_gaming` is capped at 1..365 days and refused while a block is active.
- `gaming_reset_arm` while one is armed returns the existing pending action
  (same `pending_id`, same `ready_at`): re-arming can neither shorten nor extend
  the wait. Pending resets live in daemon memory, so a daemon restart drops them
  (fail closed: arm again).
- Test-only: `SBE_CTL_TEST_COUNTDOWN_SECONDS` (1..299) in the unit's environment
  shortens the countdown for VM runs. It cannot lengthen it; unset means 300 s.

## Gaming reset

`_gaming_reset.reset_today`, shared with the CLI: zeroes billed time and per-game
attribution, re-arms warnings, releases the mounts, keeps earned time (`carry`,
`budget_seconds`; the old CLI path dropped both), and writes a `manual_adjustment`
record to `/var/log/steam-backlog-enforcer/budget.jsonl` (billed seconds and
per-game breakdown before). That record is the auditable trail; the per-day
history mirrors current billed time, so it shows the day as quiet.

## What a restart does and does not lose

`restart` sets a flag; the enforce loop finishes its pass, runs one more
accounting tick (billing the time since the last tick), leaves an exit-time
marker (`_ctl_gap.py`), and exits 0; `Restart=always` brings it back after
`RestartSec=5`. The new daemon spends the marker on its first tick, billing the
whole downtime. Everything else already lives on disk after every tick:

| State | Survives? | Why |
|---|---|---|
| Billed seconds, per-game attribution | yes | `playtime_state.json` saved every tick; the final tick bills up to the exit, the first tick of the new daemon bills the gap |
| Cutoff / kill-grace timing | yes | `blocked_at` is persisted; `_sustain_block` measures from it |
| Playtime mounts (the block itself) | yes | kernel mount table; `reconcile` is mountinfo-driven. `RuntimeDirectoryPreserve=yes` keeps the stub file |
| Fired warnings, carry ledger | yes | in `PlaytimeState` |
| Open store window | yes (blip) | deadline in `state.json`; startup re-blocks the store once, the first tick re-opens it |
| Total block | yes | lock file, guard-lib |
| Armed gaming reset | no | memory only: arm again (fails closed) |
| Audit-journal "last verdict", history throttle | no | cosmetic: one extra `verdict_change` line, one extra history write |

Why the gap is billed explicitly: the budget clamps each tick's delta to
`2 x ENFORCE_INTERVAL` = 6 s so a suspend cannot inflate it, which would forgive
the restart gap (`RestartSec` + interpreter start + startup pass, seconds to tens
of seconds) and make a restart repeatable free play. The marker is deleted
before use, expires after 300 s and only a requested restart writes one, so a
crash or a long outage still goes through the normal clamp. Downtime nothing
enforces: an unauthorised game started in the gap is killed on the first tick;
the budget cutoff and its mounts persist throughout.

Rate limit: 1 per 10 minutes, persisted in
`/var/lib/steam-backlog-enforcer/ctl_restart.json` (root, 0600) so restarting
the daemon does not reset it.
