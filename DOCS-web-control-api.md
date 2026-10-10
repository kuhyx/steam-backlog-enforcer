# Web control API (contract)

The web UI replaces `run.sh` as the primary way to drive the enforcer. Every
CLI command is reachable from the UI; the CLI stays as the backend, the
systemd entry point and the recovery path. This file is the frozen contract
between the Python server, the root daemon and the React app. The TypeScript
mirror is `web/src/api/contract.ts`; change both together or neither.

## Trust model

- The web server is an unprivileged **user** unit on `127.0.0.1:8000`.
- Privileged work goes to the **root daemon** over `/run/steam-backlog-enforcer/ctl.sock`
  (see "Control socket"). The web server never gets root.
- **Friction lives at the trust boundary, never only in the browser.** Typed
  phrases, countdowns and the unblock cap are checked
  by the server (unprivileged ops) or the daemon (privileged ops). The test:
  if `curl` can do it without the UI, it is not gated.
- **There is no way to stop or disable the enforcer** — not in the UI, not
  in the CLI, not on the socket. Restart is allowed (it comes back anyway,
  `Restart=always`), rate-limited, and only after the daemon flushed state.

## Web server auth

- `Host` must be `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding).
- Every non-GET request must carry `Origin` equal to the served origin.
- A per-launch token (32 random bytes, hex) is written to
  `$XDG_RUNTIME_DIR/steam-backlog-enforcer/web-<port>.token` (mode 0600; one
  file per port, so a second server never clobbers the live one's) and
  injected into `index.html` as `<meta name="sbe-token" content="…">`.
  Mutating requests send it as `X-SBE-Token`; `EventSource` sends it as
  `?token=`. Missing or wrong token → `403 bad_token`; the UI then reloads
  the page once (at most once per 30 s) to pick up a restarted server's token.
- Dev (`npm run dev`): Vite proxies `/api` to `127.0.0.1:8000` (`SBE_PORT`
  overrides) with `Host` and `Origin` rewritten to that origin, and injects
  the token meta from that port's token file (serve only, never in a build).
- Secrets (`steam_api_key`) are write-only: accepted by `POST /api/setup`,
  never returned by any endpoint.

## Endpoints

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/api/dataset` | – | `WebDataset` (exists) |
| GET | `/api/budget` | `?demo=1` | `BudgetSnapshot` (exists) |
| GET | `/api/status` | – | `StatusPayload` (`status_payload()`) |
| GET | `/api/stats` | – | `StatsPayload` (as MCP `get_stats`) |
| GET | `/api/installed` | – | `InstalledPayload` |
| GET | `/api/library` | – | `LibraryPayload` (every owned game, see below) |
| GET | `/api/art/{app_id}` | – | `image/jpeg` portrait cover, or `404 not_found` |
| GET | `/api/commands` | – | `CommandSpec[]` — server-driven catalog |
| GET | `/api/setup` | – | `SetupStatus` (configured flags, no secrets) |
| POST | `/api/setup` | `SetupRequest` | `SetupStatus` (validated live against Steam) |
| GET | `/api/daemon` | – | `DaemonStatus` (state, uptime, journal tail) |
| GET | `/api/server` | – | `ServerHealth` (stale?, started_at, version) |
| POST | `/api/server/restart` | – | `202`; the user unit restarts the process |
| GET | `/api/backups` | – | `StateBackup[]` |
| POST | `/api/backups/{id}/restore` | `{confirm_phrase}` | `Job` |
| GET | `/api/jobs` | – | `Job[]` newest first, last 50 |
| POST | `/api/jobs` | `JobRequest` (`confirm_phrase` for every friction command, countdown ones included) | `Job` (`201`) or `PendingAction` (`202`) |
| GET | `/api/jobs/{id}` | – | `Job` |
| GET | `/api/jobs/{id}/events` | `?token=&after=<seq>` | SSE stream of `JobEvent` |
| POST | `/api/jobs/{id}/answer` | `PromptAnswer` | `204` |
| POST | `/api/jobs/{id}/cancel` | – | `204` (only if `CommandSpec.cancellable`) |
| POST | `/api/pending/{id}/heartbeat` | – | `PendingAction` |
| POST | `/api/pending/{id}/commit` | `{confirm_phrase}` | `Job` |
| DELETE | `/api/pending/{id}` | – | `204` |

Errors are `{"error": "<code>", "message": "<human text>"}` with a 4xx/5xx
status. Codes: `bad_token`, `bad_origin`, `bad_host`, `unknown_command`,
`invalid_params`, `not_found` (404: unknown job, backup or endpoint),
`wrong_phrase`, `locked` (manual-pick / total-block lock),
`busy` (another mutating job is running), `countdown_running`,
`pending_lapsed` (also for an unknown pending id: the daemon cannot tell
one from a lapsed one), `daemon_unreachable`, `rate_limited`,
`not_cancellable`, `op_failed` (502: a daemon op raised, or a job process
could not be started — that job is then already `failed`), `server_stale`
(503 on every `/api/*` but `/api/server` while the server retires on
outdated code), `unsupported`. A locked command is refused as `locked` even
while another job is running (the lock is checked before `busy`).
`block-gaming` days are capped at 1–365 by the daemon.

### Library (`/api/library`, `/api/art/{app_id}`)

`LibraryPayload` is `{games: LibraryGame[]}`, one row per owned game (the
owned-games records joined with the achievement snapshot, so games without
achievements are listed too), in no particular order — the UI sorts:

| Field | Meaning |
|---|---|
| `app_id`, `name` | Steam app id; name from the owned records, else the snapshot |
| `achievements_total`, `achievements_unlocked` | `0`/`0` when the scan has no data for it |
| `hltb_hours` | completionist hours (HLTB cache, else snapshot), `null` when unknown |
| `playtime_minutes` | total playtime |
| `last_played` | Unix seconds of the last session, `null` when never played |
| `installed` | an `appmanifest` exists in a Steam library folder |
| `assigned` | the assignment or an active manual pick |
| `ineligible_reason` | why "pick my own game" refuses it, `null` when pickable: `No achievements` / `Not scanned yet` (not in the snapshot; the owned record's `has_stats` tells which), `No achievement data` (not in the snapshot and the cached records predate `has_stats`), `Already 100% complete` (100 % or in `finished_app_ids`), `Skipped until <date>` / `Skipped for now`. Same rule (`_own_pick.ineligible_reason`) the job enforces on the answer |

The owned records (`games` in `owned_app_ids_cache.json`) are stored by
every owned-list refresh and read at any age. Reads are local-only, except
once: when no refresh has stored records for this account yet, the view asks
Steam (`GetOwnedGames`) a single time and caches the result.

`GET /api/art/{app_id}` serves a portrait cover, first source wins:

1. Steam's librarycache, `~/.local/share/Steam/appcache/librarycache/<id>/`
   (`library_600x900.jpg` / `library_capsule.jpg`, top level or in a hash
   subdir; never the 32×32 icons or the landscape `header.jpg`).
2. This server's disk cache, `~/.cache/steam_backlog_enforcer/art/<id>.jpg`.
3. Steam's CDN, `https://shared.steamstatic.com/store_item_assets/steam/apps/<id>/library_600x900.jpg`,
   stored atomically into (2).

It is the only view that may use the network, so it is fenced: owned app
ids only (anything else is `404`; the id is an int in a fixed URL, never a
proxy), at most 6 CDN fetches at a time, `(3.05, 6)` s timeout, `image/*`
bodies ≤ 2 MiB only. A failed fetch leaves `<id>.miss` (retry-after time):
a CDN `404`/`403` or oversized body for a week, a network error or other
status for 10 minutes (the total block lists `steamstatic.com`, so art
appears once it lifts). No cover → `404 not_found`, and the UI draws a title
tile. Hits carry `Cache-Control: private, max-age=86400`. Like every GET it
needs no token, so a plain `<img src>` works.

## Jobs

Every command except pure views runs as a **job**: a subprocess
`python -m steam_backlog_enforcer.jobs run <job_dir>` that goes through the
same lock gate as the CLI (`_enforce_total_block_lock`,
`_enforce_manual_pick_lock`), then calls the command's non-interactive core
with explicit params, a `Progress` reporter and a `Prompter`.

- Job dir: `~/.local/state/steam-backlog-enforcer/jobs/<id>/` holding
  `request.json`, `events.jsonl` (append-only, one `JobEvent` per line),
  `answers.jsonl` (written by the server from `POST …/answer`) and
  `result.json`. The server only tails files, so jobs survive both page
  reloads and server restarts (including `_serve_stale` retirement).
- At most **one mutating job** at a time (`busy` otherwise). Read-only jobs
  (`check`, `stats`, `list`, …) may run alongside.
- History: last 50 job dirs kept, older ones pruned at job start. Job ids
  are `<UTC yyyymmddThhmmss + microseconds>Z-<6 hex>`, so sorting by id is
  creation order even within one second.
- A job whose process cannot be started (e.g. `systemd-run --scope` failing)
  is marked `failed` at once, with the launcher's output in its log, and
  `POST /api/jobs` answers `op_failed`.

### JobEvent (one JSON object per line)

```jsonc
{ "seq": 7, "ts": "2026-10-10T12:00:00Z", "type": "progress",
  "step": 3, "total": 12, "label": "Fetching HLTB times", "item": "Hades",
  "eta_seconds": 41 }
```

`type` is one of:

- `state` — `{state}` job lifecycle transitions (`JobState`).
- `log` — `{level, message}` the human-readable line the CLI would print.
- `progress` — `{step, total, label, item?, eta_seconds?}`; `total` may be
  `null` for indeterminate phases. Any operation over 2 s must emit
  determinate progress.
- `prompt` — `{prompt_id, kind, message, options?, phrase?, default?,
  app_ids?}`; `kind` is `choice` (pick one of `options`), `confirm`
  (yes/no), `phrase` (type `phrase` exactly), `text` or `game`. The job
  blocks until the answer arrives. Phrase answers are re-checked by the job,
  not the UI.
  - `game` ("Pick my own game…" in `pick`/`check`/`done`): the UI shows the
    library browser in pick mode; `app_ids` (sorted) are the only games the
    job accepts — the event carries ids only, the rows come from
    `/api/library`. Answer the app id as a decimal string, or `""` to go back
    to the `choice` prompt that offered it. The job re-validates: any other
    answer logs a `warning` and re-asks with a new `prompt_id`. The CLI keeps
    its text search for the same step.
- `result` — `{ok, summary, data?}` exactly once at the end.

## Friction (server/daemon-enforced)

| Command | Phrase (exact) | Extra |
|---|---|---|
| `gaming-reset` | `reset today's gaming budget` | daemon two-phase: arm (phrase required: `POST /api/jobs` with `confirm_phrase`) → 300 s with heartbeats every ≤10 s → commit (phrase required again: `POST /api/pending/{id}/commit`); lapses if a heartbeat is missed by >15 s; logged to the ledger |
| `block-gaming` | `block all gaming for {days} days` | daemon; no undo |
| `unblock` / `buy-dlc` | `unblock the store for {minutes} minutes` | daemon; 1–30 min cap |
| `gaming-unblock` | `force release playtime mounts` | daemon; if unreachable the UI shows the `sudo ./run.sh gaming-unblock` fallback |
| `abandon-pick` | `abandon {game_name}` | – |
| `pick-manual` | `lock in {game_name}` | – |
| `add-exception` | `request exception for {game_name}` | active immediately (no cooldown since de76c65); reason logged |
| `uninstall` | `uninstall {count} games` | – |
| `reset` | `wipe all enforcer state` | automatic timestamped backup first |
| backup restore | `restore backup {id}` | – |
| `enforce` restart | – | rate limit: 1 per 10 min, state flushed first |
| `enforce` demo (`demo: 1`) | – | desktop-user job, cancellable; runs the gaming budget only and never touches the daemon's Steam-binary mounts; fails (exit 1) under a total block |

`CommandSpec.friction` carries the phrase template so the UI never
hard-codes it.

## Control socket (root daemon)

- Path `/run/steam-backlog-enforcer/ctl.sock`, created by the root daemon,
  mode `0660`, group = the desktop user's primary group.
- Every connection is checked with `SO_PEERCRED`: uid must equal the
  configured desktop user's uid, else the connection is closed unanswered.
- Protocol: one JSON request line → one JSON response line, then close.
  Request `{"op": "<op>", "args": {…}}`, response `{"ok": true, "data": …}`
  or `{"ok": false, "error": "<code>", "message": "…"}`.
- Allowlisted ops only: `ping`, `status`, `journal_tail{lines}`,
  `store_unblock{minutes, phrase}`, `block_gaming{days, phrase}`,
  `gaming_unblock{phrase}`, `gaming_reset_arm{phrase}`,
  `gaming_reset_heartbeat{pending_id}`, `gaming_reset_commit{pending_id, phrase}`,
  `gaming_reset_cancel{pending_id}`, `restart{}`. There is no `stop`.
