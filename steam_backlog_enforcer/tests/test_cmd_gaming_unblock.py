"""Tests for ``gaming-unblock``, the root-only recovery hatch for the budget.

Split out of ``test_cmd_playtime.py`` to keep both files inside the 250-line cap.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._cmd_playtime import cmd_gaming_unblock
from steam_backlog_enforcer.tests._cmd_playtime_patches import cli_as, echoed

PKG = "steam_backlog_enforcer._cmd_playtime"


class TestCmdGamingUnblock:
    """gaming-unblock releases the mounts as root and nothing else."""

    def test_rejects_arguments(self) -> None:
        """Any argument is rejected before anything is released."""
        with cli_as(None) as mocks:
            assert cmd_gaming_unblock(["--force"]) == 2
        mocks.release.assert_not_called()
        assert "Unknown argument" in echoed(mocks.echo)

    def test_requires_root(self) -> None:
        """Without root nothing is released."""
        with cli_as(1000) as mocks:
            assert cmd_gaming_unblock([]) == 1
        mocks.release.assert_not_called()
        assert "requires root" in echoed(mocks.echo)

    def test_reports_when_nothing_was_mounted(self) -> None:
        """With nothing mounted it says so and succeeds."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.release_block", return_value=[]),
        ):
            assert cmd_gaming_unblock([]) == 0
        assert "No playtime mounts" in echoed(mock_echo)

    def test_lists_released_mounts(self) -> None:
        """Every released mount is listed."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo") as mock_echo,
            patch(
                f"{PKG}.release_block",
                return_value=["/usr/bin/steam", "/usr/bin/lutris"],
            ),
        ):
            assert cmd_gaming_unblock([]) == 0
        output = echoed(mock_echo)
        assert "/usr/bin/steam" in output
        assert "/usr/bin/lutris" in output

    def test_consults_no_state_at_all(self) -> None:
        """The recovery hatch must work with an unreadable state file."""
        with (
            patch(f"{PKG}.os.geteuid", return_value=0),
            patch(f"{PKG}._echo"),
            patch(
                f"{PKG}.load_state", side_effect=AssertionError("must not be called")
            ),
            patch(f"{PKG}.release_block", return_value=[]),
        ):
            assert cmd_gaming_unblock([]) == 0
