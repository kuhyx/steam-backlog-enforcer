"""Store checks repeat until name resolution catches up with a hosts edit."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from steam_backlog_enforcer import _store_verify as sv
from steam_backlog_enforcer.config import BLOCKED_DOMAINS
from steam_backlog_enforcer.tests._fake_store_host import V4 as _V4
from steam_backlog_enforcer.tests._fake_store_host import FakeHost, fake_host

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STORE = "store.steampowered.com"


@pytest.fixture(name="host")
def fixture_host(tmp_path: Path) -> Iterator[FakeHost]:
    """A fake machine with an empty /etc/hosts."""
    yield from fake_host(tmp_path)


def test_unblock_https_settles_after_dns_reload(host: FakeHost) -> None:
    """Resolution fails for a moment after a hosts edit: retried, then ok."""
    host.reachable[sv.STORE_URL] = [False, False, True]
    report = sv.check_unblock()
    assert report.ok
    assert host.sleep.call_count == 2


def test_unblock_https_gives_up_after_attempts(host: FakeHost) -> None:
    """A store that stays unreachable fails after the last attempt."""
    host.reachable[sv.STORE_URL] = False
    assert sv.check_unblock().failed_check == "https"
    store_probes = [c for c in host.calls if c[-1] == sv.STORE_URL]
    assert len(store_probes) == sv.SETTLE_ATTEMPTS


def test_reblock_no_answer_counts_as_blocked(host: FakeHost) -> None:
    """systemd-resolved answers no address for a sinkholed name: blocked."""
    host.resolves = dict.fromkeys(BLOCKED_DOMAINS, "")
    host.reachable[sv.STORE_URL] = False
    report = sv.check_reblock()
    assert report.ok


def test_reblock_settles_stale_cache(host: FakeHost) -> None:
    """A cached real address and an answering store settle to blocked."""
    host.resolves = dict.fromkeys(BLOCKED_DOMAINS, _V4)
    host.resolves[_STORE] = ["2.18.70.115", _V4]
    host.reachable[sv.STORE_URL] = [True, False]
    assert sv.check_reblock().ok


@pytest.mark.usefixtures("host")
def test_verify_passing_first_time_runs_no_repair() -> None:
    """Checks that hold at once skip the repair and the evidence."""
    repair = MagicMock()
    report = sv.verify(sv.check_unblock, repair)
    assert report.ok
    repair.assert_not_called()
    assert not report.evidence


def test_unreadable_hosts_is_reported_not_raised(host: FakeHost) -> None:
    """A missing /etc/hosts does not crash the checks or the evidence."""
    host.hosts.unlink()
    host.chain = True
    report = sv.verify(sv.check_unblock)
    assert report.evidence["/etc/hosts store lines"] == ""
    assert report.failed_check == "iptables"
