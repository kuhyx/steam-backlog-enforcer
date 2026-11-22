"""Fetch, verify and install the native Proton, never running its .INSTALL."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_installer import proton_native, proton_pkg
from steam_installer.tests._proton_fixture import (
    FILES,
    VERSION,
    Repo,
    build_db,
    build_package,
    gpg,
    stop_agent,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from steam_installer.tests._proton_fixture import Setup


def test_a_fresh_install_extracts_only_the_tool_and_stamps_it(setup: Setup) -> None:
    """A fresh install extracts only the tool and stamps it."""
    tools, _, run = setup
    status = run()
    tool = tools / "proton-cachyos-native"
    assert status.startswith("installed")
    assert "signature" in status
    assert "sha256" in status
    assert (tool / "VERSION").read_text() == VERSION + "\n"
    assert (tool / "files/bin/wine").read_bytes() == FILES["files/bin/wine"]
    assert str((tool / "files/bin/msidb").readlink()) == "wine"
    assert not (tools / ".INSTALL").exists()
    paths = [str(p.relative_to(tools)) for p in tools.rglob("*")]
    assert not any(".INSTALL" in p or "stray" in p for p in paths)
    assert sorted(p.name for p in tools.iterdir()) == ["proton-cachyos-native"]


def test_a_current_stamp_needs_no_network(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A current stamp needs no network."""
    _, _, run = setup
    run()
    monkeypatch.setattr(
        proton_native, "_download", lambda url, dest: pytest.fail("no network expected")
    )
    assert run() == f"current: {VERSION}"


def _assert_fails_untouched(run: Callable[[], str], tools: Path, match: str) -> None:
    old = tools / "proton-cachyos-native"
    old.mkdir(exist_ok=True)
    (old / "keep").write_text("old build")
    with pytest.raises(proton_pkg.PkgError, match=match):
        run()
    assert (old / "keep").read_text() == "old build"
    assert sorted(p.name for p in tools.iterdir()) == ["proton-cachyos-native"]


def test_a_tampered_signature_fails_closed(setup: Setup, mirror: Path) -> None:
    """A tampered signature fails closed."""
    tools, _, run = setup
    sig = next(mirror.glob("*.sig"))
    data = bytearray(sig.read_bytes())
    data[-5] ^= 0xFF
    sig.write_bytes(bytes(data))
    _assert_fails_untouched(run, tools, "signature")


def test_a_signature_from_another_key_fails_closed(
    setup: Setup,
    mirror: Path,
    tmp_path: Path,
) -> None:
    """A signature from another key fails closed."""
    tools, _, run = setup
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    gpg(
        other,
        "--quick-gen-key",
        "Mallory <m@example.invalid>",
        "ed25519",
        "sign",
        "never",
    )
    package = next(mirror.glob("*.pkg.tar.zst"))
    (mirror / f"{package.name}.sig").unlink()
    gpg(other, "--output", f"{package}.sig", "--detach-sign", str(package))
    stop_agent(other)
    _assert_fails_untouched(run, tools, "signature")


def test_a_package_that_differs_from_the_pinned_sha256_fails_closed(
    setup: Setup, mirror: Path, repo: Repo
) -> None:
    """A package that differs from the pinned sha256 fails closed."""
    tools, _, run = setup
    package = next(mirror.glob("*.pkg.tar.zst"))
    build_package(package, {**FILES, "proton": b"evil"})
    gpg(
        repo.gpg_home,
        "--yes",
        "--output",
        f"{package}.sig",
        "--detach-sign",
        str(package),
    )
    _assert_fails_untouched(run, tools, "sha256")


def test_a_db_sha256_that_disagrees_with_the_lock_fails_closed(
    setup: Setup, mirror: Path
) -> None:
    """A db sha256 that disagrees with the lock fails closed."""
    tools, _, run = setup
    build_db(mirror / "cachyos.db", VERSION, "0" * 64)
    _assert_fails_untouched(run, tools, "sha256")


def test_a_newer_package_in_the_repo_asks_for_a_lock_bump(
    setup: Setup, mirror: Path, repo: Repo
) -> None:
    """A newer package in the repo asks for a lock bump."""
    tools, _, run = setup
    build_db(mirror / "cachyos.db", "1:11.0.20261101-1", repo.sha256)
    _assert_fails_untouched(run, tools, "bump")


def test_a_repo_without_the_package_fails(
    setup: Setup, mirror: Path, repo: Repo
) -> None:
    """A repo without the package fails."""
    tools, _, run = setup
    build_db(mirror / "cachyos.db", VERSION, repo.sha256, name="something-else")
    _assert_fails_untouched(run, tools, "no proton-cachyos-native")
