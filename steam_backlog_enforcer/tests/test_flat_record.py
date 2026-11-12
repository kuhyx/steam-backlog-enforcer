"""Nested groups behind one flat dict: keys, order and round trip."""

from __future__ import annotations

from dataclasses import dataclass, field

from steam_backlog_enforcer._flat_record import (
    flat_group,
    flat_keys,
    from_flat,
    to_flat,
)


@dataclass
class _Inner:
    depth: int = 0


@dataclass
class _Middle:
    name: str = ""
    inner: _Inner = field(default_factory=_Inner, metadata=flat_group(_Inner, "in_"))


@dataclass
class _Outer:
    first: int = 0
    middle: _Middle = field(
        default_factory=_Middle, metadata=flat_group(_Middle, "mid_")
    )
    last: int = 0


def test_nested_groups_flatten_with_joined_prefixes() -> None:
    """A group inside a group writes ``outer + inner`` prefixed keys in place."""
    record = _Outer(1, _Middle("m", _Inner(2)), 3)
    assert to_flat(record) == {
        "first": 1,
        "mid_name": "m",
        "mid_in_depth": 2,
        "last": 3,
    }
    assert list(to_flat(record)) == ["first", "mid_name", "mid_in_depth", "last"]
    assert flat_keys(_Outer) == {"first", "mid_name", "mid_in_depth", "last"}


def test_from_flat_round_trips_and_ignores_unknown_keys() -> None:
    """Unknown keys are dropped; missing ones take the defaults."""
    record = _Outer(1, _Middle("m", _Inner(2)), 3)
    assert from_flat(_Outer, to_flat(record) | {"stray": True}) == record
    assert from_flat(_Outer, {"mid_in_depth": 5}) == _Outer(
        middle=_Middle(inner=_Inner(5))
    )
