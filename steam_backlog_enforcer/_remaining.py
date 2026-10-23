"""Countdown label for time left on a lock, e.g. "2w 2d" or "1h 8m"."""

from __future__ import annotations

import math

# Largest first; weeks are the top unit because months vary in length.
_UNITS = (("w", 7 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1))


def fmt_remaining(seconds: float) -> str:
    """Format *seconds* as its two largest units, down to one second.

    Rounds up, so the label reads "0s" only once the time is actually up.

    Args:
        seconds: Time left; negative counts as zero.

    Returns:
        A label such as "2w 2d", "2d 14h", "2h 20m", "5m 7s" or "45s".
    """
    left = max(0, math.ceil(seconds))
    for i, (name, size) in enumerate(_UNITS[:-1]):
        if left >= size:
            sub_name, sub_size = _UNITS[i + 1]
            return f"{left // size}{name} {left % size // sub_size}{sub_name}"
    return f"{left}s"
