"""One https-only way to open a URL, shared by the network callers."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
import urllib.request

if TYPE_CHECKING:
    from collections.abc import Iterator
    from http.client import HTTPResponse


@contextlib.contextmanager
def open_https(
    url: str, *, timeout: float, user_agent: str | None = None
) -> Iterator[HTTPResponse]:
    """Open `url` (https only) with `user_agent`; a context manager."""
    if not url.startswith("https://"):
        msg = f"refusing a non-https URL: {url}"
        raise ValueError(msg)
    # No header when none is given: urllib then sends its own default agent.
    headers = {} if user_agent is None else {"User-Agent": user_agent}
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        yield response
