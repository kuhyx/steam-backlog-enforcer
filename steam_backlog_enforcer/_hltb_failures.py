"""Failure accounting for HLTB lookups.

A failed request (non-200, timeout, connection error, non-JSON body) is not
evidence that a game is missing from HLTB, so the search path must keep the
cached entry instead of writing a miss. This module tells the two apart, counts
the failures for the end-of-run summary, and holds the per-batch circuit
breaker that stops hammering HLTB once it starts rate-limiting us.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# Consecutive 429s/403s after which the command sends no more requests.
BREAKER_LIMIT = 5
_BLOCKED = frozenset({HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.FORBIDDEN})
SKIPPED_AFTER_RATE_LIMIT = "skipped after rate-limit"
# A detail page that does not exist is a real answer, not a failed lookup.
_DETAIL_NOT_A_FAILURE = frozenset({HTTPStatus.OK, HTTPStatus.NOT_FOUND})
_PLURAL = {"timeout": "timeouts", "connection error": "connection errors"}


class HLTBUnavailableError(RuntimeError):
    """Nothing in an HLTB batch could be refreshed; the cache was left alone."""


@dataclass
class Breaker:
    """Circuit breaker on consecutive HTTP 429 / 403 answers.

    403 counts too: a rejected token fails every later request the same way,
    and on 2026-11-08 one let 44 doomed requests through before a manual stop.
    """

    consecutive_blocked: int = 0
    tripped: bool = False

    def note(self, status: int | None) -> None:
        """Record one request outcome (``None`` = no HTTP status at all)."""
        if status in _BLOCKED:
            self.consecutive_blocked += 1
            if self.consecutive_blocked >= BREAKER_LIMIT:
                self.tripped = True
        else:
            self.consecutive_blocked = 0


@dataclass
class _Tally:
    """Failures since the last :func:`reset_failures` (one CLI command)."""

    reasons: Counter[str] = field(default_factory=Counter)
    # App ids, so a game skipped by several passes of one command counts once.
    breaker_games: set[int] = field(default_factory=set)
    fatal: list[str] = field(default_factory=list)
    # Lookups that got a real answer (match or clean miss).
    successes: int = 0
    # Shared by every batch of the command: once HLTB rate-limits us, later
    # batches must not start hammering it again.
    breaker: Breaker = field(default_factory=Breaker)


_TALLY = _Tally()


def reset_failures() -> None:
    """Start a fresh tally (call at the start of a command)."""
    _TALLY.reasons.clear()
    _TALLY.breaker_games.clear()
    _TALLY.fatal.clear()
    _TALLY.successes = 0
    _TALLY.breaker = Breaker()


def shared_breaker() -> Breaker:
    """The command-wide circuit breaker (fresh after :func:`reset_failures`)."""
    return _TALLY.breaker


def record_success() -> None:
    """Count one lookup that got a real answer from HLTB."""
    _TALLY.successes += 1


def record_failure(reason: str) -> None:
    """Count one failed lookup under *reason*."""
    _TALLY.reasons[reason] += 1


def record_breaker(app_ids: Iterable[int]) -> None:
    """Remember the games a tripped breaker left unrefreshed."""
    _TALLY.breaker_games.update(app_ids)


def record_fatal(message: str) -> None:
    """Remember a batch that refreshed nothing at all."""
    _TALLY.fatal.append(message)


def had_total_failure() -> bool:
    """True when some batch failed outright and no lookup at all succeeded."""
    return bool(_TALLY.fatal) and not _TALLY.successes


def status_reason(status: int) -> str:
    """Label for a non-200 answer."""
    return f"HTTP {status}"


def exc_reason(exc: BaseException) -> str:
    """Label for a request that raised instead of answering cleanly."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):  # json.JSONDecodeError and friends
        return "bad JSON"
    return "connection error"


def detail_status_failed(status: int) -> bool:
    """True when a detail-page answer is a failure rather than a real verdict."""
    return status not in _DETAIL_NOT_A_FAILURE


def _label(reason: str) -> str:
    """Plural form for the summary (``detail timeout`` -> ``detail timeouts``)."""
    for singular, plural in _PLURAL.items():
        if reason.endswith(singular):
            return reason[: -len(singular)] + plural
    return reason


def failure_summary_lines() -> list[str]:
    """One-line summaries of every failure since the last reset (empty if none)."""
    lines: list[str] = []
    total = sum(_TALLY.reasons.values())
    if total:
        parts = ", ".join(
            f"{_label(reason)} x{count}"
            for reason, count in _TALLY.reasons.most_common()
        )
        lines.append(
            f"HLTB: {total} lookups failed ({parts}), cache kept for those games"
        )
    if _TALLY.breaker_games:
        n_games = len(_TALLY.breaker_games)
        lines.append(f"HLTB: rate-limited, {n_games} games not refreshed")
    lines.extend(dict.fromkeys(_TALLY.fatal))  # each batch's verdict once
    return lines
