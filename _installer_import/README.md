# steam-game-installer

Download an owned Steam game with `depotdownloader` (which saturates a link far
better than the Steam client), then make the Steam client accept the result as
a real install so **Play** works.

```bash
./run.sh BeamNG.drive
```

That is the whole thing. `run.sh` installs its own dependencies (`libibus` via
pacman, DepotDownloader from the SteamRE release, a local `.venv` and the native
Proton described below) on first use, then works out what you meant. It never
runs `steamcmd`: app info comes from Steam's own cache and the tool writes the
manifest itself. All four of these install the same game:

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
(no prompts), `--repair-ghosts` (see below), `--valve-proton` (keep this game on
Valve's Proton for this run), `--map-installed` (see below), `--username`
(remembered after the first run, in `~/.config/steam-game-installer/config`;
never a password).

## Games run on a FOSS Proton

A plain Windows game is mapped to `proton-cachyos-native`, a Proton that
CachyOS builds from source against the host's own libraries. Steam then runs
it with no Steam Linux Runtime container, and Proton Experimental, Steam Linux
Runtime 4.0 and the Steamworks Redistributables are not needed while only such
games are installed (steam-backlog-enforcer removes them then).

- **The tool.** `install.sh` downloads the exact build pinned in
  `steam_installer/data/proton-native.lock` from the CachyOS mirror. It checks
  the package's `.sig` against the CachyOS key pinned in
  `steam_installer/data/cachyos_signing_key.asc` (fingerprint and sources in
  `proton_pkg.py`), and its sha256 against the lock. Then it extracts only the
  tool folder into `compatibilitytools.d/` and writes a `VERSION` stamp; the
  package's `.INSTALL` is never run. A copy already on disk is adopted when
  every file matches the package's `.MTREE`. An update is swapped in by rename,
  only while Steam and every game are closed. The dependency-freshness gate
  checks the lock against `cachyos.db`.
- **Which games.** Only a game proven safe: Windows-only (the app, every depot,
  every launch option), no shared depots, no owned DLC depot, not in
  AreWeAntiCheatYet's `games.json` (fetched every run, last good copy cached;
  no list means nothing is mapped), and not in
  `steam_installer/data/compat_overrides.json` (`{"<appid>": "<reason>"}` for a
  game that breaks on the native build). Anything else keeps Valve's default,
  so it runs exactly as before. The run prints every reason.
- **The mapping.** With Steam closed, the game gets a `CompatToolMapping`
  entry in `config/config.vdf` (`"name" "proton-cachyos-native"`, priority
  250). The file is edited as text, and none of its other lines is ever logged.
  An entry Valve chose (priority 100) is replaced; one you picked is kept.
- **Games already installed.** `./run.sh --map-installed` prints the decision
  for every installed game and writes nothing; add `--apply` to close Steam and
  write the safe ones. `--appids 730,1201270` decides any cached app instead.

Proven live on 2026-11-22 with A Space for the Unbound (1201270). Not tested
yet, so they stay on Valve's default or are fixture-tested only: a game with
shared depots (its from-scratch manifest records `SharedDepots`), an owned DLC
depot, a native Linux game, an anti-cheat game, a global default mapping and a
package update.

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

## Owned DLC comes down fast too

Some DLC keeps its content under an app id of its own rather than in the
game's depot list -- Cyberpunk 2077's Phantom Liberty is app 2138330, about
25 GB. A depotdownloader run for the game never sees it, and Steam, restarted
onto a manifest without it, downloads all of it at its own pace.

So every DLC in the game's `listofdlc` that has depots of its own gets its own
depotdownloader run into the same install dir. Depotdownloader's licence check
decides ownership: its "not available from this account" is skipped as
expected, any other failure aborts before the manifest is touched. Each DLC
depot is then written into `InstalledDepots` with its `dlcappid`, exactly as
Steam records it.

## Which depotdownloader

Always `~/.local/bin/depotdownloader` (the copy `install.sh` manages) when it
exists, never "whatever is first on PATH". Each depotdownloader binary keeps
its remembered login in its own storage slot, keyed by its path; with an AUR
copy in `/usr/bin` too, a terminal run and a `sudo`'d run (whose PATH lacks
`~/.local/bin`) used different binaries -- one logged in, one prompting for a
password nobody was there to type.

## Ghost installs

Older versions of this tool ran steamcmd. `steamcmd +login anonymous +app_update
<paid appid>` has no licence for the app.
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

Subprocess output is teed through a pty rather than captured, because
depotdownloader only prompts for a password / Steam Guard code when it believes
it is on a terminal — with a plain pipe the prompt never appears and the run looks hung.

## How it works

1. App info (name, installdir, depots, build) is read from Steam's own cache,
   `appcache/appinfo.vdf`. An app missing from it fails with the fix: start
   Steam once, let it sync, rerun. A DLC missing from it counts as not owned.
2. `depotdownloader` pulls the content (fast path).
   Then each owned DLC with depots of its own gets a run of its own.
3. The manifest is finished by hand, or written from scratch with the 15 keys
   Steam accepted when none exists, but only when every precondition below
   holds. Steam adds `LastOwner`, `UserConfig` and the rest itself.
4. The game is mapped to the native Proton when it is safe (see above).

## Fail-closed preconditions

The tool refuses to mark an app installed, and exits non-zero, unless:

- `depotdownloader` exited 0;
- every required depot has a cached manifest under `.DepotDownloader/`
  (required = this app's depots for the chosen language and OS, excluding DLC,
  optional and shared depots — KCD2 lists 12 depots but an english/windows
  install only ever fetches 3);
- every required depot holds the public gid from Steam's cache, which proves
  the build (a differing gid means the cache is stale: start Steam, let it
  sync, rerun), or else the manifest carries a matching real `buildid`;
- no Steam client is running (it is closed first, and restarted afterwards);
- the manifest reads back as a real install *after* being written.

This matters: an earlier version wrote `StateFlags=4` and reported success after
a steamcmd run that had done nothing at all. A from-scratch manifest is built in
memory and only written once every check has passed.

## Failure modes this encodes

Each of these cost a real debugging session; the tests pin them.

**A wrong `installdir` makes Steam wipe the game.** Steam treated the correctly
downloaded folder as orphaned, deleted it and started a fresh download into the
folder its manifest named. The field is fixed first, as soon as Steam is closed.

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
