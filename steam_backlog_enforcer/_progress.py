"""Progress reporting for long operations, shared by the CLI and web jobs.

Long loops (library scan, HLTB lookups, per-game uninstall, tampering check)
report *what* they are doing through :func:`current_progress`; *who* listens
is decided by the caller. The CLI listens to nothing — it already prints its
own meters with ``_echo``, and they stay byte-identical — while a web job
installs a reporter that writes ``progress`` events.

The active reporter lives in a context variable rather than a parameter so
the loops, which sit several calls below the command entry points, report
without every signature in between growing an argument.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator, Sequence


class Progress(Protocol):
    """Receives the phases and steps of a long operation."""

    def phase(self, label: str, total: int | None = None) -> None:
        """Start a new phase; ``total`` is ``None`` when it is indeterminate."""

    def advance(self, item: str | None = None, *, step: int | None = None) -> None:
        """Move one step forward, or to ``step`` when the caller counts itself.

        Args:
            item: What the step was about (a game name), shown next to it.
            step: Absolute step number; ``None`` means "one more than before".
        """


class NullProgress:
    """The CLI reporter: does nothing, the CLI prints its own meters."""

    def phase(self, label: str, total: int | None = None) -> None:
        """Ignore a phase start."""
        del label, total

    def advance(self, item: str | None = None, *, step: int | None = None) -> None:
        """Ignore a step."""
        del item, step


_ACTIVE: ContextVar[Progress | None] = ContextVar("progress", default=None)
_NULL = NullProgress()


def current_progress() -> Progress:
    """Return the reporter the running command should talk to."""
    return _ACTIVE.get() or _NULL


@contextmanager
def use_progress(progress: Progress) -> Iterator[Progress]:
    """Make *progress* the active reporter for the duration of the context."""
    token = _ACTIVE.set(progress)
    try:
        yield progress
    finally:
        _ACTIVE.reset(token)


def tracked[T](items: Sequence[T], label: str, name: Callable[[T], str]) -> Iterator[T]:
    """Yield *items*, reporting one determinate step per item.

    The step is reported *after* the caller finishes with the item, so the
    count shown is always "done", never "started".

    Args:
        items: The work list; its length is the phase total.
        label: Phase label, e.g. ``"Uninstalling games"``.
        name: Turns an item into the text shown next to its step.
    """
    progress = current_progress()
    progress.phase(label, len(items))
    for item in items:
        yield item
        progress.advance(name(item))


async def gather_tracked[T](
    label: str, coros: Sequence[Awaitable[T]], names: Sequence[str] | None = None
) -> list[T]:
    """``asyncio.gather`` that reports one determinate step per finished awaitable.

    Steps count completions (in whatever order they finish), so the bar moves
    while the batch runs instead of jumping to full at the end.

    Args:
        label: Phase label, e.g. ``"Fetching HLTB detail pages"``.
        coros: The awaitables; their count is the phase total.
        names: Per-awaitable text shown next to its step, if any.
    """
    progress = current_progress()
    progress.phase(label, len(coros))
    done = 0

    async def one(coro: Awaitable[T], name: str | None) -> T:
        nonlocal done
        result = await coro
        done += 1
        progress.advance(name, step=done)
        return result

    labels = names if names is not None else [None] * len(coros)
    return list(await asyncio.gather(*map(one, coros, labels, strict=True)))


def eta_seconds(elapsed: float, step: int, total: int | None) -> int | None:
    """Estimate the seconds left from the average time per finished step.

    Returns:
        ``None`` until at least one step finished or when there is no total.
    """
    if total is None or step <= 0:
        return None
    return max(0, round(elapsed / step * (total - step)))
