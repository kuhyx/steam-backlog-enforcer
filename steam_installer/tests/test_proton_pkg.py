"""The package formats and checks behind the native Proton fetcher."""

from __future__ import annotations

import hashlib
import tarfile
from typing import TYPE_CHECKING

import pytest

from steam_installer import proton_pkg
from steam_installer.tests._proton_fixture import PREFIX, Repo, build_repo, stop_agent

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(name="repo", scope="module")
def _repo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Repo]:
    """The repo fixture."""
    built = build_repo(tmp_path_factory.mktemp("repo"))
    yield built
    stop_agent(built.gpg_home)


def test_the_real_lock_pins_the_proven_build() -> None:
    """The real lock pins the proven build."""
    lock = proton_pkg.read_lock()
    assert lock.name == "proton-cachyos-native"
    assert lock.version == "1:11.0.20261015-1"
    assert (
        lock.sha256
        == "25bf302f90e8e01118555b997b873c3cd06a33b5647e79d049a59e29794b43e0"
    )
    assert lock.repo == "https://mirror.cachyos.org/repo/x86_64/cachyos/cachyos.db"


def test_a_lock_missing_a_key_is_refused(tmp_path: Path) -> None:
    """A lock missing a key is refused."""
    path = tmp_path / "x.lock"
    path.write_text("# c\nname=a\nrepo=b.db\n")
    with pytest.raises(proton_pkg.PkgError, match="version"):
        proton_pkg.read_lock(path)


def test_the_pinned_key_file_holds_the_pinned_fingerprint(tmp_path: Path) -> None:
    """The pinned key file holds the pinned fingerprint."""
    home = tmp_path / "g"
    home.mkdir(mode=0o700)
    try:
        assert proton_pkg.key_fingerprints(proton_pkg.KEY, home) == [
            proton_pkg.FINGERPRINT
        ]
    finally:
        stop_agent(home)


def test_package_urls_quote_the_epoch_colon() -> None:
    """Package urls quote the epoch colon."""
    lock = proton_pkg.Lock("p", "https://m/repo/cachyos.db", "1:2-3", "x")
    assert proton_pkg.package_url(lock, "p-1:2-3-x86_64.pkg.tar.zst") == (
        "https://m/repo/p-1%3A2-3-x86_64.pkg.tar.zst"
    )


def test_sha256_file_streams(tmp_path: Path) -> None:
    """Sha256 file streams."""
    path = tmp_path / "f"
    path.write_bytes(b"abc" * 100000)
    assert proton_pkg.sha256_file(path) == hashlib.sha256(b"abc" * 100000).hexdigest()


def test_mtree_unescapes_octal_names(repo: Repo) -> None:
    """Mtree unescapes octal names."""
    entries = proton_pkg.read_mtree(repo.package)
    assert entries["user settings.py"].kind == "file"
    assert entries["files/bin/msidb"].link == "wine"
    assert ".INSTALL" not in entries
    assert "" not in entries
    assert PREFIX not in entries


def test_db_entries_other_than_desc_are_ignored(tmp_path: Path) -> None:
    """Db entries other than desc are ignored."""
    db = tmp_path / "x.db"
    with tarfile.open(db, "w:zst") as tar:
        info = tarfile.TarInfo("p-1/files")
        tar.addfile(info)
    with pytest.raises(proton_pkg.PkgError, match="lists no p"):
        proton_pkg.find_in_db(db, "p")


def test_a_key_file_without_the_pinned_fingerprint_is_refused(
    repo: Repo, tmp_path: Path
) -> None:
    """A key file without the pinned fingerprint is refused."""
    home = tmp_path / "g"
    home.mkdir(mode=0o700)
    try:
        with pytest.raises(proton_pkg.PkgError, match="pinned key file"):
            proton_pkg.verify_signature(
                repo.package, repo.package, repo.key, "0" * 40, home
            )
    finally:
        stop_agent(home)


def test_a_package_without_mtree_is_refused(tmp_path: Path) -> None:
    """A package without mtree is refused."""
    package = tmp_path / "p.pkg.tar.zst"
    with tarfile.open(package, "w:zst") as tar:
        tar.addfile(tarfile.TarInfo("usr/x"))
    with pytest.raises(proton_pkg.PkgError, match=r"no \.MTREE"):
        proton_pkg.read_mtree(package)


def test_directories_listed_in_mtree_need_no_content_check(tmp_path: Path) -> None:
    """Directories listed in mtree need no content check."""
    entries = {"files": proton_pkg.MtreeEntry("dir")}
    (tmp_path / "files").mkdir()
    assert proton_pkg.first_mismatch(tmp_path, entries) is None
