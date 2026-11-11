"""Tests for _serve_guard's port-owner resolution and serve-process check.

Split from test_serve_guard.py to stay inside the 250-line file cap. Every test
runs against a fake /proc built in tmp_path; none reads the host's real process
table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._serve_guard import (
    _hex_port,
    _hex_v4,
    find_port_owner,
    is_our_server,
    read_cmdline,
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


class TestFindPortOwner:
    """Tests for end-to-end owner resolution."""

    def test_no_listener_returns_none(self, tmp_path: Path) -> None:
        """A free port has no owner."""
        proc = make_proc(tmp_path)
        with patch_proc(proc):
            assert find_port_owner(_HOST, _PORT) is None

    def test_resolves_the_listening_pid(self, tmp_path: Path) -> None:
        """The pid holding the listening inode is the owner."""
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, 4242)])
        add_pid(proc, 100, inodes=[9])
        add_pid(proc, 200, inodes=[4242])
        with patch_proc(proc):
            assert find_port_owner(_HOST, _PORT) == 200

    def test_uninspectable_owner_resolves_to_none(self, tmp_path: Path) -> None:
        """An owner whose fds cannot be read resolves to None."""
        # Another user's listener: occupied, but not attributable. Callers must
        # read this as "cannot identify", never as "free".
        proc = make_proc(tmp_path)
        write_net_tcp(proc, [tcp_row(_LOCAL_V4, 4242)])
        add_opaque_pid(proc, 100)
        with patch_proc(proc):
            assert find_port_owner(_HOST, _PORT) is None


class TestReadCmdline:
    """Tests for argv reading."""

    def test_returns_argv(self, tmp_path: Path) -> None:
        """read_cmdline returns the process argv."""
        proc = make_proc(tmp_path)
        add_pid(proc, 100, cmdline=["python", "-m", "steam_backlog_enforcer.main"])
        with patch_proc(proc):
            assert read_cmdline(100)[0] == "python"

    def test_missing_process_is_empty(self, tmp_path: Path) -> None:
        """A missing pid reads as an empty argv."""
        proc = make_proc(tmp_path)
        with patch_proc(proc):
            assert read_cmdline(4321) == []


class TestIsOurServer:
    """Tests for recognising one of our own serve processes."""

    def test_our_serve_process_matches(self, tmp_path: Path) -> None:
        """Our main module running serve is recognised."""
        proc = make_proc(tmp_path)
        add_pid(
            proc, 100, cmdline=["python", "-m", "steam_backlog_enforcer.main", "serve"]
        )
        with patch_proc(proc):
            assert is_our_server(100) is True

    def test_other_subcommand_does_not_match(self, tmp_path: Path) -> None:
        """Our main module running another subcommand is not."""
        proc = make_proc(tmp_path)
        add_pid(
            proc, 100, cmdline=["python", "-m", "steam_backlog_enforcer.main", "status"]
        )
        with patch_proc(proc):
            assert is_our_server(100) is False

    def test_unrelated_process_does_not_match(self, tmp_path: Path) -> None:
        """A foreign program is not ours."""
        proc = make_proc(tmp_path)
        add_pid(proc, 100, cmdline=["nginx", "serve"])
        with patch_proc(proc):
            assert is_our_server(100) is False
