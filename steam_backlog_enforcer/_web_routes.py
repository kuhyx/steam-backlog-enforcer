"""The API's route table: method + path pattern → route function.

One table, so the whole surface (``DOCS-web-control-api.md``, "Endpoints")
can be read in one screen. Path ids are restricted to the characters the
stores issue; the stores re-validate them anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import (
    _web_art,
    _web_daemon,
    _web_jobs,
    _web_library,
    _web_process,
    _web_setup,
    _web_views,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from steam_backlog_enforcer._web_io import Reply, Request

type Route = Callable[[Request], Reply]

_ID = r"([0-9A-Za-z_-]{1,64})"
# Matched before the table by the server: it streams instead of replying.
EVENTS_PATH: Final = re.compile(rf"^/api/jobs/{_ID}/events$")


@dataclass(frozen=True)
class _Entry:
    """One route."""

    method: str
    pattern: re.Pattern[str]
    route: Route


def _r(method: str, path: str, route: Route) -> _Entry:
    """Build an entry; ``{id}`` in *path* captures one id segment."""
    return _Entry(method, re.compile("^" + path.replace("{id}", _ID) + "$"), route)


ROUTES: Final[tuple[_Entry, ...]] = (
    _r("GET", "/api/dataset", _web_views.dataset_view),
    _r("GET", "/api/budget", _web_views.budget_view),
    _r("GET", "/api/status", _web_views.status_view),
    _r("GET", "/api/stats", _web_views.stats_view),
    _r("GET", "/api/installed", _web_views.installed_view),
    _r("GET", "/api/library", _web_library.library_view),
    _r("GET", "/api/art/{id}", _web_art.art_view),
    _r("GET", "/api/commands", _web_views.commands_view),
    _r("GET", "/api/setup", _web_views.setup_view),
    _r("POST", "/api/setup", _web_setup.save_setup),
    _r("GET", "/api/daemon", _web_daemon.daemon_view),
    _r("GET", "/api/server", _web_process.health_view),
    _r("POST", "/api/server/restart", _web_process.restart_view),
    _r("GET", "/api/backups", _web_views.backups_view),
    _r("POST", "/api/backups/{id}/restore", _web_jobs.restore_backup_view),
    _r("GET", "/api/jobs", _web_jobs.jobs_view),
    _r("POST", "/api/jobs", _web_jobs.create_job_view),
    _r("GET", "/api/jobs/{id}", _web_jobs.job_view),
    _r("POST", "/api/jobs/{id}/answer", _web_jobs.answer_view),
    _r("POST", "/api/jobs/{id}/cancel", _web_jobs.cancel_view),
    _r("POST", "/api/pending/{id}/heartbeat", _web_daemon.heartbeat_view),
    _r("POST", "/api/pending/{id}/commit", _web_daemon.commit_view),
    _r("DELETE", "/api/pending/{id}", _web_daemon.cancel_pending_view),
)


def resolve(method: str, path: str) -> tuple[Route, tuple[str, ...]] | str | None:
    """Find the route for *method* and *path*.

    Returns:
        ``(route, captured ids)`` on a match; the string ``"method"`` when
        the path exists under another method (405); ``None`` when no route
        has this path (404).
    """
    path_known = False
    for entry in ROUTES:
        match = entry.pattern.fullmatch(path)
        if match is None:
            continue
        if entry.method == method:
            return entry.route, match.groups()
        path_known = True
    return "method" if path_known else None
