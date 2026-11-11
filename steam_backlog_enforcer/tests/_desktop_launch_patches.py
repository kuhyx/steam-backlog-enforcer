"""Shared helpers for the desktop-session and Steam-launch tests.

The desktop/launch test files each patched the same ``_steam_launch``
seams one ``patch(...)`` at a time; this module holds that boilerplate once.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Iterator

DESKTOP_ENV_PKG = "steam_backlog_enforcer._desktop_env"
STEAM_LAUNCH_PKG = "steam_backlog_enforcer._steam_launch"
STEAM_PROCESS_PKG = "steam_backlog_enforcer._steam_process"


def env_value(args: list[str], name: str) -> str | None:
    """Return the value assigned to *name* in a list of ``VAR=value`` args."""
    prefix = f"{name}="
    for arg in args:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


@contextmanager
def launch_patches(
    *bare: str,
    extra: dict[str, object] | None = None,
    **returns: object,
) -> Iterator[dict[str, MagicMock]]:
    """Patch ``_steam_launch`` attributes for the duration of the block.

    *bare* names are patched with a default mock, *returns* names with a mock
    returning the given value, and *extra* maps full dotted targets in other
    modules to return values. Yields the mocks keyed by name or target.
    """
    targets: list[tuple[str, str, dict[str, object]]] = [
        (name, f"{STEAM_LAUNCH_PKG}.{name}", {}) for name in bare
    ]
    targets += [
        (name, f"{STEAM_LAUNCH_PKG}.{name}", {"return_value": value})
        for name, value in returns.items()
    ]
    targets += [
        (target, target, {"return_value": value})
        for target, value in (extra or {}).items()
    ]
    with ExitStack() as stack:
        yield {
            key: stack.enter_context(patch(target, **kwargs))
            for key, target, kwargs in targets
        }


@contextmanager
def fresh_launch_patches(
    *bare: str,
    cdp_ready: bool = True,
    collections_ready: bool | None = True,
    extra: dict[str, object] | None = None,
    **returns: object,
) -> Iterator[dict[str, MagicMock]]:
    """Patch a Steam with no debug port that gets launched and waited on.

    ``_launch_steam_with_debug`` is always patched (bare); the CDP and
    collections waits return *cdp_ready* / *collections_ready*; a
    *collections_ready* of ``None`` leaves that wait unpatched.
    """
    if collections_ready is not None:
        returns["_wait_for_collections_ready"] = collections_ready
    with launch_patches(
        "_launch_steam_with_debug",
        *bare,
        extra=extra,
        _steam_has_debug_port=False,
        _wait_for_cdp_ready=cdp_ready,
        **returns,
    ) as mocks:
        yield mocks
