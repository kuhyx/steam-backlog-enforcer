"""Tests for the two-unit countdown label."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer._remaining import fmt_remaining

_H = 3600
_D = 24 * _H


@pytest.mark.parametrize(
    ("seconds", "label"),
    [
        (16 * _D, "2w 2d"),
        (2 * _D + 14 * _H, "2d 14h"),
        (2 * _H + 20 * 60, "2h 20m"),
        (5 * 60 + 7, "5m 7s"),
        (45, "45s"),
        (2 * _D, "2d 0h"),
        (60 * _D, "8w 4d"),
        (_H + 8 * 60 + 0.3, "1h 8m"),
        (59.2, "1m 0s"),
        (0, "0s"),
        (-5, "0s"),
    ],
)
def test_fmt_remaining(seconds: float, label: str) -> None:
    """Two largest units, rounded up, weeks down to seconds."""
    assert fmt_remaining(seconds) == label
