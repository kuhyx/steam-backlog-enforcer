"""The exceptions a fail-safe handler absorbs; anything else propagates.

No handler in the live enforcer catches ``Exception`` (kuhy's call, todo
9b9342ba). A handler that must outlive a failing input or op catches this
tuple instead:

* ``OSError``: files, sockets, ``/proc``, signals (incl. timeouts, a peer
  that hung up, ``ProcessLookupError``);
* ``ValueError``: malformed data, incl. ``json`` and Unicode decode errors;
* ``TypeError`` and ``LookupError``: a payload of the wrong shape;
* ``RuntimeError``: incl. ``RecursionError``, which leisure_watch has raised;
* ``subprocess.SubprocessError``: a helper that failed or timed out.

A programming bug outside it (``AttributeError``, ``NameError``, ...) is loud:
it reaches the thread's or the process's own error reporting.
"""

from __future__ import annotations

import subprocess
from typing import Final

FAIL_SAFE_ERRORS: Final[tuple[type[Exception], ...]] = (
    OSError,
    ValueError,
    TypeError,
    LookupError,
    RuntimeError,
    subprocess.SubprocessError,
)
