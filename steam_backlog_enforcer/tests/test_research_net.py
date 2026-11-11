"""Opening the network and the package for a research window."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from steam_backlog_enforcer import _research_net as net
from steam_backlog_enforcer.tests._research_helpers import make_record

if TYPE_CHECKING:
    from collections.abc import Iterator

PKG = "steam_backlog_enforcer._research_net"


class _World:
    """Records every collaborator call in order and answers from knobs."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.steam_installed = False
        self.chain_present = True
        self.store_blocked = True
        self.install_ok = True
        self.clock = 1000.0

    def step(self, name: str, *, result: object = True) -> object:
        """Log *name* and return *result*."""
        self.calls.append(name)
        return result


@pytest.fixture(name="world")
def _world() -> Iterator[_World]:
    """Patch the network/package collaborators with a call-recording world."""
    w = _World()

    def hosts(*, steam_open: bool = False) -> bool:
        return bool(w.step(f"hosts:{'open' if steam_open else 'full'}"))

    def install(package: str, *, masked_hooks: tuple[str, ...] = ()) -> bool:
        w.step(f"install:{package}:{','.join(masked_hooks)}")
        w.steam_installed = w.steam_installed or w.install_ok
        return w.install_ok

    with (
        patch(f"{PKG}.refresh_total_block_hosts", side_effect=hosts),
        patch(f"{PKG}.flush_dns_cache", side_effect=lambda: w.step("flush")),
        patch(f"{PKG}.hosts_blocks_store", side_effect=lambda: w.store_blocked),
        patch(f"{PKG}.unblock_store", side_effect=lambda: w.step("unblock-store")),
        patch(f"{PKG}.total_block_chain_exists", side_effect=lambda: w.chain_present),
        patch(
            f"{PKG}.release_total_block_iptables",
            side_effect=lambda: w.step("release-chain"),
        ),
        patch(f"{PKG}.is_steam_installed", side_effect=lambda: w.steam_installed),
        patch(f"{PKG}.install_package", side_effect=install),
        patch(f"{PKG}.monotonic", side_effect=lambda: w.clock),
    ):
        yield w


class TestReconcile:
    """One pass makes the network and the package match the open window."""

    def test_first_pass_opens_everything_in_order(self, world: _World) -> None:
        """Test that hosts, store, firewall, then the package are opened."""
        net.reconcile_open_window(make_record())
        assert world.calls == [
            "hosts:open",
            "flush",
            "unblock-store",
            "release-chain",
            "install:steam:guard-lib-block-steam-block.hook",
        ]

    def test_converged_pass_does_no_work(self, world: _World) -> None:
        """Test that a second pass over an open window forks nothing."""
        net.reconcile_open_window(make_record())
        world.calls.clear()
        world.store_blocked = False
        world.chain_present = False
        net.reconcile_open_window(make_record())
        assert world.calls == ["hosts:open"]

    def test_store_lines_that_come_back_are_undone(self, world: _World) -> None:
        """Test that the hourly hosts reinstall cannot re-close the store."""
        net.reconcile_open_window(make_record())
        world.calls.clear()
        world.store_blocked = True
        world.chain_present = False
        net.reconcile_open_window(make_record())
        assert world.calls == ["hosts:open", "unblock-store"]

    def test_chain_that_comes_back_is_dropped(self, world: _World) -> None:
        """Test that a rebuilt chain (e.g. by total-block-refresh) is removed."""
        net.reconcile_open_window(make_record())
        world.calls.clear()
        world.store_blocked = False
        world.chain_present = True
        net.reconcile_open_window(make_record())
        assert world.calls == ["hosts:open", "release-chain"]

    def test_a_restarted_daemon_redoes_the_one_time_release(
        self, world: _World
    ) -> None:
        """Test that the first pass of a fresh process is a full pass again."""
        net.reconcile_open_window(make_record())
        net.RELEASED.clear()
        world.calls.clear()
        net.reconcile_open_window(make_record())
        assert "unblock-store" in world.calls
        assert "flush" in world.calls

    def test_failed_hosts_refresh_is_retried_next_pass(self, world: _World) -> None:
        """Test that the one-time release is not marked done on failure."""
        with patch(f"{PKG}.refresh_total_block_hosts", return_value=False):
            net.reconcile_open_window(make_record())
        assert not net.RELEASED
        world.calls.clear()
        net.reconcile_open_window(make_record())
        assert world.calls[:3] == ["hosts:open", "flush", "unblock-store"]


class TestSteamPackage:
    """Reinstalling Steam, only when missing, never in a tight loop."""

    def test_installed_steam_is_left_alone(self, world: _World) -> None:
        """Test that an installed package is never reinstalled."""
        world.steam_installed = True
        assert net.ensure_steam_installed() is True
        assert not [c for c in world.calls if c.startswith("install")]

    def test_missing_steam_is_installed_without_the_block_hook(
        self, world: _World
    ) -> None:
        """Test that only the steam-block hook is masked for the install."""
        assert net.ensure_steam_installed() is True
        assert world.calls == ["install:steam:guard-lib-block-steam-block.hook"]

    def test_failed_install_backs_off(self, world: _World) -> None:
        """Test that a failure waits before the next attempt."""
        world.install_ok = False
        assert net.ensure_steam_installed() is False
        world.calls.clear()
        world.clock += net.RETRY_AFTER_SECONDS - 1
        assert net.ensure_steam_installed() is False
        assert world.calls == []
        world.clock += 2
        assert net.ensure_steam_installed() is False
        assert len(world.calls) == 1

    def test_pacman_database_lock_defers_the_install(self, world: _World) -> None:
        """Test that a running pacman transaction is not raced."""
        net.DB_LOCK_FILE.parent.mkdir(parents=True)
        net.DB_LOCK_FILE.write_text("", encoding="utf-8")
        assert net.ensure_steam_installed() is False
        assert world.calls == []

    def test_hook_name_follows_the_package_block_name(self) -> None:
        """Test that the masked hook is guard-lib's file for steam-block."""
        assert net.block_hook_name() == "guard-lib-block-steam-block.hook"
