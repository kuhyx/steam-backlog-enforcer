"""Failed store checks as the web server sees them: job log lines and todo tasks.

The daemon builds the report (``_store_verify``); the web server, running as
the desktop user, files it in the todo app. A failed unblock comes back on
the ``store_unblock`` call itself. A failed end-of-window re-block happens in
the daemon with nobody asking, so a background thread fetches those reports
every minute (``store_reports``) and records each as a failed job.

The re-block job is recorded under its own ``re-block`` command, a job-only
name like ``restore-backup``: the web contract and icon registry list it, the
CLI has no such command.
"""

from __future__ import annotations

from datetime import datetime
import logging
import threading
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer import _ctl_client
from steam_backlog_enforcer._ctl_protocol import CtlError, DaemonUnreachableError
from steam_backlog_enforcer._todo_filing import FilingError, file_report
from steam_backlog_enforcer.jobs._daemon_jobs import (
    EXIT_FAILED,
    DaemonOutcome,
    record_daemon_job,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

POLL_SECONDS: Final = 60.0

type LogLines = tuple[tuple[str, str], ...]


def filing_log(report: Mapping[str, object]) -> LogLines:
    """File *report* in the todo app; the job log lines saying what happened.

    Never raises: a filing failure becomes an ``error`` line, and the job it
    lands in has already failed (non-zero exit), so nothing fails quietly.
    """
    title = str(report.get("title", "?"))
    try:
        filed = file_report(report)
    except FilingError as exc:
        logger.exception("Could not file todo task %r", title)
        return (("error", f"Could not file the todo task {title!r}: {exc}"),)
    if filed.created:
        return (("info", f"Filed todo task {title!r}: {filed.task}"),)
    return (("info", f"Todo task {filed.task} is already open for {title!r}."),)


def record_reblock_failure(report: Mapping[str, object]) -> str:
    """Record one failed re-block as a failed job, filing its task first."""
    outcome = DaemonOutcome(
        ok=False,
        summary=f"Store re-block failed: {report.get('check')}",
        exit_code=EXIT_FAILED,
        data={"check": report.get("check")},
        log=filing_log(report),
    )
    created_at = datetime.now().astimezone().isoformat()
    return record_daemon_job("re-block", {}, created_at=created_at, outcome=outcome)


def collect_store_reports() -> int:
    """Fetch the daemon's queued re-block failures and record each; the count."""
    try:
        reports = _ctl_client.store_reports()
    except (DaemonUnreachableError, CtlError) as exc:
        logger.warning("store_reports: %s", exc)
        return 0
    for report in reports:
        try:
            record_reblock_failure(report)
        except OSError:
            logger.exception("Could not record the failed re-block job")
    return len(reports)


def start_store_report_poller(interval: float = POLL_SECONDS) -> threading.Event:
    """Collect re-block reports every *interval* seconds until the event is set."""
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(interval):
            collect_store_reports()

    threading.Thread(target=loop, name="store-reports", daemon=True).start()
    return stop
