"""Tests for moving spawned processes out of the service cgroup.

The unit is KillMode=control-group: a Steam left in the daemon's cgroup died
with the running game on every ``systemctl restart``. ``spawn_detached`` wraps
root launches in a transient scope; these pin when it does and when it must not.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._steam_process import spawn_detached

MOD = "steam_backlog_enforcer._steam_process"
SCOPE = ["systemd-run", "--scope", "--quiet", "--collect"]


def _argv(*, euid: int, which: str | None) -> list[str]:
    with (
        patch(f"{MOD}.os.geteuid", return_value=euid),
        patch(f"{MOD}.shutil.which", return_value=which),
        patch(f"{MOD}.subprocess.Popen") as mock_popen,
    ):
        spawn_detached(["steam", "-silent"])
    return mock_popen.call_args[0][0]


class TestSpawnDetachedScope:
    """Root launches leave the cgroup; anything else is spawned as asked."""

    def test_root_with_systemd_run_gets_its_own_scope(self) -> None:
        argv = _argv(euid=0, which="/usr/bin/systemd-run")
        assert argv == [*SCOPE, "steam", "-silent"]

    def test_root_without_systemd_run_launches_plainly(self) -> None:
        assert _argv(euid=0, which=None) == ["steam", "-silent"]

    def test_unprivileged_launch_is_never_wrapped(self) -> None:
        argv = _argv(euid=1000, which="/usr/bin/systemd-run")
        assert argv == ["steam", "-silent"]
