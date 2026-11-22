"""Run a command in a test and capture its text output."""

from __future__ import annotations

import subprocess


def run_captured(
    argv: list[str], env: dict[str, str], timeout: float = 30
) -> subprocess.CompletedProcess[str]:
    """Run *argv* under *env*, text output captured, never raising on exit code."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )
