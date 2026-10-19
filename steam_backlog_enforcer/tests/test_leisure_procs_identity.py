"""What a process really runs: wsg-grabber as the program, updated binaries."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from steam_backlog_enforcer import _leisure_procs as procs
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from pathlib import Path

_PY = "/usr/bin/python3.14"
_WSG = "/home/kuhy/.local/bin/wsg-grabber"


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    return leisure_proc(tmp_path)


class TestWsgIsTheProgram:
    @pytest.mark.parametrize(
        ("exe", "args"),
        [
            ("/usr/bin/git", ("git", "-C", "/home/kuhy/src/wsg-grabber", "status")),
            (_PY, ("python3", "-m", "pytest", "/home/kuhy/src/wsg-grabber")),
            ("/usr/bin/vim", ("vim", _WSG)),
            (_PY, ("python3", _WSG, "scrape")),
            (_PY, ("python3", "-u", "-m", "wsg_grabber", "scrape")),
            ("/usr/bin/wsg-grabber", ("wsg-grabber", "scrape")),
            (_PY, ("python3", "-c", "import wsg_grabber")),
            (_PY, ("python3", "-m")),
            (_PY, ("python3", "-X", "dev")),
            (_PY, ("python3",)),
        ],
    )
    def test_not_a_reviewer(self, proc: Path, exe: str, args: tuple[str, ...]) -> None:
        add_proc(proc, FakeProc(10, exe=exe, argv=args))
        assert procs.sweep_targets() == {}

    @pytest.mark.parametrize(
        ("exe", "args"),
        [
            (_PY, ("python3", _WSG)),
            (_PY, ("python3", _WSG, "review")),
            (_PY, ("python3", "-X", "dev", "-m", "wsg_grabber.cli")),
            ("/usr/bin/python", ("python", "/x/wsg_grabber.py")),
            ("/usr/bin/wsg_grabber", ("wsg_grabber", "review")),
        ],
    )
    def test_a_reviewer(self, proc: Path, exe: str, args: tuple[str, ...]) -> None:
        add_proc(proc, FakeProc(10, exe=exe, argv=args))
        assert procs.sweep_targets() == {10: "sweep:wsg-grabber"}

    def test_script_of_a_non_interpreter_is_none(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, exe="/usr/bin/git", argv=("git", "x.py")))
        assert procs.script_of(10) is None


class TestDeletedExe:
    def test_an_updated_browser_is_still_a_browser(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, exe="/opt/helium-browser-bin/helium (deleted)"))
        assert procs.exe_name(10) == "helium"
        assert procs.is_browser(10)
        assert procs.sweep_targets() == {10: "sweep:browser:helium"}

    def test_an_updated_player_is_still_swept(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, exe="/usr/bin/mpv (deleted)"))
        assert procs.sweep_targets() == {10: "sweep:media:mpv"}
        assert procs.exe_path(10) == "/usr/bin/mpv"
