"""Fuzzy name matching and search-variant building for HowLongToBeat.

Leaf helpers: they call nothing else in the module, so extracting
them introduces no cycle. Split to keep both files under the 250-line cap.
"""

from __future__ import annotations

from difflib import SequenceMatcher
import logging
import re
from typing import Any

from steam_backlog_enforcer._hltb_types import (
    _SUBSET_SUFFIXES,
    HLTBResult,
)

_TM_RE = re.compile("[™®©\uff0a]")
_COLON_WORD_RE = re.compile(r":(\s|$)")
_STANDALONE_PUNCT_RE = re.compile(r"^[-/|]$")
_AMP_RE = re.compile(r"\s*&\s*")
_STEAM_SUFFIX_RE = re.compile(
    r"\s+(?:\(Legacy\)|\(Classic\)|\(beta\)|\(Remastered\)|Legacy|Classic|RHCP"
    r"|\(Phase\s+\d+\))\s*$",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)

# When extended entry has ≥ this many times more hours than the exact match,
# prefer it even if its confidence count is lower.
_EXTENDED_DOMINANCE_RATIO = 4.0
# Minimum combined confidence for the dominance path (avoids picking entries
# that have almost no data at all).
_EXTENDED_MIN_CONFIDENCE = 3


# ──────────────────────────────────────────────────────────────
# HLTB API setup (done once, not per-request like the library)
# ──────────────────────────────────────────────────────────────


def _similarity(a: str, b: str) -> float:
    """Case-insensitive SequenceMatcher ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _sanitize_search_name(name: str) -> str:
    """Strip HLTB-breaking characters from a game name for searchTerms.

    Removes trademark/copyright symbols, colons at word-end, standalone
    punctuation tokens (dash, slash, pipe), and replaces & with 'and'.
    """
    cleaned = _TM_RE.sub("", name)
    cleaned = _AMP_RE.sub(" and ", cleaned)
    cleaned = _COLON_WORD_RE.sub(" ", cleaned)
    tokens = [t for t in cleaned.split() if not _STANDALONE_PUNCT_RE.match(t)]
    return " ".join(tokens)


def _build_search_variants(game_name: str) -> list[str]:
    """Return fallback search terms for one Steam game title.

    Tries progressively simplified names so HLTB search finds a result even
    when the Steam title contains edition suffixes, Steam-only labels, or
    subtitle decorators that HLTB does not index under.

    Order matters: most-specific first, then stripped-down fallbacks.
    Simplifications are chained so e.g. "Foo - Bar Edition" →
    "Foo - Bar" → "Foo" and "Foo - Bar Edition" → "Foo Edition" → "Foo".
    """
    base = game_name.strip()
    seen: set[str] = set()
    variants: list[str] = []

    def _add(name: str) -> None:
        s = name.strip()
        if s and s not in seen:
            seen.add(s)
            variants.append(s)

    _add(base)

    # Strip Steam-only labels that HLTB never uses
    no_steam = _STEAM_SUFFIX_RE.sub("", base).strip()
    _add(no_steam)

    # Strip trailing year "(YYYY)"
    no_year = re.sub(r"\s*\(\d{4}\)$", "", base).strip()
    _add(no_year)

    # Strip " - subtitle" portion (e.g. "Brothers - A Tale of Two Sons" → "Brothers")
    no_subtitle = re.sub(r"\s+-\s+.*$", "", base).strip()
    _add(no_subtitle)
    # Also strip edition from the subtitle-stripped name.
    # e.g. "Rocksmith 2014 Edition - Remastered" → "Rocksmith 2014 Edition"
    #   → "Rocksmith 2014"
    if no_subtitle != base:
        _add(re.sub(r"\s+\w+\s+Edition\s*$", "", no_subtitle, flags=re.IGNORECASE))
        _add(re.sub(r"\s+Edition\s*$", "", no_subtitle, flags=re.IGNORECASE))

    # Strip "GOTY Edition" / "Gold Edition" / "Definitive Edition" etc. from base
    no_edition = re.sub(r"\s+\w+\s+Edition\s*$", "", base, flags=re.IGNORECASE).strip()
    _add(no_edition)

    # Strip just " Edition" at end from base
    no_bare_edition = re.sub(r"\s+Edition\s*$", "", base, flags=re.IGNORECASE).strip()
    _add(no_bare_edition)

    # Strip ": subtitle" portion (e.g. "Batman: Arkham Asylum" → "Batman")
    no_colon_sub = re.sub(r"\s*:.*$", "", base).strip()
    _add(no_colon_sub)

    return variants


def _build_result_from_best(
    app_id: int,
    original_name: str,
    query_name: str,
    best: tuple[dict[str, Any], float],
) -> HLTBResult:
    """Convert selected HLTB entry into HLTBResult."""
    entry, sim = best
    hours = round(entry["comp_100"] / 3600, 2)
    logger.debug(
        ("HLTB match for '%s' via '%s': '%s' (id=%s, comp_100=%s, sim=%.3f)"),
        original_name,
        query_name,
        entry.get("game_name"),
        entry.get("game_id"),
        entry.get("comp_100"),
        sim,
    )
    return HLTBResult(
        app_id=app_id,
        game_name=original_name,
        completionist_hours=hours,
        similarity=sim,
        hltb_game_id=entry.get("game_id", 0),
        comp_100_count=int(entry.get("comp_100_count", 0) or 0),
        count_comp=int(entry.get("count_comp", 0) or 0),
    )


def _find_exact_match(
    usable: list[tuple[dict[str, Any], float]],
    lower: str,
) -> tuple[dict[str, Any], float] | None:
    """Find best exact name/alias match (highest comp_100)."""
    return next(
        (
            (e, s)
            for e, s in sorted(
                usable,
                key=lambda x: x[0].get("comp_100", 0),
                reverse=True,
            )
            if (e.get("game_name") or "").lower() == lower
            or (e.get("game_alias") or "").lower() == lower
        ),
        None,
    )


def _find_best_extended(
    usable: list[tuple[dict[str, Any], float]],
    lower: str,
) -> tuple[dict[str, Any], float] | None:
    """Find best extended entry ("Name: Subtitle" / "Name - Subtitle").

    Skips subset entries (prologue, demo, etc.).  Compilations ("compil")
    are included because HLTB classifies multi-chapter collections that
    share the base title as compilations (e.g. "FAITH: The Unholy Trinity").
    """
    best: tuple[dict[str, Any], float] | None = None
    for entry, sim in usable:
        game_type = str(entry.get("game_type", "")).lower()
        if game_type not in ("", "game", "compil"):
            continue
        entry_name = (entry.get("game_name") or "").lower()
        if entry_name.startswith((lower + ":", lower + " -")):
            suffix = entry_name[len(lower) :].lstrip(" :-")
            if not any(suffix.startswith(kw) for kw in _SUBSET_SUFFIXES) and (
                best is None or entry.get("comp_100", 0) > best[0].get("comp_100", 0)
            ):
                best = (entry, sim)
    return best


def _resolve_exact_vs_extended(
    best_exact: tuple[dict[str, Any], float] | None,
    best_extended: tuple[dict[str, Any], float] | None,
    usable: list[tuple[dict[str, Any], float]],
) -> tuple[dict[str, Any], float]:
    """Decide between exact match, extended entry, or highest similarity."""
    if best_exact is not None and best_extended is not None:
        exact_hours = best_exact[0].get("comp_100", 0)
        extended_hours = best_extended[0].get("comp_100", 0)
        exact_confidence = int(best_exact[0].get("comp_100_count", 0) or 0) + int(
            best_exact[0].get("count_comp", 0) or 0
        )
        extended_confidence = int(best_extended[0].get("comp_100_count", 0) or 0) + int(
            best_extended[0].get("count_comp", 0) or 0
        )
        # Prefer the extended entry when it has more hours AND either:
        #  (a) at least as much confidence (normal case), OR
        #  (b) dominant hours ratio (>=4x) with minimal data — handles cases
        #      like "FAITH: The Unholy Trinity" (17h, newer) vs "FAITH" 2017
        #      (1.5h, older/more data) where the older exact match has
        #      accumulated more confidence simply by being on HLTB longer.
        dominates = (
            exact_hours > 0
            and extended_hours >= exact_hours * _EXTENDED_DOMINANCE_RATIO
            and extended_confidence >= _EXTENDED_MIN_CONFIDENCE
        )
        if extended_hours > exact_hours and (
            extended_confidence >= exact_confidence or dominates
        ):
            return best_extended
        return best_exact
    if best_exact is not None:
        return best_exact
    if best_extended is not None:
        return best_extended

    # Fall back to highest similarity.
    return max(usable, key=lambda x: x[1])
