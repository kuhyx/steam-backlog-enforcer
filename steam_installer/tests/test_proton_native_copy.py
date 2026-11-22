"""An existing tool folder: adopted, replaced, deferred or updated."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_installer import proton_native, proton_pkg
from steam_installer.tests._proton_fixture import (
    FILES,
    VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from steam_installer.tests._proton_fixture import Setup


def _existing_copy(tools: Path) -> Path:
    tool = tools / "proton-cachyos-native"
    for name, data in FILES.items():
        (tool / name).parent.mkdir(parents=True, exist_ok=True)
        (tool / name).write_bytes(data)
    (tool / "files/bin/msidb").symlink_to("wine")
    (tool / "__pycache__").mkdir()
    (tool / "__pycache__" / "x.pyc").write_bytes(b"made by running it")
    return tool


def test_an_identical_copy_is_adopted_without_extracting(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An identical copy is adopted without extracting."""
    tools, _, run = setup
    tool = _existing_copy(tools)
    monkeypatch.setattr(proton_pkg, "extract", lambda *a: pytest.fail("extracted"))
    status = run()
    assert status.startswith(
        f"adopted: all {len(FILES) + 1} files match .MTREE (signature"
    )
    assert (tool / "VERSION").read_text() == VERSION + "\n"


@pytest.mark.parametrize(
    ("change", "where"),
    [
        (lambda t: (t / "files/bin/wine").write_bytes(b"patched"), "files/bin/wine"),
        (lambda t: (t / "user_settings.py").write_text("x"), "user_settings.py"),
        (lambda t: (t / "proton").unlink(), "proton"),
        (
            lambda t: (
                (t / "files/bin/msidb").unlink()
                or (t / "files/bin/msidb").symlink_to("x")
            ),
            "msidb",
        ),
        (lambda t: (t / "files/bin/msidb").unlink(), "msidb"),
    ],
)
def test_a_differing_copy_is_replaced(
    setup: Setup,
    change: Callable[[Path], object],
    where: str,
) -> None:
    """A differing copy is replaced."""
    tools, _, run = setup
    tool = _existing_copy(tools)
    change(tool)
    status = run()
    assert status.startswith("replaced: mismatch in")
    assert where in status
    assert (tool / "files/bin/wine").read_bytes() == FILES["files/bin/wine"]
    assert not (tool / "user_settings.py").exists()
    assert sorted(p.name for p in tools.iterdir()) == ["proton-cachyos-native"]


def test_replacing_is_deferred_while_steam_or_a_game_runs(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing is deferred while steam or a game runs."""
    tools, _, run = setup
    tool = _existing_copy(tools)
    (tool / "proton").write_text("old")
    monkeypatch.setattr(proton_native, "in_use", lambda t: [4242])
    status = run()
    assert status.startswith("deferred")
    assert (tool / "proton").read_text() == "old"
    assert not (tool / "VERSION").exists()


def test_an_older_stamp_is_updated(setup: Setup) -> None:
    """An older stamp is updated."""
    tools, _, run = setup
    tool = _existing_copy(tools)
    (tool / "VERSION").write_text("1:10.0-1\n")
    assert run().startswith("updated: 1:10.0-1 ->")
    assert (tool / "VERSION").read_text() == VERSION + "\n"
