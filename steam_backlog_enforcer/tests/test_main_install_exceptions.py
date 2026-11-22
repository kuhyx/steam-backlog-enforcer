"""``install`` offers approved exceptions next to the allowed games.

App 3347910 was whitelisted and ``install`` still answered "All allowed games
are already installed.": the candidates came from ``allowed_games`` alone.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._prompter import use_prompter
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.main import cmd_install
from steam_backlog_enforcer.tests._fake_prompter import FakePrompter

PKG = "steam_backlog_enforcer.main.install"
TGT = "steam_backlog_enforcer.main._install_target"
EXC = 588730
NAMES = {EXC: "Majotori"}


def _assigned() -> State:
    return State(current_app_id=1, current_game_name="Assigned")


def _run(
    state: State,
    *,
    exceptions: frozenset[int],
    installed: set[int],
    prompter: FakePrompter | None = None,
) -> tuple[FakePrompter, MagicMock, MagicMock]:
    """Run ``cmd_install``; returns the prompter, install_game and _echo mocks."""
    prompter = prompter or FakePrompter()
    with (
        use_prompter(prompter),
        patch(f"{TGT}.get_approved_exception_ids", return_value=exceptions),
        patch(
            f"{TGT}.load_owned_records",
            return_value=[{"app_id": a, "name": n} for a, n in NAMES.items()],
        ),
        patch(f"{PKG}.game_is_running", return_value=False),
        patch(f"{PKG}.is_game_fully_installed", side_effect=installed.__contains__),
        patch(f"{PKG}.install_game", return_value=True) as install,
        patch(f"{PKG}.fast_install_failure", return_value=None),
        patch(f"{PKG}._echo") as echo,
    ):
        cmd_install(Config(steam_id="i"), state)
    return prompter, install, echo


def _echoed(echo: MagicMock) -> list[str]:
    return [str(c) for c in echo.call_args_list]


class TestInstallOffersExceptions:
    """Every approved exception that is not fully installed is a candidate."""

    def test_uninstalled_exception_is_offered_next_to_allowed(self) -> None:
        """Both sources land in one prompt; picking the exception installs it."""
        prompter, install, _ = _run(
            _assigned(),
            exceptions=frozenset({EXC}),
            installed=set(),
            prompter=FakePrompter(choices=[str(EXC)]),
        )
        assert prompter.asked[0][1] == ["1", str(EXC)]
        assert install.call_args.args[:2] == (EXC, "Majotori")

    def test_only_uninstalled_exception_installs_without_prompt(self) -> None:
        """Allowed game installed, one exception left: no prompt, it installs."""
        prompter, install, _ = _run(
            _assigned(), exceptions=frozenset({EXC}), installed={1}
        )
        assert prompter.asked == []
        assert install.call_args.args[:2] == (EXC, "Majotori")

    def test_exception_that_is_also_allowed_is_offered_once(self) -> None:
        """The allowed entry wins; the id is not listed twice."""
        prompter, install, _ = _run(
            _assigned(), exceptions=frozenset({1}), installed=set()
        )
        assert prompter.asked == []
        assert install.call_args.args[:2] == (1, "Assigned")

    def test_everything_installed_keeps_the_old_message(self) -> None:
        """Allowed game and exception both installed: nothing to do."""
        _, install, echo = _run(
            _assigned(), exceptions=frozenset({EXC}), installed={1, EXC}
        )
        install.assert_not_called()
        assert any(
            "All allowed games are already installed." in c for c in _echoed(echo)
        )

    def test_no_assignment_but_an_exception_installs_it(self) -> None:
        """No allowed game is not "run scan first" while an exception exists."""
        _, install, echo = _run(State(), exceptions=frozenset({EXC}), installed=set())
        assert install.call_args.args[:2] == (EXC, "Majotori")
        assert not any("No game currently assigned" in c for c in _echoed(echo))

    def test_no_assignment_and_no_exceptions_says_scan(self) -> None:
        """Nothing from either source: the scan hint, as before."""
        _, install, echo = _run(State(), exceptions=frozenset(), installed=set())
        install.assert_not_called()
        assert any("No game currently assigned" in c for c in _echoed(echo))
