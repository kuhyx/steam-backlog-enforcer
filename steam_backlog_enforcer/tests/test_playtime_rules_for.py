"""Tests for resolving playtime rules from the config, production and demo."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from steam_backlog_enforcer._config_groups import PlaytimePolicy
from steam_backlog_enforcer._playtime_state import rules_for
from steam_backlog_enforcer.config import Config
from steam_backlog_enforcer.tests._no_workout_http import fixed_budget


class TestRulesFor:
    """rules_for maps the config and mode onto PlaytimeRules."""

    def test_production_budget_comes_from_the_resolver(self) -> None:
        """Production takes its budget from the budget resolver."""
        with fixed_budget(100.0):
            rules = rules_for(Config(), demo=False)
        assert rules.budget_seconds == 100.0
        assert rules.demo is False

    def test_demo_budget_is_sixty_seconds(self) -> None:
        """Demo always gets a 60 s budget."""
        rules = rules_for(Config(), demo=True)
        assert rules.budget_seconds == 60.0
        assert rules.demo is True

    def test_demo_warns_in_seconds_not_minutes(self) -> None:
        """Demo warning points are seconds, production ones minutes."""
        assert rules_for(Config(), demo=True).warn_at == (30, 10)
        assert rules_for(Config(), demo=False).warn_at == (3600, 1800, 600, 300)

    def test_demo_escalates_to_sigkill_sooner(self) -> None:
        """Demo escalates to SIGKILL after 10 s, production after 30 s."""
        assert rules_for(Config(), demo=True).sigkill_after == 10.0
        assert rules_for(Config(), demo=False).sigkill_after == 30.0

    def test_launcher_toggle_is_carried_through(self) -> None:
        """count_launcher_processes becomes count_launchers."""
        assert (
            rules_for(
                Config(playtime=PlaytimePolicy(count_launcher_processes=False)),
                demo=False,
            ).count_launchers
            is False
        )
        assert (
            rules_for(
                Config(playtime=PlaytimePolicy(count_launcher_processes=True)),
                demo=False,
            ).count_launchers
            is True
        )

    def test_enforcement_toggle_is_carried_through(self) -> None:
        """playtime_enforcement off becomes enforcement off."""
        assert (
            rules_for(
                Config(playtime=PlaytimePolicy(playtime_enforcement=False)), demo=False
            ).enforcement
            is False
        )

    def test_demo_uses_the_same_qualifying_predicate(self) -> None:
        """Demo may differ in budget and warnings only."""
        prod = rules_for(
            Config(playtime=PlaytimePolicy(count_launcher_processes=True)), demo=False
        )
        demo = rules_for(
            Config(playtime=PlaytimePolicy(count_launcher_processes=True)), demo=True
        )
        assert prod.count_launchers == demo.count_launchers

    def test_rules_are_frozen(self) -> None:
        """Frozen so the decision helpers stay pure and cheap to reason about."""
        rules = rules_for(Config(), demo=False)
        with pytest.raises(FrozenInstanceError):
            rules.budget_seconds = 1.0
