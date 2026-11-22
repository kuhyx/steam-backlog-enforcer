"""Which processes keep the native Proton in use."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_installer import proton_native

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_in_use_sees_steam_and_processes_running_from_the_tool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In use sees steam and processes running from the tool."""
    proc = tmp_path / "proc"
    tool = tmp_path / "tool"
    (tool / "files/bin").mkdir(parents=True)
    (tool / "files/bin/wine").write_text("")
    (tmp_path / "other").write_text("")
    for pid, target in (
        ("10", tool / "files/bin/wine"),
        ("11", tmp_path / "other"),
        ("13", tmp_path / "gone"),
    ):
        (proc / pid).mkdir(parents=True)
        (proc / pid / "exe").symlink_to(target)
    (proc / "self").mkdir()
    (proc / "12").mkdir()
    monkeypatch.setattr(proton_native.recognize, "PROC_DIR", proc)
    monkeypatch.setattr(proton_native.recognize, "steam_client_pids", lambda: [99])
    assert proton_native.in_use(tool) == [99, 10]
