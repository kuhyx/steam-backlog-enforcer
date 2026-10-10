"""The server-driven command catalog: ``GET /api/commands``.

One ``CommandSpec`` (``web/src/api/contract.ts``) per CLI command, so the UI
renders every control from data instead of hard-coding commands, phrases or
lock rules. Descriptions come from the CLI's own help table
(:mod:`steam_backlog_enforcer._command_help`), friction from
:data:`steam_backlog_enforcer._friction.FRICTION`, params from
:data:`steam_backlog_enforcer._command_params.PARAMS`, job flags from the job
registry and ``locked_reason`` from the CLI's lock gate — nothing here is a
second copy of a rule that lives elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from steam_backlog_enforcer._command_gate import lock_reason
from steam_backlog_enforcer._command_help import ALL_COMMAND_DESCRIPTIONS
from steam_backlog_enforcer._command_params import PARAMS
from steam_backlog_enforcer._friction import FRICTION
from steam_backlog_enforcer.config import Config, State
from steam_backlog_enforcer.jobs._specs import JOB_FLAGS

if TYPE_CHECKING:
    from steam_backlog_enforcer._friction import Friction

Category = Literal["backlog", "library", "gaming", "store", "system"]
Kind = Literal["view", "job", "screen"]


@dataclass(frozen=True)
class _Entry:
    """How the UI surfaces one command (the parts not derived elsewhere).

    ``mutating`` / ``cancellable`` / ``privileged`` here apply to views and
    screens only; for ``job`` commands they come from the job registry.
    """

    category: Category
    kind: Kind
    view_endpoint: str | None = None
    mutating: bool = False
    cancellable: bool = False
    privileged: bool = False


def _view(category: Category, endpoint: str) -> _Entry:
    """A read-only command rendered from a GET endpoint."""
    return _Entry(category, "view", view_endpoint=endpoint)


def _job(category: Category) -> _Entry:
    """A command that runs as a job (flags from the registry)."""
    return _Entry(category, "job")


# Order is the UI's default order: everyday backlog flow first.
CATALOG: Final[dict[str, _Entry]] = {
    "status": _view("backlog", "/api/status"),
    "list": _view("backlog", "/api/dataset"),
    "stats": _view("backlog", "/api/stats"),
    "check": _job("backlog"),
    "done": _job("backlog"),
    "scan": _job("backlog"),
    "pick": _job("backlog"),
    "pick-manual": _job("backlog"),
    "abandon-pick": _job("backlog"),
    "installed": _view("library", "/api/installed"),
    "install": _job("library"),
    "uninstall": _job("library"),
    "hide": _job("library"),
    "unhide": _job("library"),
    "add-exception": _job("library"),
    "gaming-status": _view("gaming", "/api/budget"),
    "gaming-reset": _job("gaming"),
    "gaming-unblock": _job("gaming"),
    "block-gaming": _job("gaming"),
    "buy-dlc": _job("store"),
    "unblock": _job("store"),
    "reset": _job("system"),
    "setup": _Entry("system", "screen", mutating=True),
    # The daemon screen. Its only action is a rate-limited restart through
    # the daemon; the 60-second demo runs as a job (params: demo=1).
    "enforce": _Entry("system", "screen", mutating=True, privileged=True),
    "serve": _Entry("system", "screen"),
}


def _friction_json(friction: Friction | None) -> dict[str, object] | None:
    """The contract's ``FrictionSpec``, or ``None``."""
    if friction is None:
        return None
    out: dict[str, object] = {"phrase_template": friction.phrase_template}
    if friction.countdown_seconds:
        out["countdown_seconds"] = friction.countdown_seconds
    return out


def _spec(
    name: str, entry: _Entry, description: str, locked: str | None
) -> dict[str, object]:
    """One ``CommandSpec`` object."""
    job = JOB_FLAGS.get(name) if entry.kind == "job" else None
    spec: dict[str, object] = {
        "name": name,
        "description": description,
        "category": entry.category,
        "kind": entry.kind,
        "params": [p.to_json() for p in PARAMS.get(name, ())],
        "friction": _friction_json(FRICTION.get(name)),
        "privileged": job.privileged if job else entry.privileged,
        "mutating": job.mutating if job else entry.mutating,
        "cancellable": job.cancellable if job else entry.cancellable,
        "locked_reason": locked,
    }
    if entry.view_endpoint is not None:
        spec["view_endpoint"] = entry.view_endpoint
    return spec


def command_specs(
    config: Config | None = None, state: State | None = None
) -> list[dict[str, object]]:
    """Build the ``CommandSpec[]`` payload, locks evaluated right now.

    Args:
        config: Loaded configuration (loaded here when omitted).
        state: Loaded state (loaded here when omitted).
    """
    config = config or Config.load()
    state = state or State.load()
    return [
        _spec(
            name,
            entry,
            ALL_COMMAND_DESCRIPTIONS[name],
            lock_reason(name, config, state),
        )
        for name, entry in CATALOG.items()
    ]
