"""Tests for the main CLI: add-exception and block-gaming commands."""

from unittest.mock import patch

import pytest

from steam_backlog_enforcer.main import (
    cmd_add_exception,
    cmd_block_gaming,
)
from steam_backlog_enforcer.tests._main_helpers import (
    VALID_REASON,
)

PKG = "steam_backlog_enforcer.main.misc"
EXC_PKG = "steam_backlog_enforcer.main.exception"
_PHRASE = "request exception for AppID=440"
_BLOCK_PHRASE = "block all gaming for 14 days"


class TestCmdAddException:
    """add-exception validates arguments and the typed phrase."""

    def test_no_args_prints_usage_and_exits(self) -> None:
        """No arguments prints usage and exits 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception([])

    def test_missing_reason_flag_exits(self) -> None:
        """Arguments without a --reason flag exit 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "no", "flag"])

    def test_non_numeric_app_id_exits(self) -> None:
        """A non-numeric app id exits 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["notanumber", "--reason", VALID_REASON])

    def test_reason_flag_with_no_value_exits(self) -> None:
        """A --reason flag with no value exits 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason"])

    def test_reason_flag_last_position_with_no_value_exits(self) -> None:
        """A trailing --reason with no words after it exits 1."""
        # 3 args passes the len/flag guard but --reason is last so reason_parts=[]
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "extra", "--reason"])

    def test_invalid_reason_exits(self) -> None:
        """A reason that fails validation exits 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", "too short"])

    def test_add_pending_exception_raises_value_error(self) -> None:
        """A ValueError from adding the exception exits 1."""
        with (
            patch(f"{EXC_PKG}._echo"),
            patch("builtins.input", return_value=_PHRASE),
            patch(
                f"{EXC_PKG}.add_pending_exception",
                side_effect=ValueError("already approved"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])

    def test_wrong_phrase_aborts_before_adding(self) -> None:
        """A wrong confirmation phrase aborts before anything is added."""
        with (
            patch(f"{EXC_PKG}._echo") as mock_echo,
            patch("builtins.input", return_value="please"),
            patch(f"{EXC_PKG}.add_pending_exception") as mock_add,
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])
        mock_add.assert_not_called()
        assert mock_echo.call_args.args == ("Aborted.",)

    def test_phrase_names_the_game_from_the_snapshot(self) -> None:
        """The confirmation phrase uses the game name from the snapshot."""
        with (
            patch(f"{EXC_PKG}._echo"),
            patch(f"{EXC_PKG}.snapshot_game_name", return_value="Team Fortress 2"),
            patch(
                "builtins.input", return_value="request exception for Team Fortress 2"
            ),
            patch(f"{EXC_PKG}.add_pending_exception", return_value="done") as add,
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])
        add.assert_called_once_with(440, VALID_REASON)

    def test_happy_path(self) -> None:
        """The right phrase and reason add the exception and report it."""
        with (
            patch(f"{EXC_PKG}._echo") as mock_echo,
            patch("builtins.input", return_value=_PHRASE),
            patch(
                f"{EXC_PKG}.add_pending_exception",
                return_value="Exception approved for AppID 440. Active immediately.",
            ),
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])
        mock_echo.assert_called()


# ──────────────────────────────────────────────────────────────
# main() dispatch to add-exception
# ──────────────────────────────────────────────────────────────


class TestCmdBlockGaming:
    """block-gaming validates the day count and the typed phrase."""

    def test_no_args_shows_usage(self) -> None:
        """No arguments prints usage and exits 1."""
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit) as exc_info:
            cmd_block_gaming([])
        assert exc_info.value.code == 1
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Usage" in output

    def test_non_numeric_days(self) -> None:
        """A non-numeric day count exits."""
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["abc"])

    def test_zero_days_rejected(self) -> None:
        """Zero days is rejected."""
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["0"])

    def test_negative_days_rejected(self) -> None:
        """A negative day count is rejected."""
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["-1"])

    def test_aborted_when_not_yes(self) -> None:
        """A wrong confirmation phrase starts no block."""
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch(f"{PKG}.start_total_block") as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_not_called()

    def test_confirmed_starts_block(self) -> None:
        """The right phrase starts a block for the given days."""
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value=_BLOCK_PHRASE),
            patch(f"{PKG}.start_total_block", return_value=True) as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_called_once_with(14)

    def test_start_failure_exits_nonzero(self) -> None:
        """A block that fails to start exits 1."""
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value=_BLOCK_PHRASE),
            patch(f"{PKG}.start_total_block", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_block_gaming(["14"])
        assert exc_info.value.code == 1


# ──────────────────────────────────────────────────────────────
# main() dispatch to block-gaming
# ──────────────────────────────────────────────────────────────
