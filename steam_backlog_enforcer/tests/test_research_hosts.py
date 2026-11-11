"""The research window's /etc/hosts half: Steam names open, game sites shut."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer._total_block_domains import (
    _ALL_TOTAL_BLOCK_DOMAINS,
    GAME_WEBSITE_DOMAINS,
    RESEARCH_BLOCKED_DOMAINS,
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
STEAM_NAMES = (
    "store.steampowered.com",
    "checkout.steampowered.com",
    "steamcommunity.com",
    "api.steampowered.com",
    "login.steampowered.com",
    "steamcontent.com",
    "steamstatic.com",
    "cdn.steamstatic.com",
)
GAME_SITES = ("newgrounds.com", "www.newgrounds.com", "poki.com", "www.y8.com")


class _Hosts:
    """Plays back what a refresh writes as the file's new content."""

    def __init__(self, paths: Paths, content: str) -> None:
        self.path = paths.hosts_file
        self.path.write_text(content, encoding="utf-8")
        self.writes = 0

    def write(self, content: str) -> None:
        """Stand-in for the sudo-tee write."""
        self.writes += 1
        self.path.write_text(content, encoding="utf-8")

    def text(self) -> str:
        """The file as it is now."""
        return self.path.read_text(encoding="utf-8")


@pytest.fixture(name="hosts")
def _hosts(total_block_paths: Paths) -> _Hosts:
    """A hosts file with the full section between unrelated lines."""
    full = _HOSTS_BLOCK_BEGIN + "".join(
        f"0.0.0.0 {d}\n" for d in _ALL_TOTAL_BLOCK_DOMAINS
    )
    return _Hosts(
        total_block_paths,
        "127.0.0.1 localhost\n" + full + _HOSTS_BLOCK_END + "0.0.0.0 evil.example\n",
    )


def _refresh(hosts: _Hosts, *, steam_open: bool) -> bool:
    with (
        patch(f"{PKG}._disable_hosts_protection"),
        patch(f"{PKG}._enable_hosts_protection"),
        patch(f"{PKG}._sudo_write_hosts", side_effect=hosts.write),
    ):
        return refresh_total_block_hosts(steam_open=steam_open)


class TestDomainTable:
    """The research list is the game sites, split off the same source."""

    def test_is_exactly_the_game_sites_with_www(self) -> None:
        """Test that no Steam name is in the research block list."""
        assert not set(RESEARCH_BLOCKED_DOMAINS) & set(TOTAL_BLOCK_DOMAINS)
        for site in GAME_SITES:
            assert site in RESEARCH_BLOCKED_DOMAINS
        assert set(GAME_WEBSITE_DOMAINS) <= set(RESEARCH_BLOCKED_DOMAINS)

    def test_union_with_steam_names_is_the_full_list(self) -> None:
        """Test that the split loses nothing and keeps the full-list order."""
        steam_part = [
            d for d in _ALL_TOTAL_BLOCK_DOMAINS if d not in RESEARCH_BLOCKED_DOMAINS
        ]
        assert set(steam_part) | set(RESEARCH_BLOCKED_DOMAINS) == set(
            _ALL_TOTAL_BLOCK_DOMAINS
        )

    def test_exempt_domains_stay_out(self) -> None:
        """Test that the itch exception holds in the research list too."""
        assert not set(RESEARCH_BLOCKED_DOMAINS) & set(TOTAL_BLOCK_EXEMPT_DOMAINS)


class TestOpenSection:
    """Opening swaps the section body and nothing else."""

    def test_open_drops_steam_names_and_keeps_game_sites(self, hosts: _Hosts) -> None:
        """Test that the open section null-routes only the game sites."""
        assert _refresh(hosts, steam_open=True) is True
        text = hosts.text()
        for name in STEAM_NAMES:
            assert f"0.0.0.0 {name}\n" not in text
        for site in GAME_SITES:
            assert f"0.0.0.0 {site}\n" in text

    def test_surrounding_lines_survive(self, hosts: _Hosts) -> None:
        """Test that only the text between the markers changed."""
        _refresh(hosts, steam_open=True)
        text = hosts.text()
        assert text.startswith("127.0.0.1 localhost\n" + _HOSTS_BLOCK_BEGIN)
        assert text.endswith(_HOSTS_BLOCK_END + "0.0.0.0 evil.example\n")

    def test_already_open_section_is_not_rewritten(self, hosts: _Hosts) -> None:
        """Test that a converged tick performs no write."""
        _refresh(hosts, steam_open=True)
        hosts.writes = 0
        assert _refresh(hosts, steam_open=True) is True
        assert hosts.writes == 0

    def test_missing_section_gets_the_open_variant(self, hosts: _Hosts) -> None:
        """Test that an absent section is created open, never full."""
        hosts.path.write_text("127.0.0.1 localhost\n", encoding="utf-8")
        assert _refresh(hosts, steam_open=True) is True
        text = hosts.text()
        assert _HOSTS_BLOCK_BEGIN in text
        assert "0.0.0.0 store.steampowered.com\n" not in text
        assert "0.0.0.0 newgrounds.com\n" in text

    def test_missing_section_without_trailing_newline(self, hosts: _Hosts) -> None:
        """Test that the new section starts on its own line."""
        hosts.path.write_text("127.0.0.1 localhost", encoding="utf-8")
        _refresh(hosts, steam_open=True)
        assert hosts.text().startswith("127.0.0.1 localhost\n" + _HOSTS_BLOCK_BEGIN)

    def test_unreadable_file_fails_closed(self, hosts: _Hosts) -> None:
        """Test that a missing hosts file is a False, not an exception."""
        hosts.path.unlink()
        assert _refresh(hosts, steam_open=True) is False

    def test_begin_without_end_is_left_alone(self, hosts: _Hosts) -> None:
        """Test that a damaged section is not guessed at."""
        hosts.path.write_text(_HOSTS_BLOCK_BEGIN + "0.0.0.0 x\n", encoding="utf-8")
        assert _refresh(hosts, steam_open=True) is False
        assert hosts.writes == 0

    @pytest.mark.usefixtures("hosts")
    def test_write_failure_is_false(self) -> None:
        """Test that a failing sudo tee is reported."""
        with (
            patch(f"{PKG}._disable_hosts_protection"),
            patch(f"{PKG}._enable_hosts_protection") as relock,
            patch(f"{PKG}._sudo_write_hosts", side_effect=OSError("tee")),
        ):
            assert refresh_total_block_hosts(steam_open=True) is False
        relock.assert_called_once()


class TestClose:
    """After the window the full list comes back through the ordinary refresh."""

    def test_full_refresh_restores_every_steam_name(self, hosts: _Hosts) -> None:
        """Test that refresh without steam_open re-null-routes Steam."""
        _refresh(hosts, steam_open=True)
        assert _refresh(hosts, steam_open=False) is True
        text = hosts.text()
        for name in STEAM_NAMES:
            assert f"0.0.0.0 {name}\n" in text

    def test_apply_still_leaves_a_present_section_alone(self, hosts: _Hosts) -> None:
        """Test that the cheap per-tick apply keeps its old contract."""
        _refresh(hosts, steam_open=True)
        hosts.writes = 0
        assert apply_total_block_hosts() is True
        assert hosts.writes == 0
