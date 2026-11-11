"""Strict mode: during research only runtimes survive besides the allowed game."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

from steam_backlog_enforcer._enforce_guards import guard_installed_games
from steam_backlog_enforcer.enforcer import enforce_allowed_game
from steam_backlog_enforcer.game_uninstall import (
    is_infrastructure_app,
    is_protected_app,
)

UNI = "steam_backlog_enforcer.game_uninstall"
LIBRARIAN = 4197610
EXCEPTION = 880940  # an approved whitelist exception
ZERO_ACH = 555  # an owned game with no achievements
PROTON = 1493710  # Proton Experimental, a runtime
OTHER = 111


def _world() -> tuple[object, object]:
    """Patch the two exemption sources: approved exceptions and zero-ach games."""
    return (
        patch(f"{UNI}.get_approved_exception_ids", return_value={EXCEPTION}),
        patch(f"{UNI}.zero_achievement_ids", return_value={ZERO_ACH}),
    )


class TestPredicates:
    """Infrastructure is the strict subset of protected."""

    def test_runtime_is_infrastructure(self) -> None:
        """Test that Proton is protected in both modes."""
        assert is_infrastructure_app(PROTON)
        assert is_protected_app(PROTON)

    def test_exceptions_are_protected_but_not_infrastructure(self) -> None:
        """Test that the whitelist does not reach strict mode."""
        exc, zero = _world()
        with exc, zero:
            assert is_protected_app(EXCEPTION)
            assert is_protected_app(ZERO_ACH)
            assert not is_infrastructure_app(EXCEPTION)
            assert not is_infrastructure_app(ZERO_ACH)


class TestKill:
    """enforce_allowed_game with and without strict."""

    RUNNING: ClassVar[dict[int, int]] = {
        10: LIBRARIAN,
        11: EXCEPTION,
        12: ZERO_ACH,
        13: PROTON,
        14: 0,
        15: OTHER,
    }

    def _violations(self, *, strict: bool) -> list[tuple[int, int]]:
        exc, zero = _world()
        with (
            exc,
            zero,
            patch(
                "steam_backlog_enforcer.enforcer.get_running_steam_game_pids",
                return_value=self.RUNNING,
            ),
            patch("steam_backlog_enforcer.enforcer.kill_process"),
        ):
            return enforce_allowed_game(
                {LIBRARIAN}, kill_unauthorized=True, strict=strict
            )

    def test_default_spares_exceptions(self) -> None:
        """Test that normal enforcement is unchanged."""
        assert self._violations(strict=False) == [(15, OTHER)]

    def test_strict_kills_exceptions_and_zero_achievement_games(self) -> None:
        """Test that only Librarian, runtimes and app 0 survive strict mode."""
        assert self._violations(strict=True) == [
            (11, EXCEPTION),
            (12, ZERO_ACH),
            (15, OTHER),
        ]


class TestUninstall:
    """guard_installed_games with and without strict."""

    INSTALLED: ClassVar[list[tuple[int, str]]] = [
        (LIBRARIAN, "Librarian"),
        (EXCEPTION, "Party game"),
        (ZERO_ACH, "No achievements"),
        (PROTON, "Proton Experimental"),
        (OTHER, "Other"),
    ]

    def _removed(self, *, strict: bool) -> list[int]:
        exc, zero = _world()
        with (
            exc,
            zero,
            patch(
                "steam_backlog_enforcer._enforce_guards.get_installed_games",
                return_value=self.INSTALLED,
            ),
            patch(
                "steam_backlog_enforcer._enforce_guards.uninstall_game",
                return_value=True,
            ) as uninstall,
            patch("steam_backlog_enforcer._enforce_guards.send_notification"),
        ):
            guard_installed_games({LIBRARIAN}, strict=strict)
        return [call.args[0] for call in uninstall.call_args_list]

    def test_default_spares_exceptions(self) -> None:
        """Test that normal enforcement is unchanged."""
        assert self._removed(strict=False) == [OTHER]

    def test_strict_removes_everything_but_librarian_and_runtimes(self) -> None:
        """Test that exceptions and zero-achievement games go in strict mode."""
        assert self._removed(strict=True) == [EXCEPTION, ZERO_ACH, OTHER]
