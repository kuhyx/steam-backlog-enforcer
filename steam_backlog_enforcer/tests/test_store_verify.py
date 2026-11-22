"""Tests for the store unblock / re-block result checks."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _store_verify as sv
from steam_backlog_enforcer._store_check_report import NETWORK_DOWN, StoreVerifyError
from steam_backlog_enforcer._store_verify import _run as run_command
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


def _hosts(host: FakeHost, text: str) -> None:
    host.hosts.write_text(text, encoding="utf-8")


@pytest.mark.usefixtures("host")
def test_unblock_all_checks_pass() -> None:
    """A clean unblock passes and names no failed check."""
    report = sv.check_unblock()
    assert report.ok
    assert report.failed_check is None


def test_unblock_live_ipv6_line_fails_hosts(host: FakeHost) -> None:
    """The bug kuhy hit: a live ``::`` line fails the hosts check."""
    _hosts(host, f"# 0.0.0.0 {_STORE}\n:: {_STORE}\n")
    host.reachable[sv.STORE_URL] = False
    report = sv.check_unblock()
    assert not report.ok
    assert report.failed_check == "hosts"
    assert report.title == "Store unblock verification failed: hosts"


def test_unblock_chain_left_fails_iptables(host: FakeHost) -> None:
    """A store chain still present fails the iptables check."""
    host.chain = True
    assert sv.check_unblock().failed_check == "iptables"


def test_unblock_store_unreachable_fails_https(host: FakeHost) -> None:
    """Store down while steamcommunity.com answers: an unblock failure."""
    host.reachable[sv.STORE_URL] = False
    report = sv.check_unblock()
    assert report.failed_check == "https"
    assert not report.network_down


def test_unblock_both_unreachable_is_network_down(host: FakeHost) -> None:
    """Store and steamcommunity.com both unreachable: network down."""
    host.reachable = dict.fromkeys(host.reachable, False)
    report = sv.check_unblock()
    assert not report.ok
    assert report.failed_check == NETWORK_DOWN
    assert report.title == "Store unblock verification failed: network down"


def test_network_down_not_claimed_when_hosts_still_blocks(host: FakeHost) -> None:
    """A live hosts line is named even when everything is unreachable."""
    _hosts(host, f":: {_STORE}\n")
    host.reachable = dict.fromkeys(host.reachable, False)
    assert sv.check_unblock().failed_check == "hosts"


def test_reblock_passes_when_sinkholed(host: FakeHost) -> None:
    """Every domain on a sinkhole and the store unreachable: re-block ok."""
    host.resolves = {d: ("::" if i % 2 else _V4) for i, d in enumerate(BLOCKED_DOMAINS)}
    host.reachable[sv.STORE_URL] = False
    assert sv.check_reblock().ok


def test_reblock_leaking_domain_fails_dns(host: FakeHost) -> None:
    """One domain resolving to a real address fails the dns check."""
    host.resolves = dict.fromkeys(BLOCKED_DOMAINS, _V4)
    host.resolves[_STORE] = "23.1.1.1"
    host.reachable[sv.STORE_URL] = False
    report = sv.check_reblock()
    assert report.failed_check == "dns"
    assert _STORE in report.checks[0].detail


def test_reblock_store_answering_fails_https(host: FakeHost) -> None:
    """Sinkholed names but the store still answers: https fails."""
    host.resolves = dict.fromkeys(BLOCKED_DOMAINS, _V4)
    report = sv.check_reblock()
    assert report.failed_check == "https"
    assert report.title == "Store re-block verification failed: https"


def test_verify_repairs_once_then_passes(host: FakeHost) -> None:
    """A failing check triggers one repair; a fixed machine then passes."""
    host.chain = True

    def repair() -> None:
        host.chain = False

    report = sv.verify(sv.check_unblock, repair)
    assert report.ok
    assert report.repaired


def test_verify_gives_up_after_one_repair_with_evidence(host: FakeHost) -> None:
    """Still failing after the repair: the report carries every evidence part."""
    _hosts(host, f"# 0.0.0.0 {_STORE}\n:: {_STORE}\n0.0.0.0 steamkarta.pl\n")
    repair = MagicMock()
    report = sv.verify(sv.check_unblock, repair)
    repair.assert_called_once()
    assert not report.ok
    body = report.body()
    assert "Action: unblock" in body
    assert "- hosts: FAILED" in body
    assert "- iptables: ok" in body
    assert f":: {_STORE}" in body
    assert "steamkarta" not in body
    assert "iptables -S STEAM_ENFORCER" in body
    assert all(f"getent ahosts {d}" in body for d in BLOCKED_DOMAINS)
    assert "journal line 49" in body
    wire = report.to_wire()
    assert wire["title"] == "Store unblock verification failed: hosts"
    assert wire["check"] == "hosts"


def test_verify_without_repair_checks_once(host: FakeHost) -> None:
    """The re-block path has no repair: one check, then the evidence."""
    report = sv.verify(sv.check_reblock)
    assert not report.ok
    assert not report.repaired
    curls = [c for c in host.calls if c[0] == sv.CURL]
    assert len(curls) == sv.SETTLE_ATTEMPTS  # One check pass, settling once.


def test_run_survives_missing_binary() -> None:
    """A command that cannot start reports rc -1 instead of raising."""
    with patch(f"{sv.__name__}.subprocess.run", side_effect=OSError("nope")):
        assert run_command(["x"], 1) == (-1, "nope")


def test_error_carries_report(host: FakeHost) -> None:
    """StoreVerifyError keeps the report and names the check."""
    host.chain = True
    err = StoreVerifyError(sv.check_unblock())
    assert str(err) == "Store unblock failed: iptables"
    assert err.report.failed_check == "iptables"
