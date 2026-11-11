"""itch.io exception (kuhy, 2026-11-11): domain table and /etc/hosts half."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._total_block_domains import (
    _ALL_TOTAL_BLOCK_DOMAINS,
    GAME_WEBSITE_DOMAINS,
    TOTAL_BLOCK_DOMAINS,
    TOTAL_BLOCK_EXEMPT_DOMAINS,
)
from steam_backlog_enforcer._total_block_hosts import (
    _HOSTS_BLOCK_BEGIN,
    _HOSTS_BLOCK_END,
    apply_total_block_hosts,
    refresh_total_block_hosts,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import Paths

PKG = "steam_backlog_enforcer._total_block_hosts"
STILL_BLOCKED = (
    "store.steampowered.com",
    "steamcommunity.com",
    "newgrounds.com",
    "www.newgrounds.com",
    "crazygames.com",
    "poki.com",
    "www.y8.com",
    "coolmathgames.com",
)
# What the live /etc/hosts section looked like before the exception.
OLD_SECTION = (
    _HOSTS_BLOCK_BEGIN
    + "".join(f"0.0.0.0 {d}\n" for d in (*STILL_BLOCKED, "itch.io", "www.itch.io"))
    + _HOSTS_BLOCK_END
)


class _Hosts:
    """Captures what the refresh would write, then plays it back as the file."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.writes: list[str] = []

    def write(self, content: str) -> None:
        """Stand-in for the sudo-tee write."""
        self.writes.append(content)
        self.paths.hosts_file.write_text(content, encoding="utf-8")


@pytest.fixture(name="hosts")
def _hosts_fixture(total_block_paths: Paths) -> _Hosts:
    """A tmp hosts file holding the pre-exception section between real lines."""
    total_block_paths.hosts_file.write_text(
        "127.0.0.1 localhost\n" + OLD_SECTION + "0.0.0.0 evil.example\n",
        encoding="utf-8",
    )
    return _Hosts(total_block_paths)


def _refresh(hosts: _Hosts) -> bool:
    with (
        patch(f"{PKG}._disable_hosts_protection"),
        patch(f"{PKG}._enable_hosts_protection"),
        patch(f"{PKG}._sudo_write_hosts", side_effect=hosts.write),
    ):
        return refresh_total_block_hosts()


class TestExemptTable:
    """The exception is one named constant the block lists cannot contain."""

    def test_confirmed_hosts_are_exempt(self) -> None:
        """Test that itch.io and the hosts butler talks to are exempt."""
        for host in ("itch.io", "www.itch.io", "api.itch.io"):
            assert host in TOTAL_BLOCK_EXEMPT_DOMAINS

    def test_exempt_never_in_block_list(self) -> None:
        """Test that no exempt domain is in the computed block list."""
        assert not set(TOTAL_BLOCK_EXEMPT_DOMAINS) & set(_ALL_TOTAL_BLOCK_DOMAINS)

    def test_exempt_wins_even_if_readded_to_source_lists(self) -> None:
        """Test that the filter, not the source list, enforces the exception."""
        assert "itch.io" not in GAME_WEBSITE_DOMAINS
        assert "itch.io" not in TOTAL_BLOCK_DOMAINS

    @pytest.mark.parametrize("domain", STILL_BLOCKED)
    def test_other_sites_still_blocked(self, domain: str) -> None:
        """Test that every other game site and Steam stay in the block list."""
        assert domain in _ALL_TOTAL_BLOCK_DOMAINS


class TestApplyOmitsItch:
    """A fresh block never writes itch.io."""

    def test_fresh_block_has_no_itch_line(self, total_block_paths: Paths) -> None:
        """Test that apply on a clean file writes the others but not itch.io."""
        total_block_paths.hosts_file.write_text("127.0.0.1 localhost\n")
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection"),
            patch(f"{PKG}._sudo_write_hosts") as write,
        ):
            assert apply_total_block_hosts() is True
        written = write.call_args.args[0]
        assert "itch.io" not in written
        assert "0.0.0.0 newgrounds.com\n" in written


class TestRefreshHosts:
    """refresh rewrites only the enforcer section of a live block."""

    def test_removes_itch_keeps_rest(self, hosts: _Hosts) -> None:
        """Test that itch lines go and every other line is untouched."""
        assert _refresh(hosts) is True
        new = hosts.paths.hosts_file.read_text(encoding="utf-8")
        assert "itch.io" not in new
        assert new.startswith("127.0.0.1 localhost\n" + _HOSTS_BLOCK_BEGIN)
        assert new.endswith(_HOSTS_BLOCK_END + "0.0.0.0 evil.example\n")
        for domain in STILL_BLOCKED:
            assert f"0.0.0.0 {domain}\n" in new

    def test_idempotent(self, hosts: _Hosts) -> None:
        """Test that a second refresh writes nothing."""
        assert _refresh(hosts) is True
        assert _refresh(hosts) is True
        assert len(hosts.writes) == 1

    def test_no_section_applies_block(self, total_block_paths: Paths) -> None:
        """Test that refresh on an active block with no section installs it."""
        total_block_paths.hosts_file.write_text("127.0.0.1 localhost\n")
        h = _Hosts(total_block_paths)
        assert _refresh(h) is True
        assert "newgrounds.com" in h.writes[0]

    def test_broken_section_fails_closed(self, total_block_paths: Paths) -> None:
        """Test that a BEGIN without END is left alone and reported."""
        total_block_paths.hosts_file.write_text(_HOSTS_BLOCK_BEGIN + "0.0.0.0 x\n")
        h = _Hosts(total_block_paths)
        assert _refresh(h) is False
        assert h.writes == []

    def test_unreadable_hosts_fails_closed(self, hosts: _Hosts) -> None:
        """Test that an unreadable hosts file is reported, not written."""
        hosts.paths.hosts_file.unlink()
        assert _refresh(hosts) is False
        assert hosts.writes == []

    def test_write_error_relocks_and_fails(self, hosts: _Hosts) -> None:
        """Test that a failed write returns False and re-enables protection."""
        before = hosts.paths.hosts_file.read_text(encoding="utf-8")
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as enable,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError),
        ):
            assert refresh_total_block_hosts() is False
        enable.assert_called_once()
        assert hosts.paths.hosts_file.read_text(encoding="utf-8") == before
