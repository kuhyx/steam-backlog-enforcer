# steam-game-installer

Download an owned Steam game with `depotdownloader` (which saturates a link far
better than the Steam client), then make the Steam client accept the result as
a real install so **Play** works.

```bash
./run.sh BeamNG.drive
```

That is the whole thing. `run.sh` installs its own dependencies (steamcmd via
`yay`, DepotDownloader from the SteamRE release, and a local `.venv`) on first
use, then works out what you meant. All four of these install the same game:

```bash
./run.sh 284160                                           # an AppID
./run.sh https://steamcommunity.com/app/284160/guides/    # any Steam URL
./run.sh BeamNG.drive                                     # the exact name
./run.sh BeamNG                                           # part of the name
```

An exact title always wins, so `./run.sh Portal` installs Portal and not
Portal 2 — even though Steam's own search ranks the sequel first. An ambiguous
name shows a numbered picker, and in a non-interactive run it lists the
candidates and exits 2 rather than guessing.

Useful flags: `--dry-run` (resolve and report, change nothing), `--yes`
(no prompts), `--repair-ghosts` (see below), `--username` (remembered after the
first run, in `~/.config/steam-game-installer/config`; never a password).

**Steam gets closed for you.** Steam owns `appmanifest_<appid>.acf` while it
runs and rewrites it from its own in-memory state, so anything written
underneath a live client is discarded. The tool asks, shuts it down with
`steam -shutdown`, and restarts it afterwards. It never sends a signal: a client
that refuses to exit aborts the run instead.

## It takes over a download Steam already started

Steam stages an in-progress download into `steamapps/downloading/<appid>/`, laid
out exactly like the finished game. Those bytes are yours — you waited for them
— so the tool **hardlinks them into place** before calling depotdownloader,
which hash-checks what is already on disk and fetches only the remainder.

Hardlinks, not moves and not copies. Nothing is deleted up front: the staging
tree is cleared only at the very end, so a failed run still leaves Steam able to
resume its own download. Linking is free, where copying a 47 GB tree would cost
47 GB.

Because the two trees share inodes, depotdownloader patching a partial file in
place also rewrites Steam's copy. That is deliberate — both names converge on
the same corrected content — but it does mean the staged bytes are working data,
not a frozen backup. On ext4 there is no reflink that would give you both.

## Ghost installs

`steamcmd +login anonymous +app_update <paid appid>` has no licence for the app.
It does not say so. It transfers nothing, prints `Success! App '...' fully
installed.`, exits 0, and writes a manifest claiming `StateFlags=4` with
`SizeOnDisk=0` and an empty `InstalledDepots`.

That manifest is not harmless: a running Steam client reads it, concludes the
app is installed but out of date, and downloads the entire game by itself.

```bash
./run.sh --repair-ghosts
```

finds them across every library and clears them away — but only the *cold* ones.
A ghost with staged content behind it is a real partial download; it is reported
and left alone, to be adopted by a normal install instead. Detection requires
all of: the manifest claims installed, `InstalledDepots` is empty, `SizeOnDisk`
is `0`, there are zero content bytes on disk, and there is no `.DepotDownloader`
state. Repair uses `rmdir`, never `rmtree`, so a non-empty directory cannot be
deleted even if the diagnosis were wrong.

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
- no Steam client is running (it is closed first, and restarted afterwards);
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
