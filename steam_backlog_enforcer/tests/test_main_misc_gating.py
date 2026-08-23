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


class TestCmdAddException:
    def test_no_args_prints_usage_and_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception([])

    def test_missing_reason_flag_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "no", "flag"])

    def test_non_numeric_app_id_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["notanumber", "--reason", VALID_REASON])

    def test_reason_flag_with_no_value_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason"])

    def test_reason_flag_last_position_with_no_value_exits(self) -> None:
        # 3 args passes the len/flag guard but --reason is last so reason_parts=[]
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "extra", "--reason"])

    def test_invalid_reason_exits(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", "too short"])

    def test_add_pending_exception_raises_value_error(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch(
                f"{PKG}.add_pending_exception",
                side_effect=ValueError("already approved"),
            ),
            pytest.raises(SystemExit, match="1"),
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])

    def test_happy_path(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(
                f"{PKG}.add_pending_exception",
                return_value="Exception approved for AppID 440. Active immediately.",
            ),
        ):
            cmd_add_exception(["440", "--reason", VALID_REASON])
        mock_echo.assert_called()


# ──────────────────────────────────────────────────────────────
# main() dispatch to add-exception
# ──────────────────────────────────────────────────────────────


class TestCmdBlockGaming:
    def test_no_args_shows_usage(self) -> None:
        with patch(f"{PKG}._echo") as mock_echo, pytest.raises(SystemExit) as exc_info:
            cmd_block_gaming([])
        assert exc_info.value.code == 1
        output = " ".join(str(c) for c in mock_echo.call_args_list)
        assert "Usage" in output

    def test_non_numeric_days(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["abc"])

    def test_zero_days_rejected(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["0"])

    def test_negative_days_rejected(self) -> None:
        with patch(f"{PKG}._echo"), pytest.raises(SystemExit):
            cmd_block_gaming(["-1"])

    def test_aborted_when_not_yes(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="no"),
            patch(f"{PKG}.start_total_block") as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_not_called()

    def test_confirmed_starts_block(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.start_total_block", return_value=True) as mock_start,
        ):
            cmd_block_gaming(["14"])
        mock_start.assert_called_once_with(14)

    def test_start_failure_exits_nonzero(self) -> None:
        with (
            patch(f"{PKG}._echo"),
            patch("builtins.input", return_value="YES"),
            patch(f"{PKG}.start_total_block", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            cmd_block_gaming(["14"])
        assert exc_info.value.code == 1


# ──────────────────────────────────────────────────────────────
# main() dispatch to block-gaming
# ──────────────────────────────────────────────────────────────
