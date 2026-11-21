"""The ``research_game`` / ``research_game_revoke`` control-socket ops."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _ctl_ops
from steam_backlog_enforcer import _research_game as rg
from steam_backlog_enforcer import _total_block_purge as purge
from steam_backlog_enforcer._ctl_protocol import INVALID_PARAMS, CtlError
from steam_backlog_enforcer._total_block_purge import _remove_steam_remnants
from steam_backlog_enforcer.tests._ctl_fixtures import make_ctx

APP = 4197610


def _approve(app_id: int = APP) -> None:
    """Approve."""
    rg.APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    rg.APPROVAL_FILE.write_text(json.dumps({"app_id": app_id}), encoding="utf-8")


def test_ops_are_allowlisted() -> None:
    """Ops are allowlisted."""
    assert "research_game" in _ctl_ops.OPS
    assert "research_game_revoke" in _ctl_ops.OPS


def test_add_takes_effect_at_once() -> None:
    """Add takes effect at once."""
    _approve()
    data = _ctl_ops.OPS["research_game"](make_ctx(), {"app_id": APP})
    assert data["app_id"] == APP
    assert rg.research_game_id() == APP


def test_add_refuses_other_app_than_the_file() -> None:
    """Add refuses other app than the file."""
    _approve(APP + 1)
    with pytest.raises(CtlError) as err:
        _ctl_ops.OPS["research_game"](make_ctx(), {"app_id": APP})
    assert err.value.code == INVALID_PARAMS
    assert rg.research_game_id() is None


def test_add_needs_an_int_app_id() -> None:
    """Add needs an int app id."""
    with pytest.raises(CtlError):
        _ctl_ops.OPS["research_game"](make_ctx(), {"app_id": "x"})


def test_revoke() -> None:
    """Revoke."""
    _approve()
    _ctl_ops.OPS["research_game"](make_ctx(), {"app_id": APP})
    assert _ctl_ops.OPS["research_game_revoke"](make_ctx(), {}) == {"app_id": APP}
    assert rg.research_game_id() is None


def test_total_block_purge_keeps_the_steam_folder() -> None:
    """Total block purge keeps the steam folder."""
    purge.STEAM_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _approve()
    rg.register(APP)
    with patch.object(purge, "_uninstall_proton_helpers", return_value=[]):
        purge.purge_steam_and_proton()
    assert purge.STEAM_DATA_DIR.is_dir()
    rg.revoke()
    assert str(purge.STEAM_DATA_DIR) in _remove_steam_remnants()
