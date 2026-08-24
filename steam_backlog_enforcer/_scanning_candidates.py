"""Candidate selection helpers for ``scan`` and ``pick_next_game``.

Split out of :mod:`steam_backlog_enforcer.scanning` to keep both files under
the 250-line cap. Leaf helpers: nothing here calls back into ``scanning``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from steam_backlog_enforcer._scanning_confidence import (
    _candidate_passes_hltb_confidence,
)
from steam_backlog_enforcer.game_install import _echo
from steam_backlog_enforcer.protondb import (
    ProtonDBRating,
    fetch_protondb_ratings,
)

if TYPE_CHECKING:
    from steam_backlog_enforcer.steam_api import GameInfo

logger = logging.getLogger(__name__)

_PROTONDB_BATCH_SIZE = 20

_PICK_LIST_SIZE = 10


def _sort_key(g: GameInfo) -> tuple[int, float]:
    """Sort by known HLTB time (shortest first), then unknown games."""
    if g.completionist_hours > 0:
        return (0, g.completionist_hours)
    return (1, g.name.lower().encode().hex().__hash__())


def _pick_playable_candidate(
    candidates: list[GameInfo],
) -> GameInfo | None:
    """Return the first candidate with an acceptable ProtonDB rating.

    Checks candidates in batches (sorted by HLTB hours, shortest first).
    Games rated silver-or-worse, or gold-trending-down, are skipped.
    """
    offset = 0
    while offset < len(candidates):
        batch = candidates[offset : offset + _PROTONDB_BATCH_SIZE]
        app_ids = [g.app_id for g in batch]
        ratings = fetch_protondb_ratings(app_ids)

        for game in batch:
            rating = ratings.get(game.app_id, ProtonDBRating(app_id=game.app_id))
            if rating.is_playable:
                if offset > 0 or game is not batch[0]:
                    _echo(
                        f"  Skipped {offset + batch.index(game)} game(s) "
                        f"with poor Linux compatibility"
                    )
                return game
            logger.info(
                "Skipping %s (AppID=%d): ProtonDB %s (trending %s)",
                game.name,
                game.app_id,
                rating.tier,
                rating.trending_tier,
            )

        offset += _PROTONDB_BATCH_SIZE

    return None


def _collect_qualified_candidates(
    candidates: list[GameInfo],
) -> tuple[list[GameInfo], int, int]:
    """Collect up to _PICK_LIST_SIZE playable, HLTB-confident candidates."""
    qualified: list[GameInfo] = []
    confidence_skipped = 0
    linux_skipped = 0
    for game in candidates:
        if len(qualified) >= _PICK_LIST_SIZE:
            break
        if not _candidate_passes_hltb_confidence(game):
            confidence_skipped += 1
            continue
        playable = _pick_playable_candidate([game])
        if playable is not None:
            qualified.append(playable)
        else:
            linux_skipped += 1
    return qualified, confidence_skipped, linux_skipped


def _pick_next_shortest_candidate(
    candidates: list[GameInfo],
) -> tuple[GameInfo | None, int, int]:
    """Pick next game by checking confidence one candidate at a time.

    The list must be pre-sorted by desired priority (shortest first).
    """
    confidence_skipped = 0
    linux_skipped = 0
    for game in candidates:
        if not _candidate_passes_hltb_confidence(game):
            confidence_skipped += 1
            continue

        # Reuse existing ProtonDB compatibility gate for one candidate.
        playable = _pick_playable_candidate([game])
        if playable is not None:
            if linux_skipped > 0:
                _echo(
                    f"  Skipped {linux_skipped} game(s) with poor Linux compatibility"
                )
            return playable, confidence_skipped, linux_skipped
        linux_skipped += 1

    if linux_skipped > 0:
        _echo(f"  Skipped {linux_skipped} game(s) with poor Linux compatibility")
    return None, confidence_skipped, linux_skipped


def _collect_top_candidates(
    candidates: list[GameInfo],
    n: int = 3,
) -> tuple[list[GameInfo], int, int]:
    """Collect up to n candidates that pass the Linux compatibility gate.

    Args:
        candidates: Pre-sorted list of candidate games.
        n: Maximum number of qualified games to collect.

    Returns:
        Tuple of (qualified_list, conf_skipped, linux_skipped).
    """
    qualified: list[GameInfo] = []
    linux_skipped = 0
    for game in candidates:
        if len(qualified) >= n:
            break
        playable = _pick_playable_candidate([game])
        if playable is not None:
            qualified.append(playable)
        else:
            linux_skipped += 1
    if linux_skipped > 0:
        _echo(f"  Skipped {linux_skipped} game(s) with poor Linux compatibility")
    return qualified, 0, linux_skipped
