"""Tests for the autouse real-effect guard in ``_no_real_effects``.

Every call that the guard blocks is cleared from its record before the
test ends; otherwise the guard's own teardown would (correctly) fail it.

``subprocess.Popen`` / ``subprocess.run`` are MagicMocks during tests (see
``_no_subprocess``), so real spawns here go through the captured class.
"""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._enforce_demo import run_demo
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests import _no_real_effects as guard
from steam_backlog_enforcer.tests._no_real_effects import (
    _REAL_POPEN,
    RealEffectError,
    _argv,
    _drives_steam,
    _fail_if_blocked,
    _is_ours,
    _parent_of,
)

# Never a live pid: if the guard ever let it through, the kernel would only
# answer ProcessLookupError (unlike pid 1, which a root run would SIGTERM).
_NO_SUCH_PID = int(Path("/proc/sys/kernel/pid_max").read_text(encoding="utf-8"))


@pytest.fixture
def blocked(request: pytest.FixtureRequest) -> list[str]:
    """The autouse guard's record of blocked calls, for inspection."""
    record: list[str] = request.getfixturevalue("_no_real_effects")
    return record


@pytest.fixture
def child() -> object:
    """A real, short-lived child of pytest in its own session."""
    proc = _REAL_POPEN(["sleep", "30"], start_new_session=True)
    yield proc
    proc.kill()
    proc.wait()


class TestDrivesSteam:
    @pytest.mark.parametrize(
        "argv",
        [
            ["steam"],
            ["/usr/bin/steam", "-silent"],
            ["sudo", "-u", "kuhy", "steam.sh"],
            ["xdg-open", "https://example.com"],
            ["runuser", "steam-game-installer", "620"],
            ["pkill", "-f", "x"],
            ["killall", "x"],
            ["/bin/kill", "-TERM", "42"],
            ["foo", "steam://rungameid/620"],
            ["foo", "-shutdown"],
        ],
    )
    def test_steam_and_kill_tools_are_denied(self, argv: list[str]) -> None:
        assert _drives_steam(argv)

    def test_ordinary_commands_pass(self) -> None:
        assert not _drives_steam(["git", "status", "--steam"])


class TestArgv:
    def test_string_without_shell_is_one_program(self) -> None:
        assert _argv("steam -shutdown", via_shell=False) == ["steam -shutdown"]

    def test_string_with_shell_is_split(self) -> None:
        assert _argv("steam -shutdown", via_shell=True) == ["steam", "-shutdown"]

    def test_bytes_and_paths_are_decoded(self) -> None:
        assert _argv([b"a", Path("/b"), "c"], via_shell=False) == ["a", "/b", "c"]
        assert _argv(Path("/usr/bin/steam"), via_shell=False) == ["/usr/bin/steam"]


class TestIsOurs:
    def test_pytest_itself(self) -> None:
        assert _is_ours(os.getpid(), set())

    @pytest.mark.parametrize("pid", [0, -1])
    def test_group_and_broadcast_pids_never(self, pid: int) -> None:
        assert not _is_ours(pid, set())

    def test_init_and_missing_pids_never(self) -> None:
        assert not _is_ours(1, set())
        assert not _is_ours(_NO_SUCH_PID, set())

    def test_descendants(self, child: subprocess.Popen[bytes]) -> None:
        assert _is_ours(child.pid, set())

    def test_reparented_spawns_still_count(self) -> None:
        with patch.object(guard, "_parent_of", return_value=1):
            assert _is_ours(4242, {4242})
            assert not _is_ours(4242, set())

    def test_a_cyclic_table_gives_up(self) -> None:
        with patch.object(guard, "_parent_of", return_value=4243):
            assert not _is_ours(4242, set())


class TestParentOf:
    def test_reads_ppid_after_last_paren(self, tmp_path: Path) -> None:
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "stat").write_text("7 (a) b) S 3 7 7 0", encoding="utf-8")
        with patch.object(guard, "_REAL_PROC", tmp_path):
            assert _parent_of(7) == 3

    def test_truncated_stat(self, tmp_path: Path) -> None:
        (tmp_path / "7").mkdir()
        (tmp_path / "7" / "stat").write_text("7 (a) S", encoding="utf-8")
        with patch.object(guard, "_REAL_PROC", tmp_path):
            assert _parent_of(7) is None


class TestGuardedKill:
    def test_foreign_signal_is_refused_and_recorded(self, blocked: list[str]) -> None:
        with pytest.raises(RealEffectError):
            os.kill(_NO_SUCH_PID, signal.SIGTERM)
        assert blocked == [f"os.kill(pid={_NO_SUCH_PID}, sig={signal.SIGTERM})"]
        blocked.clear()

    def test_broadcast_is_refused(self, blocked: list[str]) -> None:
        with pytest.raises(RealEffectError):
            os.kill(-1, signal.SIGTERM)
        with pytest.raises(RealEffectError):
            os.killpg(0, signal.SIGTERM)
        assert len(blocked) == 2
        blocked.clear()

    def test_probe_passes_through(self) -> None:
        with pytest.raises(ProcessLookupError):
            os.kill(_NO_SUCH_PID, 0)
        with pytest.raises(ProcessLookupError):
            os.killpg(_NO_SUCH_PID, 0)

    def test_own_children_can_be_signalled(
        self, child: subprocess.Popen[bytes]
    ) -> None:
        os.kill(child.pid, signal.SIGSTOP)
        os.killpg(child.pid, signal.SIGKILL)
        assert child.wait(timeout=5) == -signal.SIGKILL


class TestGuardedPopen:
    def test_steam_spawn_is_refused(self, blocked: list[str]) -> None:
        with pytest.raises(RealEffectError):
            _REAL_POPEN(["steam", "-shutdown"])
        with pytest.raises(RealEffectError):
            _REAL_POPEN(["anything"], executable="/usr/bin/steam")
        assert len(blocked) == 2
        blocked.clear()

    def test_ordinary_spawns_run(self) -> None:
        proc = _REAL_POPEN([sys.executable, "-c", "print(1)"], stdout=subprocess.PIPE)
        out, _ = proc.communicate(timeout=10)
        assert out.strip() == b"1"


class TestDemoTripwire:
    def test_unpatched_demo_loop_fails_at_once(self, blocked: list[str]) -> None:
        """The real loop never returns on its own: it must not even tick."""
        with (
            patch("steam_backlog_enforcer._enforce_demo._echo"),
            pytest.raises(RealEffectError),
        ):
            run_demo(Config())
        assert blocked == ["unpatched enforce --demo loop (playtime_tick)"]
        blocked.clear()


class TestFailIfBlocked:
    def test_fails_naming_each_call(self) -> None:
        with pytest.raises(pytest.fail.Exception, match="a; b"):
            _fail_if_blocked(["a", "b"])

    def test_silent_when_clean(self) -> None:
        _fail_if_blocked([])
