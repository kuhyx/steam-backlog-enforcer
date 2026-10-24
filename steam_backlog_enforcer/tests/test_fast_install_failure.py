"""Tests for _fast_install_failure: a failed run explained in the installer's words.

The text is the BG3 run of 2026-10-23, which downloaded 160 GB and then
refused; all the job showed was a finished bar and "Succeeded".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_backlog_enforcer._fast_install_failure import failure_reason

if TYPE_CHECKING:
    from pathlib import Path

_REFUSAL = (
    "2026-10-23 22:33:13,889 ERROR   steam_installer: Refusing to mark "
    "Baldur's Gate 3 as installed:\n"
    "2026-10-23 22:33:13,889 ERROR   steam_installer:   - depot(s) 1419654 "
    "have no cached manifest -- the download did not finish\n"
    "2026-10-23 22:33:13,889 INFO    steam_installer: Restarting the Steam client...\n"
)


def _console(tmp_path: Path, run_log: Path) -> Path:
    console = tmp_path / "fast_install-1000.log"
    console.write_text(
        f"Run log: {tmp_path / 'old.log'}\n"
        " 99.99% /x/Gustav.pak (403.89 Mbit/s)\n"
        "Refusing to mark Baldur's Gate 3 as installed:\n"
        f"Run log (send this): {run_log}\n"
        "Restarting the Steam client...\n"
    )
    return console


def test_reason_is_the_run_logs_error_lines(tmp_path: Path) -> None:
    run_log = tmp_path / "run-1086940.log"
    hello = "2026-10-23 22:13:21,605 INFO    steam_installer: hi\n"
    run_log.write_text(hello + _REFUSAL)
    assert failure_reason(_console(tmp_path, run_log), 1) == (
        "Refusing to mark Baldur's Gate 3 as installed: - depot(s) 1419654 have "
        "no cached manifest -- the download did not finish"
    )


def test_without_a_run_log_the_last_console_line_is_shown(tmp_path: Path) -> None:
    console = tmp_path / "fast_install-0.log"
    console.write_text("Traceback (most recent call last):\nOSError: disk full\n")
    assert failure_reason(console, 1) == "exit 1: OSError: disk full"


def test_an_unreadable_console_log_still_names_the_exit(tmp_path: Path) -> None:
    assert failure_reason(tmp_path / "missing.log", 3) == "exit 3"
