"""Tests for game-name normalisation and the protected-name safety net.

Split to keep every test file under the 250-line cap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._game_names import (
    _is_protected_name,
    _normalize_game_name,
    _protected_name_stems,
)
from steam_backlog_enforcer.game_uninstall import (
    _remove_game_dirs,
)

if TYPE_CHECKING:
    from pathlib import Path

PKG = "steam_backlog_enforcer.game_install"
GAME_NAMES_PKG = "steam_backlog_enforcer._game_names"
GAME_UNINSTALL_PKG = "steam_backlog_enforcer.game_uninstall"


class TestNormalizeGameName:
    """Tests for _normalize_game_name."""

    def test_lowercases_and_strips_punctuation(self) -> None:
        """Names lowercase and lose punctuation and spaces."""
        assert (
            _normalize_game_name("Kingdom Come: Deliverance II")
            == "kingdomcomedeliverance2"
        )

    def test_matches_no_space_variant(self) -> None:
        """A name written without spaces normalises like the spaced one."""
        assert _normalize_game_name("KingdomComeDeliverance2") == _normalize_game_name(
            "Kingdom Come: Deliverance II"
        )

    def test_spelled_out_number_matches_digit(self) -> None:
        """A spelled-out number normalises like its digit."""
        assert _normalize_game_name("Portal Two") == _normalize_game_name("Portal 2")


class TestProtectedNameStems:
    """Tests for _protected_name_stems."""

    def test_returns_allowed_game_names(self) -> None:
        """Allowed game names are returned and blank names are dropped."""
        with (
            patch("steam_backlog_enforcer.config.State.load", return_value=MagicMock()),
            patch(
                "steam_backlog_enforcer._game_names.allowed_games",
                return_value=[(1771300, "Kingdom Come: Deliverance II"), (440, "")],
            ),
        ):
            stems = _protected_name_stems()
        assert stems == ["Kingdom Come: Deliverance II"]

    def test_returns_empty_list_when_state_cannot_load(self) -> None:
        """A state that cannot load yields no protected names."""
        with patch(
            "steam_backlog_enforcer.config.State.load", side_effect=RuntimeError("boom")
        ):
            stems = _protected_name_stems()
        assert stems == []

    def test_a_programming_bug_is_loud(self) -> None:
        """An error outside FAIL_SAFE_ERRORS propagates."""
        with (
            patch(
                "steam_backlog_enforcer.config.State.load",
                side_effect=AttributeError("bug"),
            ),
            pytest.raises(AttributeError, match="bug"),
        ):
            _protected_name_stems()


class TestIsProtectedName:
    """Tests for _is_protected_name."""

    def test_blank_candidate_is_not_protected(self) -> None:
        """A blank candidate is never protected."""
        assert _is_protected_name("   ") is False

    def test_matches_exact_normalized_name(self) -> None:
        """A candidate matching a protected name after normalising is protected."""
        with patch(
            f"{GAME_NAMES_PKG}._protected_name_stems",
            return_value=["Kingdom Come: Deliverance II"],
        ):
            assert _is_protected_name("KingdomComeDeliverance2") is True

    def test_matches_typo_via_fuzzy_ratio(self) -> None:
        """A close misspelling of a protected name is protected."""
        with patch(
            f"{GAME_NAMES_PKG}._protected_name_stems",
            return_value=["Kingdom Come: Deliverance II"],
        ):
            assert _is_protected_name("Kingdom Come Delievarnce 2") is True

    def test_no_match_for_unrelated_name(self) -> None:
        """An unrelated name is not protected."""
        with patch(
            f"{GAME_NAMES_PKG}._protected_name_stems",
            return_value=["Kingdom Come: Deliverance II"],
        ):
            assert _is_protected_name("Cogmind") is False

    def test_skips_blank_protected_name(self) -> None:
        """Blank protected names are skipped and the rest still match."""
        with patch(
            f"{GAME_NAMES_PKG}._protected_name_stems", return_value=["", "Cogmind"]
        ):
            assert _is_protected_name("Cogmind") is True


class TestRemoveGameDirsProtectedName:
    """Tests for the _is_protected_name safety net inside _remove_game_dirs."""

    def test_refuses_to_remove_protected_name(self, tmp_path: Path) -> None:
        """A protected install dir is left on disk and reported as not removed."""
        install_dir = tmp_path / "common" / "Kingdom Come: Deliverance II"
        install_dir.mkdir(parents=True)
        (install_dir / "game.exe").touch()
        with (
            patch("steam_backlog_enforcer.game_uninstall.STEAMAPPS_PATH", tmp_path),
            patch(
                "steam_backlog_enforcer.game_uninstall._is_protected_name",
                return_value=True,
            ),
        ):
            result = _remove_game_dirs(install_dir, 1771300)
        assert result is False
        assert install_dir.exists()
        assert (install_dir / "game.exe").exists()
