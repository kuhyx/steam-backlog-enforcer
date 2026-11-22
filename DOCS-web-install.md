# `install` and `repair-ghosts` jobs

Part of the web control API ([DOCS-web-control-api.md](DOCS-web-control-api.md));
the TS mirror of the result is `InstallResultData` in `web/src/api/contract.ts`.

All three params are optional (`_command_params.PARAMS["install"]`):

- `target` (string): an AppID, a Steam URL (`…/app/<id>/…`) or a name, as
  the installer's own `TARGET` argument. The job resolves it, never the
  installer: inside the games allowed today, which are `allowed_games(state)`
  plus the approved exceptions (named from the owned records). AppIDs and URLs
  are parsed locally; names match exact title first, then substring (case
  ignored), with no Steam search. Several matches → a `choice` prompt; no
  match, or an id outside that set → the job fails (`locked`) and no
  installer runs. The installer only ever gets the checked `--appid`.
  Without `target`, the job offers every allowed game not yet fully
  installed, approved exceptions included (`choice` when more than one).
- `dry_run` (bool): runs only `steam_installer.cli --appid <id> --dry-run`
  and relays its report as `log` lines. No manifest is queued, Steam is not
  closed, there is no `steam://` fallback, so it is allowed while a game runs.
  An installer failure fails the job (`op_failed`).
- `valve_proton` (bool): passes `--valve-proton` to the installer.

The result `data` is `InstallResultData` `{app_id, dry_run,
fast_install_skipped}` once a game was chosen (else the assignment). The
installer closes Steam, so a real install while a game runs skips the fast
path (`_fast_install._refusal`) and Steam's own download starts:
`fast_install_skipped` is then `"game_running"`, and the UI paints the
`result.game-running` mark on the result (`result.dry-run` for a dry run).

## `repair-ghosts`

`./run.sh repair-ghosts` and the `repair-ghosts` job (Library page, icon
`cmd.repair-ghosts`) run the installer's `--repair-ghosts`
(`main/repair_ghosts.py`): every cold ghost manifest is renamed to
`*.ghost-<unix>` and its empty folder removed; a ghost with staged bytes is
only reported (`DOCS-steam-installer.md`, "Ghost installs"). No params, result
`data` = the assignment, an installer failure is `op_failed`.

The installer does not close Steam here, but it rewrites the library under a
client that may be reading it, so it gets `install`'s guard
(`_steam_restart_guard.game_is_running`).

| Command | Phrase (exact) | Checked |
|---|---|---|
| `repair-ghosts` | `delete ghost manifests` | at `POST /api/jobs` (`_web_jobs._PRECHECKED`), then again in the job |

At `POST /api/jobs` the phrase is checked first (`400 wrong_phrase`), then the
guard (`409 game_running`). Either refusal creates no job. The job re-checks
both, because a game can start in between. The UI paints the
`result.game-running` mark on a `game_running` refusal.
