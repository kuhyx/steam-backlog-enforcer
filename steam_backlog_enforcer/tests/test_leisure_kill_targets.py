"""Phase 2 at 0: which pids a ``now.json`` fact names as kill targets."""

from __future__ import annotations

from typing import TYPE_CHECKING

from leisure_watch.facts import Reason
import pytest

from steam_backlog_enforcer._leisure_kill import fact_targets
from steam_backlog_enforcer.tests._leisure_kill_world import build_proc, now_with

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(name="proc")
def fixture_proc(tmp_path: Path) -> Path:
    """Isolated /proc with mpv, helium, chromium and a root-owned app."""
    return build_proc(tmp_path)


class TestFactTargets:
    """Only media/focus apps and non-reporting browsers become targets."""

    def test_media_and_focus_apps_die_browsers_and_games_do_not(
        self, proc: Path
    ) -> None:
        """Media and focus pids are named; url-only, game and unknown are not."""
        del proc
        fact = now_with(
            Reason("media", "app:mpv", 10, "mpv"),
            Reason("focus", "domain:youtube.com", 20, "YouTube"),
            Reason("media", "domain:youtube.com", None, "url"),
            Reason("game", "steam:440", 50, "tf2"),
            Reason("mystery", "x", 10, "?"),
        )
        assert fact_targets(fact) == {10: "app:mpv"}

    @pytest.mark.parametrize(
        ("pid", "key"),
        [
            (20, "failclosed:helium"),
            (20, "failclosed:helium:unreported"),
            (20, "failclosed:helium:audio"),
            (30, "browser:chromium"),
        ],
    )
    def test_a_non_reporting_browser_dies(self, proc: Path, pid: int, key: str) -> None:
        """A fail-closed or bare browser reason targets its pid."""
        del proc
        fact = now_with(Reason("failclosed", key, pid, "x"))
        assert fact_targets(fact) == {pid: key}

    def test_failclosed_without_a_pid_names_nothing(self) -> None:
        """A fail-closed reason with no pid yields no target."""
        fact = now_with(Reason("failclosed", "failclosed:display", None, "X"))
        assert fact_targets(fact) == {}
