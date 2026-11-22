# `install`, `repair-ghosts` and `map-installed` jobs

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

## Proton map: `GET /api/compat` and `map-installed`

`GET /api/compat` (`_compat_view.compat_view`) returns
`{tool, tool_ready, rows}`: one row per installed game, built by
`steam_installer.compat_rows.rows` (the same rows `--map-installed` logs, so
the view cannot disagree with the apply). A row is
`{app_id, name, current, priority, decided, reasons, note, map, changes,
cached}` (`CompatRow` in `web/src/api/contract.ts`); `null` in `current` or
`decided` means Valve's default. Steam's own tools are not rows. An unreadable
Steam, app cache or overrides file is `502 op_failed`.

Deciding parses the ~10 MB app cache, so the payload is kept in memory and
rebuilt only when a file it was decided from changes (`cache_key`: app cache,
`config.vdf`, `libraryfolders.vdf`, every `appmanifest_*.acf`, the overrides,
the tool's `VERSION`, the anti-cheat cache and its 6 h age window). A GET
never waits on the network unless that anti-cheat cache is older.

`./run.sh map-installed` and the `map-installed` job (Library page, view
`#view=compat`, icon `cmd.map-installed`) run the installer's
`--map-installed --apply --yes --appids <ids>` (`main/map_installed.py`). The
apply closes Steam (Steam rewrites `config.vdf` on exit), maps each game the
decision proves safe to the native Proton and starts Steam again, so it refuses
while a game runs (`409 game_running`). The job streams the installer's
output as `log` lines and has a 180 s timer.

Param `appids` (string, optional): comma-separated installed app ids. Absent,
the job maps every game whose row has `changes: true`. Ids that are not
installed, not digits, or an empty list are `400 invalid_params`
(`_compat_view.checked_appids`). The installer gets exactly the ids the phrase
counted, never "everything". The result `data` is `{app_ids: [...]}`.

| Command | Phrase (exact) | Checked |
|---|---|---|
| `map-installed` | `map {appid_count} games`, e.g. `map 3 games` | at `POST /api/jobs` (`_web_jobs._PRECHECKED`), then again in the job |

The count is part of the phrase, so a stale count is a wrong phrase. At
`POST /api/jobs` the ids are checked first (`400 invalid_params`, `502
op_failed` when Steam is unreadable), then the phrase (`400 wrong_phrase`),
then the guard (`409 game_running`). Each refusal creates no job. The UI fills
`{appid_count}` from the same ids (`fillPhrase` in `web/src/commands/catalog.ts`).

The view (`web/src/library/compatTable.ts`, state in `compatState.ts`) has
sortable columns, per-column filters, fuzzy search, a 30 s poll and row
checkboxes for games that change; with none ticked, Map applies to every
visible changing game. Its state lives in the URL hash, keys prefixed `c.`
because the cover grid owns `q` and `sort` in the same hash:

| Key | Meaning |
|---|---|
| `view=compat` | show the Proton map |
| `c.sort=<col>`, `c.dir=asc\|desc` | sort column (`name`, `app_id`, `current`, `decided`, `why`, `changes`) and direction; default `changes` ascending |
| `c.q=<text>` | fuzzy search |
| `c.f.<col>=<text>` | filter: substring for `name` and `why`, exact option for `current`, `decided`, `changes` (`changes` or `same`) |
| `c.f.app_id=<min>..<max>` | app id range, either side optional |
