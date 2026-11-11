"""restore_store_block: the normal store block back, whatever else blocks it."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

from steam_backlog_enforcer.store_blocker import restore_store_block

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import Paths

PKG = "steam_backlog_enforcer.store_blocker"
# The normal section after an unblock, plus the total block's own live copy of
# the same domain: the live copy is what makes block_store() say "already
# blocked" and leave the commented lines alone.
HOSTS = (
    "127.0.0.1 localhost\n"
    "# Steam Store\n"
    "# 0.0.0.0 store.steampowered.com\n"
    "# 0.0.0.0 checkout.steampowered.com\n"
    "# BEGIN steam-backlog-enforcer total-block\n"
    "0.0.0.0 store.steampowered.com\n"
    "# END steam-backlog-enforcer total-block\n"
)


def _restore(paths: Paths, *, iptables: bool = True) -> tuple[bool, str]:
    paths.hosts_file.write_text(HOSTS, encoding="utf-8")

    def write(content: str) -> None:
        paths.hosts_file.write_text(content, encoding="utf-8")

    with (
        patch("steam_backlog_enforcer._hosts_protection.HOSTS_FILE", paths.hosts_file),
        patch("steam_backlog_enforcer._hosts_protection._disable_hosts_protection"),
        patch("steam_backlog_enforcer._hosts_protection._enable_hosts_protection"),
        patch(
            "steam_backlog_enforcer._hosts_protection._sudo_write_hosts",
            side_effect=write,
        ),
        patch(f"{PKG}._block_store_iptables", return_value=iptables) as chain,
        patch(f"{PKG}.flush_dns_cache") as flush,
    ):
        result = restore_store_block()
    chain.assert_called_once_with()
    flush.assert_called_once_with()
    return result, paths.hosts_file.read_text(encoding="utf-8")


class TestRestoreStoreBlock:
    """Unlike block_store it never stops at 'already blocked'."""

    def test_uncomments_the_normal_lines_despite_a_live_copy(
        self, total_block_paths: Paths
    ) -> None:
        """Test that the commented normal lines come back."""
        result, text = _restore(total_block_paths)
        assert result is True
        assert "\n0.0.0.0 store.steampowered.com\n0.0.0.0 checkout" in text
        assert "# 0.0.0.0 store.steampowered.com" not in text
        assert "# Steam Store\n" in text

    def test_hosts_alone_is_enough(self, total_block_paths: Paths) -> None:
        """Test that a failing iptables layer still counts as restored."""
        result, _ = _restore(total_block_paths, iptables=False)
        assert result is True

    def test_nothing_restored_is_false(self, total_block_paths: Paths) -> None:
        """Test that failing both layers is reported."""
        with patch(f"{PKG}._reblock_hosts", return_value=False):
            total_block_paths.hosts_file.write_text(HOSTS, encoding="utf-8")
            with (
                patch(f"{PKG}._block_store_iptables", return_value=False),
                patch(f"{PKG}.flush_dns_cache"),
            ):
                assert restore_store_block() is False
