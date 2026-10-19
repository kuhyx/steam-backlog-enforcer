"""Process identity for leisure kills: browsers, players, lockers, ownership."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from steam_backlog_enforcer import _leisure_procs as procs
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    return leisure_proc(tmp_path)


class TestNames:
    @pytest.mark.parametrize(
        "exe",
        [
            "/opt/helium-browser-bin/helium",
            "/usr/lib/librewolf/librewolf",
            "/usr/lib/chromium/chromium",
            "/opt/google/chrome/chrome",
            "/opt/brave.com/brave/brave",
            "/opt/vivaldi/vivaldi-bin",
            "/usr/lib/opera/opera",
            "/opt/microsoft/msedge/msedge",
            "/usr/lib/firefox/firefox-bin",
            "/opt/zen-browser-bin/zen-bin",
            "/opt/helium-browser-bin/helium_crashpad_handler",
        ],
    )
    def test_browser_families_by_exe(self, proc: Path, exe: str) -> None:
        add_proc(proc, FakeProc(10, exe=exe, comm="Isolated Web Co"))
        assert procs.is_browser(10)

    @pytest.mark.parametrize(
        "exe", ["/usr/bin/mpv", "/usr/bin/operator", "/usr/bin/frozen", "/x/knowledge"]
    )
    def test_non_browsers(self, proc: Path, exe: str) -> None:
        add_proc(proc, FakeProc(10, exe=exe))
        assert not procs.is_browser(10)

    def test_unreadable_exe_falls_back_to_comm(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, comm="helium"))
        (proc / "10" / "exe").unlink()
        assert procs.exe_name(10) == "helium"
        assert procs.is_browser(10)

    def test_a_vanished_pid_has_no_name(self) -> None:
        assert procs.exe_name(99) == ""
        assert procs.argv(99) == ()
        assert procs.real_uid(99) is None
        assert procs.start_time(99) is None
        assert procs.parent(99) is None

    def test_reads_uid_start_and_parent(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, uid=1000, ppid=7, start=4242))
        assert (procs.real_uid(10), procs.start_time(10), procs.parent(10)) == (
            1000,
            4242,
            7,
        )

    def test_malformed_status_and_stat(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10))
        (proc / "10" / "status").write_text("Name:\tmpv\nUid:\tx\n", encoding="utf-8")
        (proc / "10" / "stat").write_text("10 (mpv) S", encoding="utf-8")
        assert procs.real_uid(10) is None
        assert procs.start_time(10) is None
        (proc / "10" / "stat").write_text("10 (mpv) S x", encoding="utf-8")
        assert procs.parent(10) is None

    def test_status_without_a_uid_line(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10))
        (proc / "10" / "status").write_text("Name:\tmpv\n", encoding="utf-8")
        assert procs.real_uid(10) is None


class TestProtected:
    def test_a_plain_user_player_is_fair_game(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10))
        assert not procs.is_protected(10, set())

    @pytest.mark.parametrize("uid", [0, 999, 1001])
    def test_anything_not_the_desktop_users(self, proc: Path, uid: int) -> None:
        add_proc(proc, FakeProc(10, uid=uid))
        assert procs.is_protected(10, set())

    def test_a_vanished_pid_is_never_signalled(self) -> None:
        assert procs.is_protected(99, set())

    def test_own_chain(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10))
        assert procs.is_protected(10, {10})

    @pytest.mark.parametrize(
        "argv",
        [
            ("i3lock", "--nofork"),
            ("/usr/bin/python3", "-m", "screen_locker._web_server"),
            ("python3", "/home/kuhy/.config/i3/scripts/leetcode_guard_tray.py"),
            ("/usr/bin/book-guard",),
        ],
    )
    def test_lockers_and_their_children(
        self, proc: Path, argv: tuple[str, ...]
    ) -> None:
        add_proc(proc, FakeProc(5, exe="/usr/bin/python3", argv=argv, comm="x"))
        add_proc(proc, FakeProc(10, ppid=5))
        assert procs.is_protected(5, set())
        assert procs.is_protected(10, set())

    def test_a_parent_loop_terminates(self, proc: Path) -> None:
        add_proc(proc, FakeProc(10, ppid=11))
        add_proc(proc, FakeProc(11, ppid=10))
        assert not procs.is_protected(10, set())

    def test_own_chain_walks_up(self, proc: Path) -> None:
        me = os.getpid()
        add_proc(proc, FakeProc(me, ppid=77))
        add_proc(proc, FakeProc(77, ppid=1))
        assert procs.own_chain() == {me, 77, 1}


class TestSweep:
    def test_untrusted_watcher_sweeps_browsers_players_and_the_reviewer(
        self, proc: Path
    ) -> None:
        add_proc(proc, FakeProc(10, exe="/opt/helium-browser-bin/helium"))
        add_proc(proc, FakeProc(11, exe="/usr/bin/mpv"))
        add_proc(proc, FakeProc(12, exe="/opt/FreeTube/freetube"))
        add_proc(
            proc,
            FakeProc(
                13, exe="/usr/bin/python3.14", argv=("python3", "-m", "wsg_grabber")
            ),
        )
        add_proc(
            proc,
            FakeProc(
                14,
                exe="/usr/bin/python3.14",
                argv=("python3", "-m", "wsg_grabber", "scrape"),
            ),
        )
        add_proc(proc, FakeProc(15, exe="/usr/bin/terminator"))
        add_proc(proc, FakeProc(16, exe="/usr/bin/wsg-grabber", argv=("wsg-grabber",)))
        (proc / "self").mkdir()
        assert procs.sweep_targets() == {
            10: "sweep:browser:helium",
            11: "sweep:media:mpv",
            12: "sweep:media:freetube",
            13: "sweep:wsg-grabber",
            16: "sweep:wsg-grabber",
        }

    def test_an_unlistable_proc_sweeps_nothing(self, proc: Path) -> None:
        proc.rmdir()
        assert procs.sweep_targets() == {}

    def test_a_deep_tree_walk_is_bounded(self, proc: Path) -> None:
        for pid in range(100, 150):
            add_proc(proc, FakeProc(pid, ppid=pid + 1))
        add_proc(proc, FakeProc(150, argv=("i3lock",)))
        # The locker is 50 generations up: past the bound, so not seen.
        assert not procs.is_protected(100, set())
