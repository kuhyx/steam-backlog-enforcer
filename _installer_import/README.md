# steam-game-installer

Download an owned Steam game with `depotdownloader` (which saturates a link far
better than the Steam client), then make the Steam client accept the result as
a real install so **Play** works.

```bash
./install.sh                  # checks depotdownloader + steamcmd are present
pip install -e .
steam-game-installer --appid 1771300 --username <steam-user>
```

**Close the Steam client first.** Steam owns `appmanifest_<appid>.acf` while it
runs and rewrites it from its own in-memory state, so anything written
underneath a live client is discarded. The tool refuses to start if it sees one.

## Run logs

Every run writes a full log:

```
~/.local/state/steam-game-installer/run-<timestamp>-<appid>.log
~/.local/state/steam-game-installer/latest.log   -> most recent
```

The path is printed at the start and end of every run, and on every error path.
It contains the full argv, exit code and complete output of each subprocess, the
manifest verbatim before and after every write, the depot cache listing,
expected-vs-actual depots, and whether Steam was running. Send `latest.log` when
something goes wrong. `--verbose` mirrors all of it to the console.

Subprocess output is teed through a pty rather than captured, because steamcmd
only prompts for a password / Steam Guard code when it believes it is on a
terminal — with a plain pipe the prompt never appears and the run looks hung.

## How it works

1. `depotdownloader` pulls the content (fast path).
2. `steamcmd app_update <id> validate` reconciles Steam's own bookkeeping.
3. If that fails or leaves the manifest incomplete, the manifest is finished by
   hand — but only when every precondition below holds.

## Fail-closed preconditions

The tool refuses to mark an app installed, and exits non-zero, unless:

- `depotdownloader` exited 0;
- every required depot has a cached manifest under `.DepotDownloader/`
  (required = this app's depots for the chosen language and OS, excluding DLC,
  optional and shared depots — KCD2 lists 12 depots but an english/windows
  install only ever fetches 3);
- the manifest carries a real `buildid` matching the current public build;
- no Steam client is running;
- the manifest reads back as a real install *after* being written.

This matters: an earlier version wrote `StateFlags=4` and reported success after
a steamcmd run that had done nothing at all.

## Failure modes this encodes

Each of these cost a real debugging session; the tests pin them.

**`force_install_dir` is a library root, not an install directory.** Pointing it
at the game folder made steamcmd look for manifests in `<game>/steamapps/`, find
none (`Loaded 0 apps from install folder`), create that stray directory, and then
fail the app with `Invalid platform` — it had no depot context for the app.
Dropped entirely: the app already lives in a registered library.

**A Linux steamcmd needs `+@sSteamCmdForcePlatformType windows`** (before
`+login`) for a Windows-only game, or it resolves depots against the host OS.

**Steam rejects an internally inconsistent manifest.** A file that says
`StateFlags=4` while `BytesDownloaded` (22 GB) still differs from
`BytesToDownload` (92 GB) is self-contradictory; Steam discards the "installed"
claim and resumes downloading. Across every genuinely installed manifest the
counters are equal in pairs and `StagingSize` is `0`. `DownloadType` is *kept* —
it is present on every real install, so removing it is not the fix.

**Staging must be cleared too.** Steam stages chunks in
`steamapps/downloading/<appid>/`. Declaring the app installed while tens of GB
sit there pending makes Steam resume the update. Installed apps have an empty
(4 KB) staging dir.

**Shared depots are not installed depots.** `228989` belongs to app 228980
(Steamworks Common Redistributables); listing it in `InstalledDepots`
contradicts `SharedDepots`.

**`SizeOnDisk` excludes `.DepotDownloader/`** — its cache and staging tree are
not game content and overstate the total by gigabytes.

## Development

```bash
./install.sh                                   # also prepares the test env
.venv/bin/python -m pytest tests/ -q
ruff check steam_installer/ tests/
ruff format --check steam_installer/ tests/
```

Coverage is enforced at **100% of statements and branches**
(`fail_under = 100`), so an uncovered line fails the suite rather than quietly
lowering a number. One test runs `python -m steam_installer.cli` in a
subprocess to prove the `__main__` entry point works; recording coverage from
a child process needs a `.pth` that calls `coverage.process_startup()`, which
`install.sh` writes into the venv. Skip `install.sh` and coverage reports 99%.
