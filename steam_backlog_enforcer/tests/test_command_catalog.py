"""Tests for ``_command_catalog`` and the shared ``_command_locks`` tables."""

from __future__ import annotations

from string import Formatter
from unittest.mock import patch

from steam_backlog_enforcer import _command_catalog, _command_locks
from steam_backlog_enforcer._command_params import PARAMS
from steam_backlog_enforcer._ctl_context import require_phrase
from steam_backlog_enforcer._friction import FRICTION, Friction, expected_phrase
from steam_backlog_enforcer._web_privileged import BUY_DLC_MINUTES
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs._specs import JobFlags
from steam_backlog_enforcer.main import _shared


class TestFrictionJson:
    """The contract's FrictionSpec."""

    def test_none(self) -> None:
        assert _command_catalog._friction_json(None) is None

    def test_without_countdown(self) -> None:
        assert _command_catalog._friction_json(Friction("do {x}")) == {
            "phrase_template": "do {x}"
        }

    def test_with_countdown(self) -> None:
        assert _command_catalog._friction_json(Friction("do it", 300)) == {
            "phrase_template": "do it",
            "countdown_seconds": 300,
        }


class TestSpec:
    """One CommandSpec object."""

    def test_view_uses_entry_flags_and_endpoint(self) -> None:
        entry = _command_catalog._view("backlog", "/api/x")
        spec = _command_catalog._spec("status", entry, "desc", None)
        assert spec["kind"] == "view"
        assert spec["view_endpoint"] == "/api/x"
        assert spec["mutating"] is False
        assert spec["params"] == []
        assert spec["friction"] is None
        assert spec["locked_reason"] is None

    def test_enforce_screen_is_cancellable(self) -> None:
        # Its demo is a job that loops until stopped; without the flag the UI
        # offered no Cancel for it.
        entry = _command_catalog.CATALOG["enforce"]
        spec = _command_catalog._spec("enforce", entry, "d", None)
        assert (spec["kind"], spec["cancellable"], spec["privileged"]) == (
            "screen",
            True,
            True,
        )

    def test_job_takes_flags_from_registry(self) -> None:
        flags = JobFlags(mutating=False, cancellable=True, privileged=True)
        with patch.dict(_command_catalog.JOB_FLAGS, {"scan": flags}):
            spec = _command_catalog._spec(
                "scan", _command_catalog._job("backlog"), "d", "why"
            )
        assert (spec["mutating"], spec["cancellable"], spec["privileged"]) == (
            False,
            True,
            True,
        )
        assert spec["locked_reason"] == "why"
        assert "view_endpoint" not in spec

    def test_job_without_registry_entry_falls_back_to_entry(self) -> None:
        entry = _command_catalog._Entry("system", "job", mutating=True)
        with patch.dict(_command_catalog.JOB_FLAGS, clear=True):
            spec = _command_catalog._spec("zzz", entry, "d", None)
        assert spec["mutating"] is True

    def test_params_and_friction_are_attached(self) -> None:
        spec = _command_catalog._spec(
            "block-gaming", _command_catalog._job("gaming"), "d", None
        )
        assert spec["params"] == [_command_catalog.PARAMS["block-gaming"][0].to_json()]
        assert spec["friction"] == {
            "phrase_template": "block all gaming for {days} days"
        }


class TestCommandSpecs:
    """The full payload."""

    def test_one_spec_per_catalog_entry(self) -> None:
        specs = _command_catalog.command_specs(Config(), State())
        assert [s["name"] for s in specs] == list(_command_catalog.CATALOG)
        assert all(
            isinstance(s["description"], str) and s["description"] for s in specs
        )

    def test_unconfigured_commands_report_a_lock(self) -> None:
        specs = {
            s["name"]: s for s in _command_catalog.command_specs(Config(), State())
        }
        assert specs["setup"]["locked_reason"] is None
        assert specs["scan"]["locked_reason"] == "Not configured. Run 'setup' first."

    def test_loads_config_and_state_when_omitted(self) -> None:
        with (
            patch.object(_command_catalog.Config, "load", return_value=Config()) as cfg,
            patch.object(_command_catalog.State, "load", return_value=State()) as st,
        ):
            _command_catalog.command_specs()
        cfg.assert_called_once()
        st.assert_called_once()


class TestCommandLocks:
    """The daemon and the CLI consult one table."""

    def test_cli_uses_the_same_tables(self) -> None:
        assert _shared._MANUAL_LOCK_EXEMPT_COMMANDS is (
            _command_locks._MANUAL_LOCK_EXEMPT_COMMANDS
        )
        assert _shared._TOTAL_BLOCK_EXEMPT_COMMANDS is (
            _command_locks._TOTAL_BLOCK_EXEMPT_COMMANDS
        )

    def test_total_block_is_stricter(self) -> None:
        assert _command_locks._TOTAL_BLOCK_EXEMPT_COMMANDS <= (
            _command_locks._MANUAL_LOCK_EXEMPT_COMMANDS
        )
        assert "gaming-reset" not in _command_locks._TOTAL_BLOCK_EXEMPT_COMMANDS


class TestPhrasesAreFillable:
    """Every phrase the UI shows can be completed and is the one checked."""

    def test_every_template_field_has_a_source(self) -> None:
        # Mirrors fillPhrase in web/src/commands/catalog.ts: a field is a
        # param, ``game_name`` from an ``app_id`` param, or ``count`` from
        # the installed list. Anything else leaves Run disabled forever.
        # The same two tables ``_spec`` builds each CommandSpec from.
        for name in _command_catalog.CATALOG:
            friction = FRICTION.get(name)
            if friction is None:
                continue
            params = {p.name for p in PARAMS.get(name, ())}
            derived = {"count"} | ({"game_name"} if "app_id" in params else set())
            template = friction.phrase_template
            fields = {f for _, f, _, _ in Formatter().parse(template) if f}
            assert fields <= params | derived, name

    def test_buy_dlc_phrase_is_the_unblock_the_daemon_checks(self) -> None:
        shown = expected_phrase("buy-dlc")
        assert shown == expected_phrase("unblock", minutes=BUY_DLC_MINUTES)
        assert shown is not None
        require_phrase("unblock", shown, minutes=BUY_DLC_MINUTES)
