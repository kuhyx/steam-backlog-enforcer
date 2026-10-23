"""``pick`` CLI/web wiring: the keep default, ``--replace`` and the cap.

The keep/replace state model itself is covered in ``test_pick_keep``; this
file covers how the choice reaches it (argv, web params, job handler), the
refusal when the allowed set is full, and abandoning a kept game.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._command_params import (
    PARAMS,
    InvalidParamsError,
    validate_params,
)
from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs import _registry
from steam_backlog_enforcer.main import (
    _dispatch_extra_command,
    cmd_abandon_pick,
    cmd_pick,
)
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter
from steam_backlog_enforcer.tests._main_helpers import STARTED_AT, snap

PKG = "steam_backlog_enforcer.main.picks"
_ABANDON = "steam_backlog_enforcer.main.abandon"


def _pick(app_id: int, name: str, *, released: bool = True) -> dict[str, str | int]:
    entry: dict[str, str | int] = {
        "app_id": app_id,
        "game_name": name,
        "started_at": STARTED_AT,
    }
    if released:
        entry["released_at"] = STARTED_AT
    return entry


def _full_state() -> State:
    """Assignment plus two kept games: 3 allowed, the cap for 2 manual picks."""
    return State(
        current_app_id=1,
        current_game_name="Current",
        manual_picks=[_pick(2, "KeptA"), _pick(3, "KeptB")],
    )


def _config() -> Config:
    return Config(steam_api_key="k", steam_id="i", max_manual_picks=2)


def _output(mock_echo: MagicMock) -> str:
    return " ".join(str(c) for c in mock_echo.call_args_list)


class TestCmdPickKeep:
    def test_keeps_by_default(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[snap(5, "New")]),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            patch(f"{PKG}.hide_others_and_report"),
        ):
            cmd_pick(_config(), State(), [])
        assert mock_pick.call_args.kwargs["keep"] is True

    def test_replace_flag_replaces(self) -> None:
        with (
            patch(f"{PKG}.load_snapshot", return_value=[snap(5, "New")]),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            patch(f"{PKG}.hide_others_and_report"),
        ):
            cmd_pick(_config(), _full_state(), ["--replace"])
        assert mock_pick.call_args.kwargs["keep"] is False

    def test_unknown_argument_exits(self) -> None:
        with (
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.pick_next_game") as mock_pick,
            pytest.raises(SystemExit) as exc,
        ):
            cmd_pick(_config(), State(), ["--keep"])
        assert exc.value.code == 1
        assert "--replace" in _output(mock_echo)
        mock_pick.assert_not_called()

    def test_full_allowed_set_is_refused_before_the_list(self) -> None:
        # No scripted answers: being asked anything raises IndexError.
        with (
            use_prompter(FakePrompter()),
            patch(f"{PKG}._echo") as mock_echo,
            patch(f"{PKG}.load_snapshot") as mock_snapshot,
            patch(f"{PKG}.pick_next_game") as mock_pick,
            pytest.raises(SystemExit) as exc,
        ):
            cmd_pick(_config(), _full_state(), [])
        assert exc.value.code == 1
        mock_snapshot.assert_not_called()
        mock_pick.assert_not_called()
        output = _output(mock_echo)
        for name in ("Current (AppID=1)", "KeptA (AppID=2)", "KeptB (AppID=3)"):
            assert name in output
        assert "abandon-pick 2" in output
        assert "--replace" in output

    def test_one_below_the_cap_is_allowed(self) -> None:
        state = State(
            current_app_id=1, current_game_name="Current", manual_picks=[_pick(2, "A")]
        )
        with (
            patch(f"{PKG}.load_snapshot", return_value=[snap(5, "New")]),
            patch(f"{PKG}.load_hltb_cache", return_value={}),
            patch(f"{PKG}.pick_next_game") as mock_pick,
            patch(f"{PKG}.hide_others_and_report"),
        ):
            cmd_pick(_config(), state, [])
        mock_pick.assert_called_once()


class TestDispatch:
    def test_main_passes_the_argv_tail_to_pick(self) -> None:
        config, state = _config(), State()
        with (
            patch("sys.argv", ["sbe", "pick", "--replace"]),
            patch("steam_backlog_enforcer.main.cmd_pick") as mock_pick,
        ):
            assert _dispatch_extra_command("pick", config, state) is True
        mock_pick.assert_called_once_with(config, state, ["--replace"])


class TestReplaceParam:
    def test_defaults_to_keep(self) -> None:
        assert validate_params("pick", {}) == {"replace": 0}

    @pytest.mark.parametrize(("raw", "want"), [(True, 1), (False, 0), (1, 1)])
    def test_accepts_booleans(self, raw: object, want: int) -> None:
        assert validate_params("pick", {"replace": raw}) == {"replace": want}

    @pytest.mark.parametrize("raw", [2, "yes", None])
    def test_rejects_non_booleans(self, raw: object) -> None:
        with pytest.raises(InvalidParamsError):
            validate_params("pick", {"replace": raw})

    def test_is_an_unchecked_checkbox_in_the_catalog(self) -> None:
        [spec] = PARAMS["pick"]
        assert spec.to_json() == {
            "name": "replace",
            "label": "Replace current games (uninstalls them)",
            "type": "bool",
            "required": False,
            "default": 0,
            "help": spec.help,
        }


class TestPickJob:
    @pytest.mark.parametrize(("replace", "argv"), [(1, ["--replace"]), (0, [])])
    def test_replace_param_becomes_the_flag(
        self, replace: int, argv: list[str]
    ) -> None:
        with patch("steam_backlog_enforcer.jobs._registry.cmd_pick") as command:
            _registry.HANDLERS["pick"]({"replace": replace}, MagicMock(), MagicMock())
        assert command.call_args.args[2] == argv


class TestAbandonKeptGame:
    def test_a_kept_game_can_be_abandoned(self) -> None:
        state = State(
            current_app_id=1,
            current_game_name="Current",
            manual_picks=[_pick(2, "KeptA")],
        )
        with (
            patch(f"{_ABANDON}._echo"),
            patch("builtins.input", return_value="abandon KeptA"),
            patch.object(State, "save"),
            patch(f"{_ABANDON}.is_game_installed", return_value=True),
            patch(f"{_ABANDON}.uninstall_game", return_value=True) as uninstall,
        ):
            cmd_abandon_pick(Config(), state, ["2"])
        assert state.manual_picks == []
        assert state.current_app_id == 1
        uninstall.assert_called_once_with(2, "KeptA")

    def test_warning_names_the_assignment_that_survives(self) -> None:
        """Abandoning a kept game does not leave you without an assignment."""
        state = State(
            current_app_id=1,
            current_game_name="Current",
            manual_picks=[_pick(2, "KeptA")],
        )
        with (
            patch(f"{_ABANDON}._echo") as echo,
            patch("builtins.input", return_value="no"),
        ):
            cmd_abandon_pick(Config(), state, ["2"])
        output = " ".join(str(c) for c in echo.call_args_list)
        assert "no assigned game" not in output
        assert "Current stays assigned" in output
