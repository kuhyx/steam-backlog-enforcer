"""Reading leetcode-guard's ledger for today's accepted submissions.

Reading and verifying is the shared reader in ``earned_time`` (kuhyx/utils),
the same one screen-locker uses; ``test_leetcode_ledger.py`` pins its HMAC
canonicalisation to a fixed vector. gatelock itself is not imported: it pulls
in tkinter, and this daemon runs headless as root.

Since earned_time 0.18.0 only today's signed ``leetcode`` ``charge`` (the day
paid in full) earns. A bare ``credit`` earns only when ``gate_off`` is true (a
free or sick day), and a ``seen`` entry is first-run seeding worth zero.

The solve time is ``detail["submitted_at"]``, LeetCode's own timestamp, not the
entry's ``day``: ``day`` is stamped by the *harvesting* run, so a problem
solved at 23:50 and harvested the next morning carries the next day's key.

Every unreadable state returns ``None``, never ``False``. "Cannot check" is not
"not solved", and only one of the two is worth waking the user about.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final

import earned_time

logger = logging.getLogger(__name__)

# The key every locker signs its state with. Root-owned, world-readable.
HMAC_KEY_FILE: Final = Path("/etc/workout-locker/hmac.key")


def read_ledger_solved_today(path: Path, *, gate_off: bool = False) -> bool | None:
    """Read leetcode-guard's ledger: was today paid in full?

    Args:
        path: The ledger file.
        gate_off: Whether the gate stands down today (asked live). Only then
            does one verified solve earn; otherwise only the signed charge
            that covers the day's whole price does (earned_time 0.18.0).

    Returns:
        True or False when the ledger could be read and verified, ``None`` when
        it could not -- which is never "nothing was solved".
    """
    return earned_time.done_today(
        earned_time.LEETCODE, path, HMAC_KEY_FILE, gate_off=gate_off
    )
