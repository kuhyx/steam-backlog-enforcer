"""Tests for the main CLI: argv resolution and command dispatch."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import (
    _print_usage,
    _resolve_command,
    main,
)

PKG = "steam_backlog_enforcer.main"
CMD_DONE_PKG = "steam_backlog_enforcer._cmd_done"


class TestMain:
    """Tests for main CLI entry point."""

    def test_no_args_exits(self) -> None:
        """No command prints usage and exits 1."""
        with (
            patch.object(sys, "argv", ["prog"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_unknown_command_exits(self) -> None:
        """An unknown command exits 1."""
        with (
            patch.object(sys, "argv", ["prog", "bogus"]),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_valid_command_runs(self) -> None:
        """A known command runs with the loaded config and state."""
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"status": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_setup_no_key_required(self) -> None:
        """setup runs without an API key."""
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "setup"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"setup": ("s", mock_cmd)}),
        ):
            main()
        mock_cmd.assert_called_once()

    def test_no_api_key_exits(self) -> None:
        """Other commands exit when the API key is missing."""
        with (
            patch.object(sys, "argv", ["prog", "status"]),
            patch(f"{PKG}.Config.load", return_value=Config()),
            patch(f"{PKG}._echo"),
            pytest.raises(SystemExit, match="1"),
        ):
            main()

    def test_dashed_command_dispatches_with_note(self) -> None:
        """'--status' runs 'status' and says so."""
        mock_cmd = MagicMock()
        with (
            patch.object(sys, "argv", ["prog", "--status"]),
            patch(f"{PKG}.Config.load", return_value=Config(steam_api_key="k")),
            patch(f"{PKG}.State.load", return_value=State()),
            patch.dict(f"{PKG}.COMMANDS", {"status": ("s", mock_cmd)}),
            patch(f"{PKG}._echo") as mock_echo,
        ):
            main()
        mock_cmd.assert_called_once()
        assert any(
            "treating '--status' as 'status'" in str(call.args[0])
            for call in mock_echo.call_args_list
            if call.args
        )

    @pytest.mark.parametrize("raw", ["bogus", "--bogus"])
    def test_unknown_command_names_the_input(self, raw: str) -> None:
        """The unknown-command error names what was typed."""
        with (
            patch.object(sys, "argv", ["prog", raw]),
            patch("steam_backlog_enforcer.main._registry._echo") as mock_echo,
            pytest.raises(SystemExit, match="1"),
        ):
            main()
        assert any(
            str(call.args[0]).startswith(f"Unknown command: {raw}")
            for call in mock_echo.call_args_list
            if call.args
        )


class TestResolveCommand:
    """Tests for argv[1] normalisation and the usage printer."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("status", "status"),
            ("--status", "status"),
            ("--abandon-pick", "abandon-pick"),
            ("-status", "status"),
            ("bogus", None),
            ("--bogus", None),
            ("--", None),
        ],
    )
    def test_resolve(self, raw: str, expected: str | None) -> None:
        """_resolve_command maps raw input to a command name or None."""
        assert _resolve_command(raw) == expected

    def test_usage_suggests_close_match(self) -> None:
        """Usage suggests a close command name."""
        with patch("steam_backlog_enforcer.main._registry._echo") as mock_echo:
            _print_usage("statu")
        lines = [str(c.args[0]) for c in mock_echo.call_args_list if c.args]
        assert "Did you mean 'status'?" in lines

    def test_usage_omits_suggestion_when_far_off(self) -> None:
        """Usage suggests nothing for a far-off name."""
        with patch("steam_backlog_enforcer.main._registry._echo") as mock_echo:
            _print_usage("--zzzzzz")
        lines = [str(c.args[0]) for c in mock_echo.call_args_list if c.args]
        assert not any(line.startswith("Did you mean") for line in lines)

    def test_usage_without_unknown_has_no_error_line(self) -> None:
        """Plain usage has no unknown-command line."""
        with patch("steam_backlog_enforcer.main._registry._echo") as mock_echo:
            _print_usage()
        lines = [str(c.args[0]) for c in mock_echo.call_args_list if c.args]
        assert not any(line.startswith("Unknown command") for line in lines)
