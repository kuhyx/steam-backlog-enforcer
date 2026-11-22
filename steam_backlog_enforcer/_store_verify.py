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
    dns       -- every store domain resolves only to a sinkhole (or to
                 nothing, which is how systemd-resolved answers one);
    https     -- the store does not answer.
"""

from __future__ import annotations

from datetime import datetime
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Final

from steam_backlog_enforcer._hosts_lines import (
    SINKHOLES,
    live_store_lines,
    store_lines,
)
from steam_backlog_enforcer._store_check_report import (
    REBLOCK,
    UNBLOCK,
    Check,
    StoreCheckReport,
)
from steam_backlog_enforcer._store_tools import IPTABLES, IPTABLES_CHAIN, SUDO
from steam_backlog_enforcer.config import BLOCKED_DOMAINS, HOSTS_FILE

if TYPE_CHECKING:
    from collections.abc import Callable

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
# Name resolution lags a hosts edit: systemd-resolved answered nothing for
# about 2 s after an unblock in vmbox, and a cache can still hold the real
# address right after a re-block. Probes repeat until they agree with the
# wanted result, at most this many times.
SETTLE_ATTEMPTS: Final = 3
_SETTLE_GAP_SECONDS: Final = 2.0


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


def _settled_https(url: str, *, want: bool) -> tuple[bool, str]:
    """Probe *url* until its reachability is *want* (or attempts run out)."""
    for attempt in range(SETTLE_ATTEMPTS):
        if attempt:
            time.sleep(_SETTLE_GAP_SECONDS)
        reachable, detail = https_reachable(url)
        if reachable == want:
            break
    return reachable, detail


def _leaks() -> dict[str, str]:
    """Store domains resolving to a real address (no answer counts as blocked).

    systemd-resolved answers a sinkholed name with no address at all rather
    than ``0.0.0.0``; either way nothing can connect.
    """
    leaks = {}
    for domain in BLOCKED_DOMAINS:
        addrs, _ = resolve(domain)
        if not addrs <= SINKHOLES:
            leaks[domain] = ",".join(sorted(addrs))
    return leaks


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
    store_ok, store_detail = _settled_https(STORE_URL, want=True)
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
    """Run the re-block checks once (each probe settles, see SETTLE_ATTEMPTS)."""
    leaks = _leaks()
    for _ in range(SETTLE_ATTEMPTS - 1):
        if not leaks:
            break
        time.sleep(_SETTLE_GAP_SECONDS)
        leaks = _leaks()
    store_open, detail = _settled_https(STORE_URL, want=False)
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
