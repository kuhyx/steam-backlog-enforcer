"""The research window's firewall half: drop the chain, keep the IP memory."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._total_block_iptables import (
    IPTABLES_CHAIN,
    _load_cached_ips,
    _save_cached_ips,
    apply_total_block_iptables,
    release_total_block_iptables,
    total_block_chain_exists,
)

PKG = "steam_backlog_enforcer._total_block_iptables"
STEAM_IP = "23.1.1.1"
CDN_IP = "23.2.2.2"
SITE_IP = "172.67.1.1"


class FakeChain:
    """A fake iptables holding one chain, its rules and its OUTPUT hook."""

    def __init__(self, ips: list[str], *, exists: bool = True) -> None:
        self.rules = list(ips)
        self.exists = exists
        self.hooked = exists
        self.calls: list[list[str]] = []
        self.stuck = False

    def run(self, cmd: list[str], **_kw: object) -> MagicMock:
        """Answer one iptables call."""
        self.calls.append(cmd)
        args = cmd[2:]  # [sudo, iptables, <verb>, ...]
        verb = args[0]
        ok = MagicMock(returncode=0, stdout="")
        if verb == "-S":
            if not self.exists:
                return MagicMock(returncode=1, stdout="")
            lines = [f"-A {IPTABLES_CHAIN} -d {ip}/32 -j DROP" for ip in self.rules]
            return MagicMock(returncode=0, stdout="\n".join(lines) + "\n")
        if verb == "-C":
            return MagicMock(returncode=0 if self.hooked else 1)
        if verb == "-I":
            self.hooked = True
        elif verb == "-N":
            self.exists = True
        elif verb == "-D" and args[1] == "OUTPUT":
            self.hooked = False
        elif verb == "-F":
            self.rules.clear()
        elif verb == "-X" and not self.stuck:
            self.exists = False
        elif verb == "-A":
            self.rules.append(args[args.index("-d") + 1])
        return ok


def _dns(*names: str, ip: str = STEAM_IP) -> MagicMock:
    def getaddrinfo(host: str, *_a: object, **_k: object) -> list[tuple[object, ...]]:
        if host not in names:
            raise socket.gaierror
        return [(None, None, None, None, (ip, 443))]

    return MagicMock(side_effect=getaddrinfo)


class TestChainExists:
    """The cheap per-tick probe."""

    def test_present(self) -> None:
        """Test that a listed chain exists."""
        with patch(f"{PKG}.subprocess.run", side_effect=FakeChain([STEAM_IP]).run):
            assert total_block_chain_exists() is True

    def test_absent(self) -> None:
        """Test that a missing chain does not."""
        fake = FakeChain([], exists=False)
        with patch(f"{PKG}.subprocess.run", side_effect=fake.run):
            assert total_block_chain_exists() is False


class TestRelease:
    """Opening the window removes the chain but remembers what it dropped."""

    def test_chain_and_hook_are_gone_and_cache_survives(self) -> None:
        """Test that the IP cache is the memory the expiry rebuild needs."""
        _save_cached_ips({STEAM_IP, CDN_IP})
        fake = FakeChain([STEAM_IP, CDN_IP])
        with patch(f"{PKG}.subprocess.run", side_effect=fake.run):
            assert release_total_block_iptables() is True
        assert fake.exists is False
        assert fake.hooked is False
        assert _load_cached_ips() == {STEAM_IP, CDN_IP}

    def test_absent_chain_is_already_released(self) -> None:
        """Test that releasing twice is fine."""
        fake = FakeChain([], exists=False)
        with patch(f"{PKG}.subprocess.run", side_effect=fake.run):
            assert release_total_block_iptables() is True

    def test_chain_that_will_not_go_is_false(self) -> None:
        """Test that a failed delete is reported, not assumed."""
        fake = FakeChain([STEAM_IP])
        fake.stuck = True
        with patch(f"{PKG}.subprocess.run", side_effect=fake.run):
            assert release_total_block_iptables() is False

    def test_iptables_that_cannot_run_is_false(self) -> None:
        """Test that a missing iptables fails closed to 'not released'."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert release_total_block_iptables() is False


class TestRebuildAfterRelease:
    """At expiry the ordinary tick rebuilds the whole chain from the cache."""

    def test_cached_steam_ips_are_dropped_again(self) -> None:
        """Test that apply restores cached IPs plus freshly resolved ones."""
        _save_cached_ips({STEAM_IP, CDN_IP})
        fake = FakeChain([STEAM_IP, CDN_IP])
        with patch(f"{PKG}.subprocess.run", side_effect=fake.run):
            release_total_block_iptables()
        dns = _dns("store.steampowered.com", ip=SITE_IP)
        with (
            patch(f"{PKG}.subprocess.run", side_effect=fake.run),
            patch(f"{PKG}.socket.getaddrinfo", dns),
        ):
            assert apply_total_block_iptables() is True
        assert sorted(fake.rules) == sorted([STEAM_IP, CDN_IP, SITE_IP])
        assert fake.exists is True
        assert fake.hooked is True
