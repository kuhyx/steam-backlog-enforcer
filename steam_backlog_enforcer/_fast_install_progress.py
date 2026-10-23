"""Live progress of a detached steam-game-installer run, read from its log.

The installer runs depotdownloader on a pty and flushes every chunk, so the
per-user ``fast_install-<euid>.log`` grows while the download runs (CRLF line
endings, from the pty). Its markers, verbatim from a real run:

* ``Shutting down the Steam client...``
* ``Steam already staged 71.53 GB for this app ...`` (adopting a partial download)
* ``Downloading via depotdownloader (fast path)...`` (connecting, logging in)
* ``Processing depot 1086941`` once per depot, then ``Downloading depot 1086941``
  as each one starts
* `` 46.90% /path/of/finished/file (657.13 Mbit/s)`` per finished file
* ``Checking for owned DLC ...``, then the manifest is finished
* ``Restarting the Steam client...``

The percentage is depotdownloader's progress through the *current depot*: it
restarts at 0 for every depot. Depots are wildly uneven (one Baldur's Gate 3
depot is 128 of its 132 GB), so averaging over depot count would lie; the
phase names the depot instead (``downloading depot 3/8``) and the percent
belongs to it.

The log is opened in append mode and keeps every earlier run, so a tracker
reads only bytes past the offset recorded at spawn, and only the new ones on
each poll: the log of a large game runs to tens of megabytes.

Who reads it: a waiting web job (:class:`WaitReporter`, through the Progress
API and a line every :data:`ECHO_SECONDS`), and the root daemon's ctl
``status`` op (:func:`fast_install_status`), which never touches the file -
the daemon's own enforce loop polls the trackers.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._echo import _echo
from steam_backlog_enforcer._progress import current_progress

if TYPE_CHECKING:
    from pathlib import Path

STARTING: Final = "starting"
_DOWNLOADING: Final = "downloading"
# Line prefix -> the phase it starts.
_MARKERS: Final = (
    ("Shutting down the Steam client", "shutting Steam down"),
    ("Steam already staged", "adopting Steam's partial download"),
    ("Downloading via depotdownloader", "connecting to Steam"),
    ("Checking for owned DLC", "finishing manifest"),
    ("Reconciling with steamcmd", "finishing manifest"),
    ("Restarting the Steam client", "restarting Steam"),
)
_PLANNED_DEPOT: Final = re.compile(r"Processing depot \d+$")
_STARTED_DEPOT: Final = re.compile(r"Downloading depot \d+$")
_PERCENT: Final = re.compile(r"\s*(\d{1,3}\.\d+)% ")
# A waiting job prints a status line this often; the bar moves every poll.
ECHO_SECONDS: Final = 30
_READ_CHUNK: Final = 1 << 20


def _clock(seconds: int) -> str:
    """``42s`` or ``5m 12s``."""
    minutes, secs = divmod(seconds, 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


@dataclass(frozen=True)
class InstallProgress:
    """Where a run is: its phase, the current depot's percent, time spent."""

    phase: str
    percent: float | None
    elapsed_seconds: int

    @property
    def downloading(self) -> bool:
        """Whether the phase is a depot download (the one with a percent)."""
        return self.phase.startswith(_DOWNLOADING)

    def describe(self) -> str:
        """``46% (downloading depot 3/8), 5m 12s elapsed``; no % before one is known."""
        elapsed = f"{_clock(self.elapsed_seconds)} elapsed"
        if self.percent is None:
            return f"{self.phase}, {elapsed}"
        return f"{int(self.percent)}% ({self.phase}), {elapsed}"


class InstallTracker:
    """Follows one run's log from its spawn offset, a complete line at a time."""

    def __init__(self, log_path: Path, *, offset: int, started: float) -> None:
        """Track *log_path* from byte *offset*; *started* is a monotonic time."""
        self._path = log_path
        self._offset = offset
        self._started = started
        self._partial = b""
        self._phase = STARTING
        self._percent: float | None = None
        self._planned = 0
        self._depot = 0

    def poll(self) -> None:
        """Parse whatever the run has written since the last poll.

        A log that is missing or unreadable changes nothing: the run itself is
        judged by its exit status, never by its log.
        """
        try:
            with self._path.open("rb") as log:
                log.seek(self._offset)
                while chunk := log.read(_READ_CHUNK):
                    self._offset += len(chunk)
                    *lines, self._partial = (self._partial + chunk).split(b"\n")
                    for line in lines:
                        self._feed(line.decode("utf-8", "replace").rstrip("\r"))
        except OSError:
            return

    def _feed(self, line: str) -> None:
        """Apply one log line to the phase / percent state."""
        if match := _PERCENT.match(line):
            if self._phase.startswith(_DOWNLOADING):
                # Max within a depot: a depot's progress only ever grows.
                self._percent = max(self._percent or 0.0, float(match.group(1)))
        elif _PLANNED_DEPOT.match(line):
            self._planned += 1
        elif _STARTED_DEPOT.match(line):
            self._depot += 1
            # DLC depots come on top of the planned ones: no total to show then.
            of = f"/{self._planned}" if self._depot <= self._planned else ""
            self._phase, self._percent = f"{_DOWNLOADING} depot {self._depot}{of}", None
        else:
            for prefix, phase in _MARKERS:
                if line.startswith(prefix):
                    self._phase, self._percent = phase, None

    def snapshot(self, now: float) -> InstallProgress:
        """The run's progress as of monotonic time *now*."""
        elapsed = max(0, int(now - self._started))
        return InstallProgress(self._phase, self._percent, elapsed)


# Live detached runs of this process by app id, with the name to show. The
# enforce loop polls them; ctl connection threads read snapshots.
_TRACKERS: dict[int, tuple[str, InstallTracker]] = {}
_LOCK = threading.Lock()


def track(app_id: int, name: str, log_path: Path, *, offset: int, now: float) -> None:
    """Start following a run just spawned with its output at *offset* of the log."""
    with _LOCK:
        _TRACKERS[app_id] = (name, InstallTracker(log_path, offset=offset, started=now))


def poll_trackers(live: set[int]) -> None:
    """Read new log lines of the *live* runs and forget every other one."""
    with _LOCK:
        for app_id in [aid for aid in _TRACKERS if aid not in live]:
            del _TRACKERS[app_id]
        for _name, tracker in _TRACKERS.values():
            tracker.poll()


def progress_of(app_id: int, now: float) -> InstallProgress | None:
    """The tracked run's progress for *app_id*, or None if it is not tracked."""
    with _LOCK:
        entry = _TRACKERS.get(app_id)
        return entry[1].snapshot(now) if entry else None


def fast_install_status(now: float) -> list[dict[str, object]]:
    """Every tracked run as the ctl ``status`` op reports it (no file I/O)."""
    with _LOCK:
        entries = [(aid, name, t.snapshot(now)) for aid, (name, t) in _TRACKERS.items()]
    return [
        {
            "app_id": app_id,
            "name": name,
            "phase": snap.phase,
            "percent": None if snap.percent is None else round(snap.percent, 2),
            "elapsed_seconds": snap.elapsed_seconds,
        }
        for app_id, name, snap in entries
    ]


class WaitReporter:
    """Shows a waiting caller's run: the job progress bar plus a periodic line.

    The installer prints a line per finished file (thousands), so nothing here
    runs per line: one report per poll, one echo per :data:`ECHO_SECONDS`.
    """

    def __init__(self, app_id: int, label: str, *, started: float) -> None:
        """Announce the wait for *app_id*'s run; *started* is when it began."""
        self._app_id = app_id
        self._label = label
        self._phase: str | None = None
        self._last_echo = started
        _echo(
            f"  Fast-installing {label} with steam-game-installer (Steam will "
            f"close); progress every {ECHO_SECONDS}s..."
        )

    def report(self, now: float) -> None:
        """Push the run's current progress; a no-op once it is not tracked."""
        snap = progress_of(self._app_id, now)
        if snap is None:
            return
        progress = current_progress()
        if snap.phase != self._phase:
            # Only on a change: phase() restarts the job's ETA clock.
            self._phase = snap.phase
            total = 100 if snap.downloading else None
            progress.phase(f"Fast-installing {self._label}: {snap.phase}", total)
        if snap.downloading:
            # Floor, so 99.99 never reads as done before the depot is.
            progress.advance(self._label, step=int(snap.percent or 0))
        else:
            progress.advance(f"{_clock(snap.elapsed_seconds)} elapsed", step=0)
        if now - self._last_echo >= ECHO_SECONDS:
            self._last_echo = now
            _echo(f"  Fast-installing {self._label}: {snap.describe()}")
