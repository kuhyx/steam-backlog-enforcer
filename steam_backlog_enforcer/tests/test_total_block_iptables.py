"""Tests for the iptables half of the network block."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer._total_block_iptables import (
    _iptables_chain_intact,
    _load_cached_ips,
    _save_cached_ips,
    apply_total_block_iptables,
    remove_total_block_iptables,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.tests._total_block_paths import (
        Paths,
    )

PKG = "steam_backlog_enforcer._total_block_iptables"


class TestIpCache:
    """Tests for ip cache."""

    def test_load_no_file_returns_empty(self) -> None:
        """Test that load no file returns empty."""
        assert _load_cached_ips() == set()

    def test_save_then_load_round_trips(self) -> None:
        """Test that save then load round trips."""
        _save_cached_ips({"1.2.3.4", "5.6.7.8"})
        assert _load_cached_ips() == {"1.2.3.4", "5.6.7.8"}

    def test_load_malformed_json_returns_empty(self, total_block_paths: Paths) -> None:
        """Test that load malformed json returns empty."""
        total_block_paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.ip_cache_file.write_text("not json", encoding="utf-8")
        assert _load_cached_ips() == set()

    def test_load_non_list_json_returns_empty(self, total_block_paths: Paths) -> None:
        """Test that load non list json returns empty."""
        total_block_paths.ip_cache_file.parent.mkdir(parents=True, exist_ok=True)
        total_block_paths.ip_cache_file.write_text(
            json.dumps({"a": 1}), encoding="utf-8"
        )
        assert _load_cached_ips() == set()


# ──────────────────────────────────────────────────────────────
# iptables
# ──────────────────────────────────────────────────────────────


class TestIptablesChainIntact:
    """Tests for iptables chain intact."""

    def test_missing_chain_returns_false(self) -> None:
        """Test that missing chain returns false."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_missing_ip_returns_false(self) -> None:
        """Test that missing ip returns false."""
        listing = MagicMock(
            returncode=0,
            stdout="-N STEAM_TOTAL_BLOCK\n-A STEAM_TOTAL_BLOCK -d 9.9.9.9/32 -j DROP\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=listing):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_all_ips_present_and_hooked_returns_true(self) -> None:
        """Test that all ips present and hooked returns true."""
        listing = MagicMock(
            returncode=0,
            stdout=(
                "-N STEAM_TOTAL_BLOCK\n"
                "-A STEAM_TOTAL_BLOCK -d 1.2.3.4/32 -j DROP\n"
                "-A STEAM_TOTAL_BLOCK -d 5.6.7.8/32 -j DROP\n"
            ),
        )
        hook_check = MagicMock(returncode=0)
        with patch(f"{PKG}.subprocess.run", side_effect=[listing, hook_check]):
            assert _iptables_chain_intact({"1.2.3.4", "5.6.7.8"}) is True

    def test_ips_present_but_not_hooked_returns_false(self) -> None:
        """Test that ips present but not hooked returns false."""
        listing = MagicMock(
            returncode=0,
            stdout="-A STEAM_TOTAL_BLOCK -d 1.2.3.4/32 -j DROP\n",
        )
        hook_check = MagicMock(returncode=1)
        with patch(f"{PKG}.subprocess.run", side_effect=[listing, hook_check]):
            assert _iptables_chain_intact({"1.2.3.4"}) is False

    def test_malformed_trailing_d_flag_is_ignored(self) -> None:
        """A `-d` token with nothing after it (malformed/truncated rule
        line) must not index past the end of `parts`."""
        listing = MagicMock(
            returncode=0,
            stdout="-A STEAM_TOTAL_BLOCK -j DROP -d\n",
        )
        with patch(f"{PKG}.subprocess.run", return_value=listing):
            assert _iptables_chain_intact({"1.2.3.4"}) is False


class TestApplyTotalBlockIptables:
    """Tests for apply total block iptables."""

    def test_intact_chain_short_circuits(self) -> None:
        """Test that intact chain short circuits."""
        _save_cached_ips({"1.2.3.4"})
        with (
            patch(f"{PKG}._iptables_chain_intact", return_value=True),
            patch(f"{PKG}.subprocess.run") as mock_run,
        ):
            assert apply_total_block_iptables() is True
        mock_run.assert_not_called()

    def test_rebuilds_when_not_intact(self) -> None:
        """Test that rebuilds when not intact."""
        with (
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch(
                f"{PKG}.socket.getaddrinfo",
                return_value=[(None, None, None, None, ("9.9.9.9", 443))],
            ),
        ):
            assert apply_total_block_iptables() is True
        assert "9.9.9.9" in _load_cached_ips()

    def test_dns_failure_skips_that_domain(self) -> None:
        """Test that dns failure skips that domain."""
        import socket as real_socket

        with (
            patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)),
            patch(f"{PKG}.socket.getaddrinfo", side_effect=real_socket.gaierror),
        ):
            assert apply_total_block_iptables() is True
        assert _load_cached_ips() == set()

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with (
            patch(
                f"{PKG}.subprocess.run",
                side_effect=[MagicMock(returncode=0), OSError],
            ),
            patch(f"{PKG}.socket.getaddrinfo", return_value=[]),
        ):
            assert apply_total_block_iptables() is False

    def test_inserts_output_hook_when_missing(self) -> None:
        """Test that inserts output hook when missing."""

        def run_side_effect(cmd: list[str], **_kwargs: object) -> MagicMock:
            if "-C" in cmd:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0)

        with (
            patch(f"{PKG}.subprocess.run", side_effect=run_side_effect),
            patch(f"{PKG}.socket.getaddrinfo", return_value=[]),
        ):
            assert apply_total_block_iptables() is True


class TestRemoveTotalBlockIptables:
    """Tests for remove total block iptables."""

    def test_removes_chain_and_cache(self, total_block_paths: Paths) -> None:
        """Test that removes chain and cache."""
        _save_cached_ips({"1.2.3.4"})
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert remove_total_block_iptables() is True
        assert not total_block_paths.ip_cache_file.exists()

    def test_no_cache_file_is_fine(self) -> None:
        """Test that no cache file is fine."""
        with patch(f"{PKG}.subprocess.run", return_value=MagicMock(returncode=0)):
            assert remove_total_block_iptables() is True

    def test_subprocess_error_returns_false(self) -> None:
        """Test that subprocess error returns false."""
        with patch(f"{PKG}.subprocess.run", side_effect=OSError):
            assert remove_total_block_iptables() is False


# ──────────────────────────────────────────────────────────────
# Public lifecycle API
# ──────────────────────────────────────────────────────────────
