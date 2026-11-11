"""itch.io exception (kuhy, 2026-11-11): iptables half, against a fake chain."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._total_block_domains import NULL_ROUTE_IP
from steam_backlog_enforcer._total_block_iptables import (
    _load_cached_ips,
    _resolve_exempt_ips,
    _save_cached_ips,
    apply_total_block_iptables,
    refresh_total_block_iptables,
)

if TYPE_CHECKING:
    from collections.abc import Callable


PKG = "steam_backlog_enforcer._total_block_iptables"
ITCH_IP = "104.26.9.198"  # Cloudflare, shared by itch.io and api.itch.io
STEAM_IP = "23.1.1.1"
OTHER_CF_IP = "172.67.1.1"  # a still-blocked site


class FakeIptables:
    """A fake `iptables` that keeps one chain's rules in a list."""

    def __init__(self, ips: list[str], *, chain_exists: bool = True) -> None:
        self.rules = list(ips)
        self.chain_exists = chain_exists
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **_kw: object) -> MagicMock:
        """Answer one iptables call against the fake chain."""
        self.calls.append(cmd)
        args = (
            cmd[cmd.index("/usr/sbin/iptables") + 1 :]
            if "/usr/sbin/iptables" in cmd
            else cmd[2:]
        )
        verb = args[0]
        if verb == "-S":
            if not self.chain_exists:
                return MagicMock(returncode=1, stdout="")
            lines = ["-N STEAM_TOTAL_BLOCK"] + [
                f"-A STEAM_TOTAL_BLOCK -d {ip}/32 -j DROP" for ip in self.rules
            ]
            return MagicMock(returncode=0, stdout="\n".join(lines) + "\n")
        if verb == "-N":
            self.chain_exists = True
        elif verb == "-F":
            self.rules.clear()
        elif verb == "-A":
            self.rules.append(args[args.index("-d") + 1])
        elif verb == "-D" and args[1] != "OUTPUT":
            ip = args[args.index("-d") + 1].split("/")[0]
            if ip not in self.rules:
                return MagicMock(returncode=1)
            self.rules.remove(ip)
        return MagicMock(returncode=0)

    def verbs(self) -> list[str]:
        """The iptables verb (-S, -D, ...) of every call so far."""
        return [
            next(a for a in c if a.startswith("-") and len(a) == 2) for c in self.calls
        ]


def _dns(mapping: dict[str, list[str]]) -> Callable[..., list[tuple[object, ...]]]:
    def getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple[object, ...]]:
        """A getaddrinfo that answers from *mapping*, NXDOMAIN otherwise."""
        if host not in mapping:
            raise socket.gaierror
        return [(None, None, None, None, (ip, 443)) for ip in mapping[host]]

    return getaddrinfo


ITCH_DNS = {h: [ITCH_IP] for h in ("itch.io", "www.itch.io", "api.itch.io")}


def _run(fake: FakeIptables, dns: dict[str, list[str]]) -> bool:
    with (
        patch(f"{PKG}.subprocess.run", side_effect=fake.run),
        patch(f"{PKG}.socket.getaddrinfo", side_effect=_dns(dns)),
    ):
        return refresh_total_block_iptables()


class TestRefreshIptables:
    """Reconciling a live chain to the exception, without a gap."""

    def test_removes_itch_ip_keeps_rest(self) -> None:
        """Test that the shared Cloudflare IP leaves chain and cache."""
        _save_cached_ips({ITCH_IP, STEAM_IP, OTHER_CF_IP})
        fake = FakeIptables([ITCH_IP, STEAM_IP, OTHER_CF_IP])
        assert _run(fake, ITCH_DNS) is True
        assert sorted(fake.rules) == sorted([STEAM_IP, OTHER_CF_IP])
        assert _load_cached_ips() == {STEAM_IP, OTHER_CF_IP}

    def test_never_flushes_the_chain(self) -> None:
        """Test that other IPs stay dropped throughout (no -F, no -X)."""
        _save_cached_ips({ITCH_IP, STEAM_IP})
        fake = FakeIptables([ITCH_IP, STEAM_IP])
        _run(fake, ITCH_DNS)
        assert "-F" not in fake.verbs()
        assert "-X" not in fake.verbs()

    def test_idempotent(self) -> None:
        """Test that a second refresh changes nothing and runs no -D."""
        _save_cached_ips({ITCH_IP, STEAM_IP})
        fake = FakeIptables([ITCH_IP, STEAM_IP])
        assert _run(fake, ITCH_DNS) is True
        fake.calls.clear()
        assert _run(fake, ITCH_DNS) is True
        assert "-D" not in fake.verbs()
        assert fake.rules == [STEAM_IP]

    def test_exception_wins_on_shared_ip(self) -> None:
        """Test that an IP a blocked site also uses is still released."""
        _save_cached_ips({ITCH_IP})
        fake = FakeIptables([ITCH_IP])
        dns = {**ITCH_DNS, "newgrounds.com": [ITCH_IP]}
        assert _run(fake, dns) is True
        assert fake.rules == []

    def test_resumes_after_cache_was_saved_but_chain_not(self) -> None:
        """Test that a chain still holding the IP is cleaned although cache is not."""
        _save_cached_ips({STEAM_IP})
        fake = FakeIptables([ITCH_IP, STEAM_IP])
        assert _run(fake, ITCH_DNS) is True
        assert fake.rules == [STEAM_IP]

    def test_unresolvable_exempt_hosts_change_nothing(self) -> None:
        """Test that no DNS answer leaves cache and chain exactly as they were."""
        _save_cached_ips({ITCH_IP, STEAM_IP})
        fake = FakeIptables([ITCH_IP, STEAM_IP])
        assert _run(fake, {}) is False
        assert _run(fake, {"itch.io": [NULL_ROUTE_IP]}) is False  # still null-routed
        assert sorted(fake.rules) == sorted([ITCH_IP, STEAM_IP])
        assert _load_cached_ips() == {ITCH_IP, STEAM_IP}

    def test_delete_failure_reports_false(self) -> None:
        """Test that a rule that cannot be deleted is reported."""
        _save_cached_ips({ITCH_IP})
        fake = FakeIptables([ITCH_IP])
        real = fake.run

        def failing(cmd: list[str], **kw: object) -> MagicMock:
            if "-D" in cmd:
                return MagicMock(returncode=1)
            return real(cmd, **kw)

        with (
            patch(f"{PKG}.subprocess.run", side_effect=failing),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=_dns(ITCH_DNS)),
        ):
            assert refresh_total_block_iptables() is False

    def test_subprocess_error_reports_false(self) -> None:
        """Test that an iptables that cannot run fails closed."""
        _save_cached_ips({ITCH_IP})
        with (
            patch(f"{PKG}.subprocess.run", side_effect=OSError),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=_dns(ITCH_DNS)),
        ):
            assert refresh_total_block_iptables() is False

    def test_missing_chain_is_rebuilt_without_itch(self) -> None:
        """Test that a vanished chain comes back, minus the itch IP."""
        _save_cached_ips({ITCH_IP, STEAM_IP})
        fake = FakeIptables([], chain_exists=False)
        dns = {**ITCH_DNS, "store.steampowered.com": [STEAM_IP]}
        assert _run(fake, dns) is True
        assert fake.rules == [STEAM_IP]


class TestApplyExcludesItch:
    """A first build or rebuild never drops the exempt IPs."""

    def test_rebuild_skips_exempt_ip(self) -> None:
        """Test that a blocked site sharing itch's IP does not re-block it."""
        fake = FakeIptables([], chain_exists=False)
        dns = {**ITCH_DNS, "newgrounds.com": [ITCH_IP, OTHER_CF_IP]}
        with (
            patch(f"{PKG}.subprocess.run", side_effect=fake.run),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=_dns(dns)),
        ):
            assert apply_total_block_iptables() is True
        assert fake.rules == [OTHER_CF_IP]
        assert ITCH_IP not in _load_cached_ips()


class TestResolveExempt:
    """Only real, public answers count as an exempt IP."""

    def test_filters_null_and_private(self) -> None:
        """Test that 0.0.0.0, loopback and LAN answers are ignored."""
        dns = {"itch.io": [NULL_ROUTE_IP, "127.0.0.1", "192.168.1.1", ITCH_IP]}
        with patch(f"{PKG}.socket.getaddrinfo", side_effect=_dns(dns)):
            assert _resolve_exempt_ips() == {ITCH_IP}
