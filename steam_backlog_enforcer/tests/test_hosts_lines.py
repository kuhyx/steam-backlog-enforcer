"""Tests for the /etc/hosts store-line matcher (both address families)."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer._hosts_lines import (
    comment_out_store_line,
    hosts_fully_blocks_store,
    is_live_store_line,
    live_store_lines,
    store_lines,
    uncomment_store_line,
)
from steam_backlog_enforcer.config import BLOCKED_DOMAINS

_STORE = "store.steampowered.com"


def _full_block() -> str:
    """The hosts text the hosts installer writes: both families per domain."""
    return "".join(f"0.0.0.0 {d}\n:: {d}\n" for d in BLOCKED_DOMAINS)


@pytest.mark.parametrize(
    "line",
    [
        f"0.0.0.0 {_STORE}",
        f":: {_STORE}",
        f"::\t{_STORE}",
        f"  0.0.0.0   {_STORE}  # inline note",
        f"0.0.0.0 other.example {_STORE}",
        "0.0.0.0 checkout.steampowered.com\n",
    ],
)
def test_live_store_lines(line: str) -> None:
    """Both sinkholes, any whitespace, multi-host lines and trailing notes."""
    assert is_live_store_line(line)


@pytest.mark.parametrize(
    "line",
    [
        f"# 0.0.0.0 {_STORE}",
        f"# :: {_STORE}",
        f"127.0.0.1 {_STORE}",
        f"::1 {_STORE}",
        f"::ffff:0.0.0.0 {_STORE}",
        "::1 localhost",
        "0.0.0.0 steamkarta.pl",
        ":: steamkarta.pl",
        f"0.0.0.0 x{_STORE}",
        f"0.0.0.0 {_STORE}.evil",
        f"# blocks {_STORE} below",
        "",
    ],
)
def test_not_live_store_lines(line: str) -> None:
    """Comments, other addresses, other hosts and substrings never match."""
    assert not is_live_store_line(line)


def test_comment_out_both_families() -> None:
    """Unblock comments out the IPv4 and the IPv6 line, keeping newlines."""
    assert comment_out_store_line(f"0.0.0.0 {_STORE}\n") == f"# 0.0.0.0 {_STORE}\n"
    assert comment_out_store_line(f":: {_STORE}\n") == f"# :: {_STORE}\n"
    assert comment_out_store_line(f":: {_STORE}") == f"# :: {_STORE}\n"


def test_comment_out_leaves_other_lines() -> None:
    """``steamkarta.pl`` and ``::1 localhost`` stay untouched."""
    for line in (":: steamkarta.pl\n", "::1 localhost\n", f"# :: {_STORE}\n"):
        assert comment_out_store_line(line) is None


def test_uncomment_both_families() -> None:
    """Re-block uncomments the IPv4 and the IPv6 line."""
    assert uncomment_store_line(f"# 0.0.0.0 {_STORE}\n") == f"0.0.0.0 {_STORE}\n"
    assert uncomment_store_line(f"# :: {_STORE}\n") == f":: {_STORE}\n"
    assert uncomment_store_line(f"#:: {_STORE}\n") == f":: {_STORE}\n"


def test_uncomment_leaves_prose_comments() -> None:
    """A comment that only mentions a store domain is not a block line."""
    for line in (
        f"# blocks {_STORE} below\n",
        "# 0.0.0.0 steamkarta.pl\n",
        f"0.0.0.0 {_STORE}\n",
    ):
        assert uncomment_store_line(line) is None


def test_live_store_lines_ipv6_left_behind() -> None:
    """The bug kuhy hit: IPv4 commented, IPv6 still live, counts as blocked."""
    text = f"# 0.0.0.0 {_STORE}\n:: {_STORE}\n0.0.0.0 steamkarta.pl\n"
    assert live_store_lines(text) == [f":: {_STORE}"]
    assert store_lines(text) == [f"# 0.0.0.0 {_STORE}", f":: {_STORE}"]


def test_fully_blocks_needs_both_families_for_every_domain() -> None:
    """Half a block (one family, or one domain missing) is not a full block."""
    full = _full_block()
    assert hosts_fully_blocks_store(full)
    assert not hosts_fully_blocks_store(full.replace(f"0.0.0.0 {_STORE}\n", ""))
    half = full.replace(f"0.0.0.0 {_STORE}\n", f"# 0.0.0.0 {_STORE}\n")
    assert not hosts_fully_blocks_store(half)
    assert not hosts_fully_blocks_store("")
