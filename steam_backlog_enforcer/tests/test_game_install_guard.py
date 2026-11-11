"""Tests for install_game's Steam-library readiness guard.

Split from test_game_install_part3.py to keep both files under the 250-line cap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._enforce_steps import _reinstall_missing_allowed
from steam_backlog_enforcer.game_install import _LIBRARY_WARNED, install_game

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestInstallGameLibraryGuard:
    """install_game must not retry when Steam has no library at all.

    Without this the enforce loop re-triggered every allowed game on every
    pass (measured: 1656 attempts in 30 minutes), each one launching Steam
    as root and raising FileNotFoundError on the manifest write.
    """

    _PKG = "steam_backlog_enforcer.game_install"

    def test_skips_when_library_missing(self, tmp_path: Path) -> None:
        """With no Steam library, install neither starts Steam nor triggers."""
        missing = tmp_path / "steamapps"  # deliberately not created
        with (
            patch(f"{self._PKG}.STEAMAPPS_PATH", missing),
            patch(f"{self._PKG}.steam_library_ready", return_value=False),
            patch(f"{self._PKG}._ensure_steam_running") as mock_ensure,
            patch(f"{self._PKG}._trigger_steam_install") as mock_trigger,
        ):
            assert (
                install_game(440, "TF2", "steam123", use_steam_protocol=True) is False
            )

        mock_ensure.assert_not_called()
        mock_trigger.assert_not_called()

    def test_proceeds_when_library_present(self, tmp_path: Path) -> None:
        """With a library present, install goes ahead and succeeds."""
        with (
            patch(f"{self._PKG}.STEAMAPPS_PATH", tmp_path),
            patch(f"{self._PKG}.steam_library_ready", return_value=True),
            patch(f"{self._PKG}._ensure_steam_running"),
            patch(f"{self._PKG}._trigger_steam_install", return_value=True),
        ):
            result = install_game(440, "TF2", "steam123", use_steam_protocol=True)
        assert result is True


class TestReinstallMissingAllowedGuard:
    """_reinstall_missing_allowed must stay quiet when there is no library.

    install_game guards this too, but the caller logs one INFO line per game
    *before* calling it — at a 3s cadence that is its own log storm.
    """

    _PKG = "steam_backlog_enforcer._enforce_steps"

    def test_skips_when_library_missing(self) -> None:
        """With no library, reinstall never even lists allowed games."""
        with (
            patch(f"{self._PKG}.steam_library_ready", return_value=False),
            patch(f"{self._PKG}.allowed_games") as mock_allowed,
            patch(f"{self._PKG}.install_game") as mock_install,
        ):
            _reinstall_missing_allowed(MagicMock(), MagicMock())

        mock_allowed.assert_not_called()
        mock_install.assert_not_called()

    def test_proceeds_when_library_present(self) -> None:
        """With a library, a missing allowed game is reinstalled."""
        with (
            patch(f"{self._PKG}.steam_library_ready", return_value=True),
            patch(f"{self._PKG}.allowed_games", return_value=[(440, "TF2")]),
            patch(f"{self._PKG}.is_game_installed", return_value=False),
            patch(f"{self._PKG}.install_game") as mock_install,
        ):
            _reinstall_missing_allowed(MagicMock(), MagicMock())

        mock_install.assert_called_once()


class TestLibraryWarningLatch:
    """The "no library" warning must fire once, not once per game per pass.

    At the observed 3s cadence an unlatched warning replaces a traceback storm
    with a log storm, which is the same bug in a different costume.
    """

    _PKG = "steam_backlog_enforcer.game_install"

    def test_warns_once_then_debugs(self, caplog: pytest.LogCaptureFixture) -> None:
        """Repeated misses warn once, then log at debug."""
        _LIBRARY_WARNED.discard("missing")
        with (
            patch(f"{self._PKG}.steam_library_ready", return_value=False),
            caplog.at_level(
                logging.DEBUG, logger="steam_backlog_enforcer.game_install"
            ),
        ):
            for _ in range(3):
                install_game(440, "TF2", "steam123")

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        assert len(warnings) == 1
        assert len(debugs) == 2

    def test_latch_resets_when_library_returns(self) -> None:
        """Signing in to Steam must re-arm the warning for a later outage."""
        _LIBRARY_WARNED.add("missing")
        with (
            patch(f"{self._PKG}.steam_library_ready", return_value=True),
            patch(f"{self._PKG}.is_game_installed", return_value=True),
        ):
            install_game(440, "TF2", "steam123")

        assert "missing" not in _LIBRARY_WARNED
