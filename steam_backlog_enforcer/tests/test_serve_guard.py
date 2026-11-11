"""Tests for _serve_guard's /proc parsing and port-ownership resolution.

Split from test_serve_guard_lifecycle.py to stay inside the 250-line file cap;
this half covers "who holds the port", that half covers "what to do about it".
Every test runs against a fake /proc built in tmp_path — none reads the host's
real process table, and none signals a real pid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._serve_guard import (
    _WILDCARD_V4,
    _conflicting_addresses,
    _hex_port,
    _hex_v4,
    _hex_v6,
    _listening_inodes,
    _pid_owns_inode,
)
from steam_backlog_enforcer.tests._fake_proc import (
    add_opaque_pid,
    add_pid,
    make_proc,
    patch_proc,
    tcp_row,
    write_net_tcp,
)

if TYPE_CHECKING:
    from pathlib import Path

_HOST = "127.0.0.1"
_PORT = 8000
_LOCAL_V4 = f"{_hex_v4(_HOST)}:{_hex_port(_PORT)}"


class TestHexRendering:
    """Tests for the /proc address column encoders."""

    def test_port_is_upper_hex(self) -> None:
        """Ports render as upper-case hex."""
        assert _hex_port(8000) == "1F40"

    def test_ipv4_is_little_endian(self) -> None:
        """IPv4 addresses render little-endian."""
        assert _hex_v4("127.0.0.1") == "0100007F"

    def test_ipv6_swaps_each_word(self) -> None:
        """IPv6 addresses render with each 32-bit word byte-swapped."""
        assert _hex_v6("::1") == "0" * 24 + "01000000"

    def test_v4_mapped_v6_is_rendered(self) -> None:
        """A v4-mapped v6 address ends in the v4 encoding."""
        mapped = _hex_v6("::ffff:127.0.0.1")
        assert mapped.endswith("0100007F")


class TestConflictingAddresses:
    """Tests for which listeners actually block a bind."""

    def test_includes_self_wildcard_and_mapped(self) -> None:
        """The host itself, the v4 wildcard and the v6 wildcard all conflict."""
        addrs = _conflicting_addresses(_HOST)
        assert _hex_v4(_HOST) in addrs
        assert _WILDCARD_V4 in addrs
        assert _hex_v6("::") in addrs

    def test_excludes_an_unrelated_interface(self) -> None:
        """A LAN address does not conflict with a loopback bind."""
        # A listener on a LAN address must never be reported as the owner of a
        # loopback bind; naming it would blame an innocent process.
        assert _hex_v4("192.168.1.5") not in _conflicting_addresses(_HOST)


class TestListeningInodes:
    """Tests for parsing /proc/net/tcp."""

    def test_finds_matching_listener(self, tmp_path: Path) -> None:
        """A listener on host:port is found."""
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, 4242)])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == {4242}

    def test_finds_wildcard_listener(self, tmp_path: Path) -> None:
        """A v4 wildcard listener on the port is found."""
        proc = make_proc(tmp_path)
        wildcard = f"{_WILDCARD_V4}:{_hex_port(_PORT)}"
        write_net_tcp(proc, [tcp_row(wildcard, 7)])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == {7}

    def test_finds_v6_wildcard_listener(self, tmp_path: Path) -> None:
        """A v6 wildcard listener in tcp6 is found."""
        # A dual-stack bind lives in tcp6 even when our bind is IPv4, which is
        # why both files are scanned.
        proc = make_proc(tmp_path)
        local = f"{_hex_v6('::')}:{_hex_port(_PORT)}"
        write_net_tcp(proc, [tcp_row(local, 9)], v6=True)
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == {9}

    def test_ignores_non_listening_state(self, tmp_path: Path) -> None:
        """An established connection is not a listener."""
        # 01 is ESTABLISHED: an outbound connection, not a bind.
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, 4242, state="01")])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == set()

    def test_ignores_other_port(self, tmp_path: Path) -> None:
        """A listener on another port is ignored."""
        proc = make_proc(tmp_path)
        other = f"{_hex_v4(_HOST)}:{_hex_port(9999)}"
        write_net_tcp(proc, [tcp_row(other, 4242)])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == set()

    def test_ignores_other_interface(self, tmp_path: Path) -> None:
        """A listener on another interface is ignored."""
        proc = make_proc(tmp_path)
        lan = f"{_hex_v4('192.168.1.5')}:{_hex_port(_PORT)}"
        write_net_tcp(proc, [tcp_row(lan, 4242)])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == set()

    def test_ignores_truncated_row(self, tmp_path: Path) -> None:
        """A row too short to parse is skipped."""
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [f"   0: {_LOCAL_V4} 0A 4242"])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == set()

    def test_ignores_non_numeric_inode(self, tmp_path: Path) -> None:
        """A row with a non-numeric inode is skipped."""
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, inode="notanumber")])
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == set()

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        """A missing tcp6 file does not hide tcp listeners."""
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, 4242)])
        (proc / "net" / "tcp6").unlink()
        with patch_proc(proc):
            assert _listening_inodes(_HOST, _PORT) == {4242}


class TestPidOwnsInode:
    """Tests for matching a socket inode to a process."""

    def test_matching_fd_is_found(self, tmp_path: Path) -> None:
        """A process holding the socket inode owns it."""
        proc = make_proc(tmp_path)
        pid_dir = add_pid(proc, 100, inodes=[1, 4242])
        assert _pid_owns_inode(pid_dir, {4242}) is True

    def test_unrelated_fds_do_not_match(self, tmp_path: Path) -> None:
        """Other fds do not make a process the owner."""
        proc = make_proc(tmp_path)
        pid_dir = add_pid(proc, 100, inodes=[1, 2])
        assert _pid_owns_inode(pid_dir, {4242}) is False

    def test_unreadable_fd_dir_is_not_an_owner(self, tmp_path: Path) -> None:
        """A process whose fds cannot be read is not an owner."""
        proc = make_proc(tmp_path)
        pid_dir = add_opaque_pid(proc, 100)
        assert _pid_owns_inode(pid_dir, {4242}) is False

    def test_unreadable_fds_are_skipped(self, tmp_path: Path) -> None:
        """fd entries that cannot be readlink()ed are skipped."""
        # A plain file in fd/ cannot be readlink()ed. Only unreadable entries
        # here, so the skip is exercised whatever order iterdir() returns —
        # a version of this that mixed in a real socket passed locally and
        # failed in CI, where the socket happened to be visited first.
        proc = make_proc(tmp_path)
        pid_dir = add_pid(proc, 100)
        for name in ("broken", "alsobroken"):
            (pid_dir / "fd" / name).write_text("", encoding="utf-8")
        assert _pid_owns_inode(pid_dir, {4242}) is False

    def test_an_unreadable_fd_does_not_abandon_the_process(
        self, tmp_path: Path
    ) -> None:
        """A broken fd does not stop the scan from finding the socket."""
        # The matching socket must still be found alongside a broken entry,
        # rather than the scan giving up on the process at the first OSError.
        proc = make_proc(tmp_path)
        pid_dir = add_pid(proc, 100, inodes=[4242])
        (pid_dir / "fd" / "broken").write_text("", encoding="utf-8")
        assert _pid_owns_inode(pid_dir, {4242}) is True
