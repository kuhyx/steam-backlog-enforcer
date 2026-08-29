"""Turning attribution keys into names a human recognises.

Keys are stable (``app:475150``); labels are not (Steam renames games, and a
user can retitle a ``counted_processes`` entry). So keys are what get stored in
state and history, and this module resolves them for display.

Steam names come from ``appmanifest_<id>.acf`` rather than ``snapshot.json``:
a game that is *running* is by definition installed, so its manifest exists and
is a few hundred bytes, whereas the snapshot is ~11 MB and would be read on
every three-second tick and every five-second UI poll.
"""

from __future__ import annotations

import contextlib
import re
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _steam_state
from steam_backlog_enforcer._counted_procs import labels_by_key, load_counted_processes

if TYPE_CHECKING:
    from collections.abc import Iterable

_APP_PREFIX: Final = "app:"
_PROC_PREFIX: Final = "proc:"
_LAUNCHER_PREFIX: Final = "launcher:"

# Same pattern game_uninstall.get_installed_games() uses on the same files.
_NAME_RE: Final = re.compile(r'"name"\s+"([^"]+)"')

# Manifest names never change while a game runs, and the daemon is long-lived.
_app_names: dict[int, str] = {}


def _steam_name(app_id: int) -> str | None:
    """Return *app_id*'s name from its appmanifest, or ``None``.

    Args:
        app_id: Steam application id.

    Returns:
        The manifest's ``name`` field, or ``None`` if unreadable.
    """
    cached = _app_names.get(app_id)
    if cached is not None:
        return cached
    manifest = _steam_state.STEAMAPPS_PATH / f"appmanifest_{app_id}.acf"
    with contextlib.suppress(OSError):
        match = _NAME_RE.search(manifest.read_text(encoding="utf-8"))
        if match:
            name = match.group(1)
            _app_names[app_id] = name
            return name
    return None


def label_for(key: str) -> str:
    """Return a display name for an attribution *key*.

    Falls back to the key itself, which is ugly but never wrong — an
    unresolvable game is still better identified by ``app:475150`` than by a
    blank row.

    Args:
        key: An ``app:``/``proc:``/``launcher:`` attribution key.

    Returns:
        The display label.
    """
    if key.startswith(_APP_PREFIX):
        raw = key[len(_APP_PREFIX) :]
        if raw.isdigit():
            return _steam_name(int(raw)) or key
        return key
    if key.startswith(_PROC_PREFIX):
        return labels_by_key(load_counted_processes()).get(key, key)
    if key.startswith(_LAUNCHER_PREFIX):
        return key[len(_LAUNCHER_PREFIX) :]
    return key


def labels_for(keys: Iterable[str]) -> dict[str, str]:
    """Resolve every key in *keys* to its label.

    Args:
        keys: Any iterable of attribution keys.

    Returns:
        Mapping of key to display label.
    """
    return {key: label_for(key) for key in keys}
