"""Detect the fake "fully installed" state anonymous steamcmd leaves behind.

`steamcmd +login anonymous +app_update <paid appid>` has no licence for the
app. It does not say so. It transfers nothing, prints

    Update state (0x0) unknown, progress: 0.00 (0 / 0)
    Success! App '284160' fully installed.

exits 0, and writes a manifest claiming StateFlags=4 with SizeOnDisk=0 and an
empty InstalledDepots block. Reproduced on this machine on 2026-09-11.

That manifest is not harmless. A running Steam client reads it, concludes the
app is installed but out of date, and starts downloading the whole game by
itself -- which is exactly what happened, to the tune of 22 GB.

Two outcomes, and only one of them deletes anything:

* **Cold ghost** -- the lie and nothing else. Safe to clear away.
* **Warm ghost** -- the same manifest, but Steam has since staged real content
  into `steamapps/downloading/<appid>/`. Those bytes are worth keeping: the
  whole point of this tool is to make installs faster, and deleting a partial
  download to start over is the opposite. Warm ghosts are routed to
  `takeover`, never to `repair`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from steam_installer import manifest_write, recognize, vdf
from steam_installer.library import SteamLibrary

INSTALLED_STATE_FLAG = 4


@dataclass(frozen=True)
class GhostReport:
    appid: int
    manifest_path: Path
    install_dir: Path | None
    content_bytes: int
    staging_bytes: int
    reasons: tuple[str, ...]

    @property
    def is_ghost(self) -> bool:
        return bool(self.reasons)

    @property
    def is_warm(self) -> bool:
        """Steam has staged real content for this app; it must not be deleted."""
        return self.staging_bytes > 0


def staging_size(library: SteamLibrary, appid: int) -> int:
    staged = library.steamapps / "downloading" / str(appid)
    if not staged.is_dir():
        return 0
    return sum(f.stat().st_size for f in staged.rglob("*") if f.is_file())


def _install_dir(library: SteamLibrary, app_state: dict) -> Path | None:
    installdir = app_state.get("installdir")
    if not isinstance(installdir, str) or not installdir:
        return None
    return library.common / installdir


def inspect(library: SteamLibrary, appid: int) -> GhostReport:
    """Classify `appid` in `library`. An empty `reasons` means it is not a ghost.

    Every condition is required. They are deliberately a conjunction: a real
    install fails several of them at once, and a single `or` anywhere in this
    chain is the difference between cleaning up a lie and deleting someone's
    game.
    """
    manifest_path = library.steamapps / f"appmanifest_{appid}.acf"
    empty = GhostReport(appid, manifest_path, None, 0, 0, ())

    if not manifest_path.is_file():
        return empty
    try:
        app_state = recognize.read_app_state(manifest_path)
    except vdf.VdfParseError:
        return empty
    if str(app_state.get("appid", "")) != str(appid):
        return empty

    install_dir = _install_dir(library, app_state)
    content_bytes = (
        manifest_write.measure_content_size(install_dir)
        if install_dir is not None and install_dir.is_dir()
        else 0
    )
    staged = staging_size(library, appid)
    known = GhostReport(appid, manifest_path, install_dir, content_bytes, staged, ())

    state_flags = app_state.get("StateFlags", "")
    if not (str(state_flags).isdigit() and int(state_flags) & INSTALLED_STATE_FLAG):
        return known
    depots = app_state.get("InstalledDepots")
    if depots:
        return known
    if str(app_state.get("SizeOnDisk", "0")) != "0":
        return known
    if content_bytes:
        return known
    # Our own downloader's cache means a real run is in progress against this
    # directory; an empty install dir mid-download is not a ghost.
    if install_dir is not None and recognize.discover_cached_depot_manifests(
        install_dir
    ):
        return known

    return GhostReport(
        appid,
        manifest_path,
        install_dir,
        content_bytes,
        staged,
        (
            f"manifest claims StateFlags={state_flags} (installed)",
            "InstalledDepots is empty",
            "SizeOnDisk is 0",
            "no game content on disk",
        ),
    )


def scan(libraries: list[SteamLibrary]) -> list[GhostReport]:
    """Every ghost across every library, checked one manifest at a time."""
    found: list[GhostReport] = []
    for library in libraries:
        if not library.steamapps.is_dir():
            continue
        for manifest in sorted(library.steamapps.glob("appmanifest_*.acf")):
            digits = manifest.stem.removeprefix("appmanifest_")
            if not digits.isdigit():
                continue
            report = inspect(library, int(digits))
            if report.is_ghost:
                found.append(report)
    return found


def repair(
    report: GhostReport, logger: logging.Logger, *, now_unix: int | None = None
) -> list[Path]:
    """Clear a COLD ghost away. Returns the paths it touched.

    Refuses a warm ghost outright: those bytes belong to `takeover`.
    """
    if not report.is_ghost:
        raise ValueError(f"appid {report.appid} is not a ghost; refusing to touch it")
    if report.is_warm:
        raise ValueError(
            f"appid {report.appid} has {report.staging_bytes / 1e9:.1f} GB of staged "
            "Steam content. That is a partial download, not a ghost to delete -- "
            "install it normally so the bytes are reused."
        )

    stamp = int(time.time()) if now_unix is None else now_unix
    touched: list[Path] = []

    # Rename rather than unlink: reversible, atomic, and it leaves the evidence
    # on disk if the diagnosis was somehow wrong.
    backup = report.manifest_path.with_name(
        f"{report.manifest_path.name}.ghost-{stamp}"
    )
    report.manifest_path.rename(backup)
    logger.info("Moved bogus manifest to %s", backup)
    touched.append(backup)

    if report.install_dir is not None and report.install_dir.is_dir():
        try:
            # rmdir, never rmtree: the kernel refuses a non-empty directory, so
            # a real install cannot be destroyed here even if inspect() were wrong.
            report.install_dir.rmdir()
        except OSError as exc:
            logger.warning("Left %s in place: %s", report.install_dir, exc)
        else:
            logger.info("Removed empty %s", report.install_dir)
            touched.append(report.install_dir)

    return touched
