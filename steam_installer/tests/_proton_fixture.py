"""A tiny fake CachyOS repo: a signed proton package, its db and the signing key.

Built for real (zstd tars, a gzip .MTREE, a gpg detached signature from a
throwaway ed25519 key) so the fetcher's checks run against the same formats
the real mirror serves.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import hashlib
import io
import shutil
import subprocess
import tarfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from steam_installer.proton_pkg import Lock

    type Setup = tuple[Path, Lock, Callable[..., str]]

PREFIX = "usr/share/steam/compatibilitytools.d/proton-cachyos-native/"
VERSION = "1:11.0.20261015-1"
FILENAME = f"proton-cachyos-native-{VERSION}-x86_64.pkg.tar.zst"
FILES = {
    "toolmanifest.vdf": b'"manifest"\n{\n  "commandline" "/proton %verb%"\n}\n',
    "proton": b"#!/usr/bin/env python3\n",
    "files/bin/wine": b"\x7fELF wine",
    "user settings.py": b"# a name with a space\n",
}
LINKS = {"files/bin/msidb": "wine"}


GPG = shutil.which("gpg") or "gpg"
GPGCONF = shutil.which("gpgconf") or "gpgconf"


@dataclass
class Repo:
    """Repo."""

    root: Path  # served as the mirror: holds cachyos.db, the package, the .sig
    key: Path
    fingerprint: str
    sha256: str
    gpg_home: Path

    @property
    def db_url(self) -> str:
        """Db url."""
        return (self.root / "cachyos.db").as_uri()

    @property
    def package(self) -> Path:
        """Package."""
        return self.root / FILENAME


def _mtree() -> bytes:
    lines = ["#mtree", "/set type=file uid=0 gid=0 mode=644"]
    lines.append("./.INSTALL time=1.0 size=3 sha256digest=00")
    lines.append(f"./{PREFIX.rstrip('/')} time=1.0 mode=755 type=dir")
    for name, data in FILES.items():
        digest = hashlib.sha256(data).hexdigest()
        path = (PREFIX + name).replace(" ", "\\040")
        lines.append(f"./{path} time=1.0 size={len(data)} sha256digest={digest}")
    for name, target in LINKS.items():
        lines.append(f"./{PREFIX}{name} time=1.0 mode=777 type=link link={target}")
    return gzip.compress(("\n".join(lines) + "\n").encode())


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def build_package(path: Path, files: dict[str, bytes] | None = None) -> None:
    """Build package."""
    files = FILES if files is None else files
    with tarfile.open(path, "w:zst") as tar:
        _add(tar, ".INSTALL", b"rm -rf /\n")  # never run, never extracted
        _add(tar, ".MTREE", _mtree())
        _add(tar, "usr/bin/stray", b"outside the tool folder")
        for name, data in files.items():
            _add(tar, PREFIX + name, data)
        for name, target in LINKS.items():
            info = tarfile.TarInfo(PREFIX + name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)


def build_db(
    path: Path, version: str, sha256: str, name: str = "proton-cachyos-native"
) -> None:
    """Build db."""
    desc = (
        f"%FILENAME%\n{name}-{version}-x86_64.pkg.tar.zst\n\n%NAME%\n{name}\n\n"
        f"%VERSION%\n{version}\n\n%SHA256SUM%\n{sha256}\n\n"
    ).encode()
    other = b"%NAME%\nproton-cachyos-native-v3\n\n%VERSION%\n9:9-9\n\n"
    with tarfile.open(path, "w:zst") as tar:
        _add(tar, "proton-cachyos-native-v3-9:9-9/desc", other)
        _add(tar, f"{name}-{version}/desc", desc)


def gpg(home: Path, *args: str) -> None:
    """Gpg."""
    subprocess.run(
        [GPG, "--homedir", str(home), "--batch", "--passphrase", "", *args],
        check=True,
        capture_output=True,
    )


def build_repo(tmp: Path) -> Repo:
    """Build repo."""
    root = tmp / "mirror"
    root.mkdir()
    home = tmp / "signer"
    home.mkdir(mode=0o700)
    gpg(
        home,
        "--quick-gen-key",
        "Fake CachyOS <fake@example.invalid>",
        "ed25519",
        "sign",
        "never",
    )
    listing = subprocess.run(
        [GPG, "--homedir", str(home), "--with-colons", "--fingerprint"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    fingerprint = next(
        line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr")
    )
    key = tmp / "key.asc"
    gpg(home, "--armor", "--output", str(key), "--export", fingerprint)
    package = root / FILENAME
    build_package(package)
    gpg(home, "--output", f"{package}.sig", "--detach-sign", str(package))
    sha256 = hashlib.sha256(package.read_bytes()).hexdigest()
    build_db(root / "cachyos.db", VERSION, sha256)
    return Repo(root, key, fingerprint, sha256, home)


def stop_agent(home: Path) -> None:
    """Stop agent."""
    subprocess.run([GPGCONF, "--homedir", str(home), "--kill", "all"], check=False)
