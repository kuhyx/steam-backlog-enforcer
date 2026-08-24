"""Game-name normalisation and the protected-name check.

Split out of :mod:`steam_backlog_enforcer.game_install` to keep it under the
250-line cap. Pure string handling with no filesystem or Steam knowledge, so
it stays a leaf module.
"""

from __future__ import annotations

import difflib
import logging
import re

# _allowed_games, not _actions: _actions imports game_uninstall, which
# imports this module. The leaf module has the same function and no cycle.
from steam_backlog_enforcer._allowed_games import allowed_games
from steam_backlog_enforcer.config import State

logger = logging.getLogger(__name__)

_NAME_FUZZY_MATCH_THRESHOLD = 0.82

_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}

_ROMAN_NUMERALS = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}


def _normalize_game_name(name: str) -> str:
    """Canonicalize a game/folder name for fuzzy comparison.

    Splits into alphanumeric words, maps spelled-out numbers ("two") and
    roman numerals ("II") to digits, then joins with no separators. Makes
    "Kingdom Come: Deliverance II", "KingdomComeDeliverance2", and "kingdom
    come deliverance two" all normalize to the same string.
    """
    words = re.findall(r"[A-Za-z0-9]+", name.lower())
    mapped = [_NUMBER_WORDS.get(w) or _ROMAN_NUMERALS.get(w) or w for w in words]
    return "".join(mapped)


def _protected_name_stems() -> list[str]:
    """Every name of every currently-allowed game, for the deletion safety net.

    Returns [] (protects nothing extra beyond exact matches already checked
    by callers) if state can't be loaded -- this is a best-effort safety net,
    not a hard dependency.
    """
    try:
        return [name for _, name in allowed_games(State.load()) if name]
    except Exception:
        logger.exception("Could not load allowed games for the deletion safety net")
        return []


def _is_protected_name(candidate: str) -> bool:
    """True if *candidate* plausibly names one of the currently-allowed games.

    Errs toward over-matching on purpose: a false positive here just skips a
    deletion that can be done manually; a false negative deletes real files.
    """
    normalized_candidate = _normalize_game_name(candidate)
    if not normalized_candidate:
        return False
    for protected in _protected_name_stems():
        normalized_protected = _normalize_game_name(protected)
        if not normalized_protected:
            continue
        if normalized_candidate == normalized_protected:
            return True
        ratio = difflib.SequenceMatcher(
            None, normalized_candidate, normalized_protected
        ).ratio()
        if ratio >= _NAME_FUZZY_MATCH_THRESHOLD:
            return True
    return False


# Real Steam directory — used as a safety check to block destructive
# operations that leak through during testing.
