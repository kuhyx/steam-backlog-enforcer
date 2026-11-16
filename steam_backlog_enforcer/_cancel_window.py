"""A stretch of a command during which a web job may be cancelled.

Most commands cannot be stopped midway, but the library-hiding phase of
``done`` and ``check`` can: it only drives Steam, and a hide that is aborted is
already a skip. The command code marks that phase with :func:`cancel_window`;
*who* acts on the mark is decided by the caller, exactly like
:mod:`steam_backlog_enforcer._progress`. The CLI and the root daemon install
nothing, so for them the window is a no-op; a web job installs one that
announces it to the server and turns SIGTERM into a skipped hide.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    WindowFactory = Callable[[], AbstractContextManager[None]]

_ACTIVE: ContextVar[WindowFactory | None] = ContextVar("cancel_window", default=None)


def cancel_window() -> AbstractContextManager[None]:
    """Return the context manager that brackets a cancellable phase."""
    factory = _ACTIVE.get()
    return nullcontext() if factory is None else factory()


@contextmanager
def use_cancel_window(factory: WindowFactory) -> Iterator[None]:
    """Make *factory* build the cancel windows for the duration of the context."""
    token = _ACTIVE.set(factory)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
