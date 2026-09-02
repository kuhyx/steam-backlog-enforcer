"""Tests for who a billed tick belongs to — 100% branch coverage.

Split from ``test_playtime_procs`` at the 250-line cap. This file owns the
attribution dimension: which PIDs qualify, and which single game a tick is
credited to. ``test_playtime_procs`` keeps the /proc plumbing.
"""

from __future__ import annotations

from unittest.mock import patch

from steam_backlog_enforcer._counted_procs import CountedProcess
from steam_backlog_enforcer._playtime_procs import attributed_key, qualifying_pids
from steam_backlog_enforcer._playtime_state import rules_for
from steam_backlog_enforcer.config import Config


class TestQualifyingPids:
    """`qualifying_pids` returns pid -> attribution key, not a bare pid set."""

    def test_steam_games_only_when_launchers_are_off(self) -> None:
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={5: 440, 6: 0},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names"
            ) as mock_comm,
        ):
            assert qualifying_pids(rules) == {5: "app:440"}
        mock_comm.assert_not_called()

    def test_steam_client_appid_zero_does_not_count(self) -> None:
        """Browsing the store is not gaming."""
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={9: 0},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(),
            ),
        ):
            assert qualifying_pids(rules) == {}

    def test_unions_launchers_from_both_scanners(self) -> None:
        rules = rules_for(Config(count_launcher_processes=True), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={5: 440},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={7: "heroic"},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={8: "lutris"},
            ),
        ):
            assert qualifying_pids(rules) == {
                5: "app:440",
                7: "launcher:heroic",
                8: "launcher:lutris",
            }

    def test_counted_processes_bill_even_with_launchers_off(self) -> None:
        """The user's own list is not gated on the launcher switch.

        Turning launcher counting off because a launcher idles in the tray must
        not silently stop billing a game the user explicitly listed.
        """
        rules = rules_for(Config(count_launcher_processes=False), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(
                    CountedProcess(
                        id="osu-lazer", label="osu!lazer", names=frozenset({"osu!"})
                    ),
                ),
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={11: "osu!"},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={},
            ),
        ):
            assert qualifying_pids(rules) == {11: "proc:osu-lazer"}

    def test_steam_attribution_wins_over_a_name_match(self) -> None:
        """A Steam game keeps its app key even if its comm matches a launcher."""
        rules = rules_for(Config(count_launcher_processes=True), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={7: 440},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={7: "heroic"},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={},
            ),
        ):
            assert qualifying_pids(rules) == {7: "app:440"}

    def test_a_name_outside_the_map_is_skipped(self) -> None:
        """Unreachable in production; a KeyError in the enforce loop is not."""
        rules = rules_for(Config(count_launcher_processes=True), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.load_counted_processes",
                return_value=(),
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={12: "not-a-launcher"},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={},
            ),
        ):
            assert qualifying_pids(rules) == {}

    def test_no_processes_at_all(self) -> None:
        rules = rules_for(Config(), demo=False)
        with (
            patch(
                "steam_backlog_enforcer._playtime_procs.get_running_steam_game_pids",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_process_names",
                return_value={},
            ),
            patch(
                "steam_backlog_enforcer._playtime_procs.get_pids_by_cmdline_names",
                return_value={},
            ),
        ):
            assert qualifying_pids(rules) == {}


class TestAttributedKey:
    """Deciding which single game a tick belongs to."""

    def test_falls_back_to_the_only_game_running(self) -> None:
        assert attributed_key({7: "app:440", 8: "app:440"}) == "app:440"

    def test_two_games_is_unattributable(self) -> None:
        # There is no honest way to say which one earned the tick, so the
        # tick still bills but the gap shows up as Unattributed rather than
        # being charged to a guess.
        assert attributed_key({7: "app:440", 8: "app:1"}) == ""

    def test_nothing_qualifying(self) -> None:
        assert attributed_key({}) == ""
