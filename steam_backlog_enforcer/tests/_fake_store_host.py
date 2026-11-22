"""A fake machine for the store checks: answers curl, getent, iptables, journalctl."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

from steam_backlog_enforcer import _store_verify as sv
from steam_backlog_enforcer.config import BLOCKED_DOMAINS

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

V4 = ".".join(["0"] * 4)  # The IPv4 sinkhole.


class FakeHost:
    """Answers the commands the checks run, from settable machine state."""

    def __init__(self, hosts: Path) -> None:
        """Start as a correctly unblocked, online machine."""
        self.hosts = hosts
        self.sleep = MagicMock()
        self.chain = False
        self.reachable = {sv.STORE_URL: True, sv.CONTROL_URL: True}
        self.resolves: dict[str, str] = dict.fromkeys(BLOCKED_DOMAINS, "1.2.3.4")
        self.calls: list[list[str]] = []

    def run(self, cmd: list[str], **_kw: object) -> MagicMock:
        """Fake ``subprocess.run``."""
        self.calls.append(cmd)
        out, rc = "", 0
        if cmd[0] == sv.CURL:
            rc = 0 if _next(self.reachable, cmd[-1]) else 7
            out = "200" if rc == 0 else "curl: (7) Failed to connect"
        elif cmd[0] == sv.GETENT:
            addr = _next(self.resolves, cmd[-1])
            out = f"{addr}      STREAM {cmd[-1]}\n" if addr else ""
            rc = 0 if addr else 2
        elif "-S" in cmd:
            rc = 0 if self.chain else 1
            out = "-N STEAM_ENFORCER\n-A STEAM_ENFORCER -d 1.2.3.4 -j DROP"
            out = out if self.chain else "iptables: No chain/target/match."
        elif cmd[0] == sv.JOURNALCTL:
            out = "\n".join(f"journal line {i}" for i in range(50))
        return MagicMock(returncode=rc, stdout=out, stderr="")


def _next(table: dict[str, Any], key: str) -> object:
    """The value for *key*; a list is a sequence of answers, one per call."""
    value = table[key]
    if isinstance(value, list):
        return value.pop(0) if len(value) > 1 else value[0]
    return value


def fake_host(tmp_path: Path) -> Iterator[FakeHost]:
    """Patch the checks onto a fresh :class:`FakeHost`; yield it."""
    hosts = tmp_path / "hosts"
    fake = FakeHost(hosts)
    hosts.write_text("127.0.0.1 localhost\n", encoding="utf-8")
    with (
        patch(f"{sv.__name__}.time.sleep") as fake.sleep,
        patch(f"{sv.__name__}.subprocess.run", side_effect=fake.run),
        patch(f"{sv.__name__}.HOSTS_FILE", hosts),
    ):
        yield fake
