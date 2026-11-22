"""Check that a store unblock or re-block really did what it reports.

An unblock once reported "Success" while a live ``::`` hosts line kept the
store blocked: nothing looked at the result. Every store-window action now
runs these checks and fails loudly when one does not hold.

Unblock checks, in order (the first failing one names the failure):
    hosts     -- no live store line in /etc/hosts (either address family);
    iptables  -- the store chain is gone;
    https     -- ``https://store.steampowered.com/`` answers.
When only ``https`` fails and ``https://steamcommunity.com/`` fails too, the
machine is offline: the result is "network down", not an unblock failure.

Re-block checks (the reverse):
    dns       -- every store domain resolves only to a sinkhole;
    https     -- the store does not answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import shutil
import subprocess
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._hosts_lines import (
    SINKHOLES,
    live_store_lines,
    store_lines,
)
from steam_backlog_enforcer._store_tools import IPTABLES, IPTABLES_CHAIN, SUDO
from steam_backlog_enforcer.config import BLOCKED_DOMAINS, HOSTS_FILE

if TYPE_CHECKING:
    from collections.abc import Callable

UNBLOCK: Final = "unblock"
REBLOCK: Final = "re-block"
NETWORK_DOWN: Final = "network down"
STORE_URL: Final = "https://store.steampowered.com/"
CONTROL_URL: Final = "https://steamcommunity.com/"

CURL: Final = shutil.which("curl") or "/usr/bin/curl"
GETENT: Final = shutil.which("getent") or "/usr/bin/getent"
JOURNALCTL: Final = shutil.which("journalctl") or "/usr/bin/journalctl"
_UNIT: Final = "steam-backlog-enforcer.service"
# curl's --max-time bounds the whole request, IPv6-then-IPv4 fallback included.
_HTTPS_SECONDS: Final = 8
_GETENT_SECONDS: Final = 2
_JOURNAL_SECONDS: Final = 5
_JOURNAL_LINES: Final = 50


@dataclass(frozen=True)
class Check:
    """One check's outcome: its name, whether it held, and what was seen."""

    name: str
    ok: bool
    detail: str


@dataclass
class StoreCheckReport:
    """Every check of one action, plus the evidence a failure report needs."""

    action: str
    at: str
    checks: list[Check]
    network_down: bool = False
    repaired: bool = False
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """Whether every check held."""
        return not self.network_down and all(c.ok for c in self.checks)

    @property
    def failed_check(self) -> str | None:
        """The failure: "network down", the first failed check, or None."""
        if self.network_down:
            return NETWORK_DOWN
        return next((c.name for c in self.checks if not c.ok), None)

    @property
    def title(self) -> str:
        """The todo task title for this failure."""
        return f"Store {self.action} verification failed: {self.failed_check}"

    def body(self) -> str:
        """The failure report as markdown, for the todo task."""
        rows = [
            f"- {c.name}: {'ok' if c.ok else 'FAILED'} ({c.detail})"
            for c in self.checks
        ]
        parts = [
            f"Time: {self.at}",
            f"Action: {self.action}",
            f"Repair pass run: {'yes' if self.repaired else 'no'}",
            f"Result: {self.failed_check or 'ok'}",
            "",
            "## Checks",
            *rows,
        ]
        for name, text in self.evidence.items():
            parts += ["", f"## {name}", "```", text.rstrip() or "(empty)", "```"]
        return "\n".join(parts) + "\n"

    def to_wire(self) -> dict[str, object]:
        """What the daemon hands the web server for filing."""
        return {
            "action": self.action,
            "check": self.failed_check,
            "title": self.title,
            "body": self.body(),
        }


class StoreVerifyError(RuntimeError):
    """A store action ran but its checks failed, even after the repair pass."""

    def __init__(self, report: StoreCheckReport) -> None:
        """Keep *report* for the caller to show and file."""
        super().__init__(f"Store {report.action} failed: {report.failed_check}")
        self.report = report


def _run(cmd: list[str], timeout: float) -> tuple[int, str]:
    """Run *cmd*; its exit code and combined output (``-1`` if it never ran)."""
    try:
        done = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return done.returncode, (done.stdout + done.stderr).strip()


def https_reachable(url: str) -> tuple[bool, str]:
    """Whether *url* answers at all (any HTTP status counts as reachable)."""
    cmd = [CURL, "-sS", "-o", "/dev/null", "-w", "%{http_code}"]
    rc, out = _run([*cmd, "--max-time", str(_HTTPS_SECONDS), url], _HTTPS_SECONDS + 2)
    return rc == 0, f"curl rc={rc} {out}".strip()


def resolve(domain: str) -> tuple[set[str], str]:
    """Addresses *domain* resolves to via NSS (what curl and Steam see)."""
    _rc, out = _run([GETENT, "ahosts", domain], _GETENT_SECONDS)
    return {line.split()[0] for line in out.splitlines() if line.split()}, out


def _hosts_text() -> str:
    try:
        return HOSTS_FILE.read_text(encoding="utf-8")
    except OSError as exc:
        return f"(unreadable: {exc})"


def _chain_rules() -> tuple[bool, str]:
    """Whether the store chain exists, and ``iptables -S`` for it."""
    rc, out = _run([SUDO, IPTABLES, "-S", IPTABLES_CHAIN], 5)
    return rc == 0, out


def check_unblock() -> StoreCheckReport:
    """Run the unblock checks once."""
    live = live_store_lines(_hosts_text())
    chain, _rules = _chain_rules()
    store_ok, store_detail = https_reachable(STORE_URL)
    checks = [
        Check("hosts", not live, f"{len(live)} live store line(s)"),
        Check("iptables", not chain, "chain present" if chain else "chain gone"),
        Check("https", store_ok, store_detail),
    ]
    report = StoreCheckReport(UNBLOCK, _now(), checks)
    if not live and not chain and not store_ok:
        report.network_down = not https_reachable(CONTROL_URL)[0]
    return report


def check_reblock() -> StoreCheckReport:
    """Run the re-block checks once."""
    leaks = {}
    for domain in BLOCKED_DOMAINS:
        addrs, _ = resolve(domain)
        if not addrs or not addrs <= SINKHOLES:
            leaks[domain] = ",".join(sorted(addrs)) or "no answer"
    store_open, detail = https_reachable(STORE_URL)
    leak_text = "; ".join(f"{d} -> {a}" for d, a in leaks.items())
    checks = [
        Check("dns", not leaks, leak_text or "every domain sinkholed"),
        Check("https", not store_open, detail),
    ]
    return StoreCheckReport(REBLOCK, _now(), checks)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def gather_evidence(report: StoreCheckReport) -> None:
    """Attach hosts lines, the chain, getent per domain and the journal tail."""
    getent = [f"$ getent ahosts {d}\n{resolve(d)[1]}" for d in BLOCKED_DOMAINS]
    journal = [JOURNALCTL, "-u", _UNIT, "-n", str(_JOURNAL_LINES), "--no-pager", "-q"]
    report.evidence = {
        "/etc/hosts store lines": "\n".join(store_lines(_hosts_text())),
        f"iptables -S {IPTABLES_CHAIN}": _chain_rules()[1],
        "getent": "\n".join(getent),
        "Daemon journal (last 50 lines)": _run(journal, _JOURNAL_SECONDS)[1],
    }


def verify(
    check: Callable[[], StoreCheckReport],
    repair: Callable[[], object] | None = None,
) -> StoreCheckReport:
    """Run *check*; on failure run *repair* once and check again.

    The report that comes back carries the evidence when it failed.
    """
    report = check()
    if report.ok:
        return report
    if repair is not None:
        repair()
        report = check()
        report.repaired = True
        if report.ok:
            return report
    gather_evidence(report)
    return report
