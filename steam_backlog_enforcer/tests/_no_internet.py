"""Autouse guard: tests resolve loopback names only, never the internet.

Without it a test that walked into an unpatched HLTB lookup (the poll-count
backfill after a pick, for example) made real HTTPS requests to
howlongtobeat.com: ~1.5 s per test, and a result that depended on the network
and on HLTB's live data. Every outbound call starts with ``getaddrinfo``
(requests/urllib3 directly, aiohttp through asyncio's thread resolver), so
refusing non-loopback hosts there turns each leak into the same fast failure
the package already handles when the machine is offline.

Tests that need a resolver patch ``socket.getaddrinfo`` themselves; their patch
sits on top of this one for the test's duration.

Split out of ``conftest.py`` to keep every file inside the 250-line cap;
``conftest`` imports the fixture by name, which is what registers it.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_REAL_GETADDRINFO = socket.getaddrinfo
_LOCAL_NAMES = frozenset({"", "localhost"})


def is_local_host(host: bytes | str | None) -> bool:
    """Whether *host* names this machine (loopback, unspecified, or None)."""
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    name = str(host)
    if name.lower() in _LOCAL_NAMES:
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def local_only_getaddrinfo(
    host: bytes | str | None,
    port: bytes | str | int | None,
    *args: int,
    **kwargs: int,
) -> list[tuple[object, ...]]:
    """``socket.getaddrinfo`` for loopback hosts; offline for anything else."""
    if not is_local_host(host):
        msg = f"tests may not resolve {host!r}: patch the network call instead"
        raise socket.gaierror(socket.EAI_NONAME, msg)
    return list(_REAL_GETADDRINFO(host, port, *args, **kwargs))


@pytest.fixture(autouse=True)
def _no_internet() -> Iterator[None]:
    """Refuse DNS for non-loopback hosts for the whole test."""
    with patch("socket.getaddrinfo", local_only_getaddrinfo):
        yield
