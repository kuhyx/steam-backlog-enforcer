"""Tests for steam_client_running: yes, no, or cannot tell."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer._steam_client import steam_client_running

RUN = "steam_backlog_enforcer._steam_client.subprocess.run"


@pytest.mark.parametrize(
    ("returncode", "expected"), [(0, True), (1, False), (2, None), (3, None)]
)
def test_pgrep_exit_code(returncode: int, *, expected: bool | None) -> None:
    """0 is running, 1 is not, anything else cannot tell."""
    with patch(RUN, return_value=MagicMock(returncode=returncode)):
        assert steam_client_running() is expected


def test_missing_pgrep_cannot_tell() -> None:
    """A missing pgrep cannot tell."""
    with patch(RUN, side_effect=FileNotFoundError):
        assert steam_client_running() is None
