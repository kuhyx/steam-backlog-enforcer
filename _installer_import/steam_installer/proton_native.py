"""Install the pinned proton-cachyos-native build into Steam's compatibilitytools.d.

    python -m steam_installer.proton_native          # what install.sh runs
    python -m steam_installer.proton_native --check  # exit 0 when in place

The package comes straight from the CachyOS mirror: the `proton-cachyos-native`
entry of `cachyos.db`, its signature and sha256 checked (see :mod:`proton_pkg`),
and only `usr/share/steam/compatibilitytools.d/proton-cachyos-native/` taken
out of it. Its `.INSTALL` is never run. It is a WoW64 build that needs no
lib32 packages, and unlike the `-slr` variant its toolmanifest requires no
Steam Linux Runtime -- which is the point.

A `VERSION` stamp equal to the lock means there is nothing to do and no
network is touched. Otherwise the new build is extracted next to the old one
and swapped in by rename -- never while Steam or a game from the tool runs,
since a game would lose its files mid-run. A copy already on disk with no
stamp is adopted as is when every file matches the package's `.MTREE`.

`SGI_PROTON_REPO` points the fetch at another copy of the repo db (a local
test mirror); the pinned key and sha256 still decide what is accepted.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from steam_installer import proton_pkg, recognize
from steam_installer.library import find_steam_root
from steam_installer.proton_pkg import FINGERPRINT, KEY, Lock, PkgError

TOOL_NAME = "proton-cachyos-native"


def in_use(tool: Path) -> list[int]:
    """Steam client pids plus every process running from the tool folder."""
    pids = list(recognize.steam_client_pids())
    root = tool.resolve()
    for entry in recognize.PROC_DIR.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            exe = (entry / "exe").resolve(strict=True)
        except OSError:
            continue
        if exe.is_relative_to(root):
            pids.append(int(entry.name))
    return pids


def _download(url: str, dest: Path) -> None:
    # A generic agent: the mirror answers 403 to urllib's default one.
    request = urllib.request.Request(url, headers={"User-Agent": "steam-game-installer"})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out, 1 << 20)


def _fetch_verified(lock: Lock, work: Path, key: Path, fingerprint: str) -> Path:
    """Download the pinned package and prove it, or raise PkgError."""
    db = work / "repo.db"
    _download(lock.repo, db)
    entry = proton_pkg.find_in_db(db, lock.name)
    if entry.version != lock.version:
        raise PkgError(
            f"the repo serves {lock.name} {entry.version} but the lock pins "
            f"{lock.version}: bump steam_installer/data/proton-native.lock "
            "(version and sha256)"
        )
    if entry.sha256 != lock.sha256:
        raise PkgError("the repo's sha256 for the pinned version differs from the lock")
    package = work / entry.filename
    url = proton_pkg.package_url(lock, entry.filename)
    _download(url, package)
    sig = work / f"{entry.filename}.sig"
    _download(f"{url}.sig", sig)
    home = work / "gnupg"
    home.mkdir(mode=0o700)
    try:
        proton_pkg.verify_signature(package, sig, key, fingerprint, home)
    finally:
        subprocess.run(
            ["gpgconf", "--homedir", str(home), "--kill", "all"],
            check=False, capture_output=True,
        )
    if proton_pkg.sha256_file(package) != lock.sha256:
        raise PkgError("the downloaded package's sha256 differs from the pinned sha256")
    return package


def _stamp(tool: Path, version: str) -> None:
    (tool / "VERSION").write_text(version + "\n")


def _swap(package: Path, tools_dir: Path, tool: Path, version: str) -> None:
    new = tools_dir / f".{TOOL_NAME}.new"
    old = tools_dir / f".{TOOL_NAME}.old"
    for leftover in (new, old):
        shutil.rmtree(leftover, ignore_errors=True)
    new.mkdir()
    proton_pkg.extract(package, new)
    if tool.exists():
        tool.rename(old)
    new.rename(tool)
    shutil.rmtree(old, ignore_errors=True)
    _stamp(tool, version)


def ensure(
    tools_dir: Path, lock: Lock, *, key: Path = KEY, fingerprint: str = FINGERPRINT
) -> str:
    """Make `tools_dir/proton-cachyos-native` the pinned build; return what happened."""
    tool = tools_dir / TOOL_NAME
    stamp = tool / "VERSION"
    current = stamp.read_text().strip() if stamp.is_file() else None
    if current == lock.version:
        return f"current: {lock.version}"
    tools_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(dir=tools_dir, prefix=".proton-download."))
    try:
        package = _fetch_verified(lock, work, key, fingerprint)
        checks = f"signature by {fingerprint} and sha256 both passed"
        if not tool.exists():
            verb = f"installed: {lock.version}"
        elif current is not None:
            verb = f"updated: {current} -> {lock.version}"
        else:
            entries = proton_pkg.read_mtree(package)
            mismatch = proton_pkg.first_mismatch(tool, entries)
            if mismatch is None:
                _stamp(tool, lock.version)
                count = sum(entry.kind != "dir" for entry in entries.values())
                return f"adopted: all {count} files match .MTREE ({checks})"
            verb = f"replaced: mismatch in {mismatch}"
        busy = in_use(tool) if tool.exists() else []
        if busy:
            return (
                f"deferred: Steam or a game is running (pid {', '.join(map(str, busy))}); "
                "rerun with Steam closed"
            )
        _swap(package, tools_dir, tool, lock.version)
        return f"{verb} ({checks})"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    """Install the pinned build; with `--check`, only say whether it is in place."""
    lock = proton_pkg.read_lock()
    if os.environ.get("SGI_PROTON_REPO"):
        lock = dataclasses.replace(lock, repo=os.environ["SGI_PROTON_REPO"])
    try:
        tools_dir = find_steam_root() / "compatibilitytools.d"
    except FileNotFoundError:
        print("native Proton skipped: no Steam installation")
        return 0
    if argv and argv[0] == "--check":
        stamp = tools_dir / TOOL_NAME / "VERSION"
        return 0 if stamp.is_file() and stamp.read_text().strip() == lock.version else 1
    try:
        status = ensure(tools_dir, lock)
    except (PkgError, OSError) as exc:
        print(f"error: native Proton: {exc}", file=sys.stderr)
        return 1
    print(f"native Proton {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
