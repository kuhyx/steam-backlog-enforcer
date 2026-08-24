"""Parsing a HowLongToBeat game page.

Leaf helpers: they call nothing else in the module, so extracting
them introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
)


def _parse_game_page(html: str) -> dict[str, Any] | None:
    """Extract game data dict from a HLTB game page's __NEXT_DATA__."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        result: dict[str, Any] = data["props"]["pageProps"]["game"]["data"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    return result


def _as_positive_int(value: object) -> int:
    """Convert HLTB numeric JSON values to a positive int, or 0 when invalid."""
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        int_value = int(value)
        return max(0, int_value)
    if isinstance(value, str):
        try:
            int_value = int(value)
            return max(0, int_value)
        except ValueError:
            return 0
    return 0


def _apply_dlc_leisure_overrides(
    base_hours: float,
    dlc_rels: list[tuple[int, float]],
    dlc_hours_by_id: dict[int, float],
) -> float:
    """Replace fallback DLC hours with detailed leisure hours when available."""
    adjusted = base_hours
    for dlc_id, fallback_hours in dlc_rels:
        dlc_leisure = dlc_hours_by_id.get(dlc_id, -1.0)
        if dlc_leisure > 0:
            adjusted += dlc_leisure - fallback_hours
    return round(adjusted, 2)
