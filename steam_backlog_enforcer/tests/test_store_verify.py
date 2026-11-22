"""Tests for the store unblock / re-block result checks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from steam_backlog_enforcer import _store_verify as sv
from steam_backlog_enforcer._store_verify import _run as run_command
from steam_backlog_enforcer.config import BLOCKED_DOMAINS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_STORE = "store.steampowered.com"
_V4 = ".".join(["0"] * 4)  # The IPv4 sinkhole.


class FakeHost:
    """Answers the commands the checks run, from settable machine state."""

    def __init__(self, hosts: Path) -> None:
        """Start as a correctly unblocked, online machine."""
        self.hosts = hosts
        self.sleep = MagicMock()
        self.chain = False
        self.reachable = {sv.STORE_URL: True, sv.CONTROL_URL: True}
        self.resolves: dict[str, str] = dict.fromkeys(BLOCKED_DOMAINS, "1.2.3.4")
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **_kw: object) -> MagicMock:
        """Fake ``subprocess.run``."""
        self.calls.append(cmd)
        out, rc = "", 0
        if cmd[0] == sv.CURL:
            rc = 0 if _next(self.reachable, cmd[-1]) else 7
            out = "200" if rc == 0 else "curl: (7) Failed to connect"
        elif cmd[0] == sv.GETENT:
            addr = _next(self.resolves, cmd[-1])
            out = f"{addr}      STREAM {cmd[-1]}\n" if addr else ""
            rc = 0 if addr else 2
        elif "-S" in cmd:
            rc = 0 if self.chain else 1
            out = "-N STEAM_ENFORCER\n-A STEAM_ENFORCER -d 1.2.3.4 -j DROP"
            out = out if self.chain else "iptables: No chain/target/match."
        elif cmd[0] == sv.JOURNALCTL:
            out = "\n".join(f"journal line {i}" for i in range(50))
        return MagicMock(returncode=rc, stdout=out, stderr="")


def _next(table: dict[str, Any], key: str) -> object:
    """The value for *key*; a list is a sequence of answers, one per call."""
    value = table[key]
    if isinstance(value, list):
        return value.pop(0) if len(value) > 1 else value[0]
    return value


@pytest.fixture(name="host")
def fixture_host(tmp_path: Path) -> Iterator[FakeHost]:
    """A fake machine with an empty /etc/hosts."""
    hosts = tmp_path / "hosts"
    fake = FakeHost(hosts)
    hosts.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    with (
        patch(f"{sv.__name__}.time.sleep") as fake.sleep,
        patch(f"{sv.__name__}.subprocess.run", side_effect=fake.run),
        patch(f"{sv.__name__}.HOSTS_FILE", hosts),
    ):
        yield fake


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
    assert report.failed_check == sv.NETWORK_DOWN
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
    err = sv.StoreVerifyError(sv.check_unblock())
    assert str(err) == "Store unblock failed: iptables"
    assert err.report.failed_check == "iptables"


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
