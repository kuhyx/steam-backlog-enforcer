"""Store unblock / re-block on a hosts file that blocks both address families."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer import store_blocker
from steam_backlog_enforcer._hosts_protection import rewrite_hosts_lines
from steam_backlog_enforcer.config import BLOCKED_DOMAINS

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PKG = "steam_backlog_enforcer.store_blocker"
_HP = "steam_backlog_enforcer._hosts_protection"
_OTHER = "0.0.0.0 steamkarta.pl\n:: steamkarta.pl\n::1 localhost\n"


def _blocked() -> str:
    return _OTHER + "".join(f"0.0.0.0 {d}\n:: {d}\n" for d in BLOCKED_DOMAINS)


def _run(hosts: Path, fn: Callable[[], bool]) -> bool:
    """Call *fn* with /etc/hosts redirected to *hosts* and writes landing there."""

    def write(content: str) -> None:
        hosts.write_text(content, encoding="utf-8")

    with (
        patch(f"{PKG}.HOSTS_FILE", hosts),
        patch(f"{_HP}.HOSTS_FILE", hosts),
        patch(f"{_HP}._disable_hosts_protection"),
        patch(f"{_HP}._enable_hosts_protection"),
        patch(f"{_HP}._sudo_write_hosts", side_effect=write),
        patch(f"{PKG}._is_iptables_blocked", return_value=False),
        patch(f"{PKG}._block_store_iptables", return_value=True),
        patch(f"{PKG}._unblock_store_iptables", return_value=True),
        patch(f"{PKG}.flush_dns_cache"),
    ):
        return fn()


def test_unblock_comments_out_both_families(tmp_path: Path) -> None:
    """Every ``0.0.0.0`` and ``::`` store line is commented; others stay."""
    hosts = tmp_path / "hosts"
    hosts.write_text(_blocked(), encoding="utf-8")
    assert _run(hosts, store_blocker.unblock_store) is True
    text = hosts.read_text(encoding="utf-8")
    for domain in BLOCKED_DOMAINS:
        assert f"# 0.0.0.0 {domain}\n" in text
        assert f"# :: {domain}\n" in text
    assert text.startswith(_OTHER)
    assert not _run(hosts, store_blocker.hosts_blocks_store)


def test_ipv6_line_alone_counts_as_blocked(tmp_path: Path) -> None:
    """A live ``::`` line is a block even with the IPv4 line commented out."""
    hosts = tmp_path / "hosts"
    hosts.write_text("# 0.0.0.0 store.steampowered.com\n:: store.steampowered.com\n")
    assert _run(hosts, store_blocker.hosts_blocks_store) is True


def test_reblock_from_half_state_uncomments_both(tmp_path: Path) -> None:
    """IPv4 commented + IPv6 live is not "already blocked": both end up live."""
    hosts = tmp_path / "hosts"
    half = _OTHER + "".join(f"# 0.0.0.0 {d}\n:: {d}\n" for d in BLOCKED_DOMAINS)
    hosts.write_text(half, encoding="utf-8")
    assert _run(hosts, store_blocker.block_store) is True
    assert hosts.read_text(encoding="utf-8") == _blocked()


def test_reblock_after_unblock_round_trips(tmp_path: Path) -> None:
    """Unblock then re-block gives back the original file."""
    hosts = tmp_path / "hosts"
    hosts.write_text(_blocked(), encoding="utf-8")
    _run(hosts, store_blocker.unblock_store)
    _run(hosts, store_blocker.block_store)
    assert hosts.read_text(encoding="utf-8") == _blocked()


def test_failed_write_reports_failure_and_relocks(tmp_path: Path) -> None:
    """A failing ``sudo tee`` returns False and still re-locks /etc/hosts."""
    hosts = tmp_path / "hosts"
    hosts.write_text(_blocked(), encoding="utf-8")
    error = subprocess.CalledProcessError(1, ["tee"])
    with (
        patch(f"{_HP}.HOSTS_FILE", hosts),
        patch(f"{_HP}._disable_hosts_protection"),
        patch(f"{_HP}._enable_hosts_protection") as relock,
        patch(f"{_HP}._sudo_write_hosts", side_effect=error),
    ):
        ok = rewrite_hosts_lines(lambda line: f"# {line}", "done")
    assert ok is False
    relock.assert_called_once()
