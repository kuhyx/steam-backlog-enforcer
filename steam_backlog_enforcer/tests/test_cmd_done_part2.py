"""Tests for _cmd_done module (part 2): _prompt_keep_or_skip."""

from __future__ import annotations

from unittest.mock import patch

from python_pkg.steam_backlog_enforcer._cmd_done import _prompt_keep_or_skip
from python_pkg.steam_backlog_enforcer.steam_api import GameInfo

CMD_DONE_PKG = "python_pkg.steam_backlog_enforcer._cmd_done"


class TestPromptKeepOrSkip:
    """Tests for _prompt_keep_or_skip."""

    def _game(self, hours: float = 5.0) -> GameInfo:
        return GameInfo(
            app_id=42,
            name="Test",
            total_achievements=10,
            unlocked_achievements=5,
            playtime_minutes=60,
            completionist_hours=hours,
        )

    def test_non_tty_accepts_silently(self) -> None:
        with patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert _prompt_keep_or_skip(self._game()) is True

    def test_yes_answers_accept(self) -> None:
        for answer in ("y", "Y", "yes", "YES", ""):
            with (
                patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin,
                patch(f"{CMD_DONE_PKG}._echo"),
                patch("builtins.input", return_value=answer),
            ):
                mock_stdin.isatty.return_value = True
                assert _prompt_keep_or_skip(self._game()) is True, answer

    def test_no_answers_reject(self) -> None:
        for answer in ("n", "N", "no", "NO"):
            with (
                patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin,
                patch(f"{CMD_DONE_PKG}._echo"),
                patch("builtins.input", return_value=answer),
            ):
                mock_stdin.isatty.return_value = True
                assert _prompt_keep_or_skip(self._game()) is False, answer

    def test_invalid_then_yes(self) -> None:
        echoed: list[str] = []
        with (
            patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin,
            patch(
                f"{CMD_DONE_PKG}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch("builtins.input", side_effect=["maybe", "y"]),
        ):
            mock_stdin.isatty.return_value = True
            assert _prompt_keep_or_skip(self._game()) is True
        assert any("answer 'y' or 'n'" in line for line in echoed)

    def test_eof_accepts(self) -> None:
        with (
            patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin,
            patch(f"{CMD_DONE_PKG}._echo"),
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_stdin.isatty.return_value = True
            assert _prompt_keep_or_skip(self._game()) is True

    def test_zero_hours_omits_hours_string(self) -> None:
        echoed: list[str] = []
        with (
            patch(f"{CMD_DONE_PKG}.sys.stdin") as mock_stdin,
            patch(
                f"{CMD_DONE_PKG}._echo",
                side_effect=lambda *a, **_: echoed.append(a[0]),
            ),
            patch("builtins.input", return_value="y"),
        ):
            mock_stdin.isatty.return_value = True
            _prompt_keep_or_skip(self._game(hours=0.0))
        # Without hours, the printed line should not contain "~"
        assert not any("~" in line for line in echoed if "Next pick" in line)
