"""Reconcile an install with Steam's own bookkeeping via `steamcmd ... validate`.

Split out of recognize.py (250-line cap). `app_update <id> validate` hash-checks
existing files against the depot manifest and only fetches real deltas --
confirmed live against a real 90+ GB install, going from ~24% to ~41% credited
in one pass without redownloading from scratch.

Some titles ship a post-install script (installscript.vdf) that steamcmd runs
through a private, headless Proton setup. On at least one real title this hit a
confirmed steamcmd bug -- a stack-overflow segfault in the closed-source
steamclient.so error-handling path after the script evaluator reports failure
(the same stack frame repeating dozens of times). There's no known fix; the
caller detects that crash and finishes the manifest by hand instead
(:mod:`manifest_write`).
"""

from __future__ import annotations

import logging
import signal
from dataclasses import dataclass

from steam_installer import runlog


@dataclass
class ValidateResult:
    completed: bool
    crashed_on_install_script: bool
    returncode: int
    output: str = ""


def run_steamcmd_validate(
    appid: int,
    username: str,
    logger: logging.Logger,
) -> ValidateResult:
    """Run steamcmd's app_update ... validate.

    Takes no install dir on purpose. `force_install_dir` sets a Steam *library
    root*, not an install directory: pointing it at the game folder made
    steamcmd look for manifests in `<game>/steamapps/`, find none ("Loaded 0
    apps from install folder"), create that stray directory, and then fail the
    app with "Invalid platform" because it had no depot context for it. The app
    already lives in a registered library, so letting steamcmd use the real one
    is both correct and sufficient.

    Output is teed through a pty (see runlog) rather than captured: steamcmd
    prompts for a password and possibly a Steam Guard code on stdin, and prompt
    text written to a captured/buffered pipe never reaches the terminal -- the
    process looks hung with no visible request for input.

    The confirmed steamcmd install-script bug (see module docstring) kills
    the process with SIGSEGV -- Python reports that as returncode -11 on
    POSIX. Checking the signal directly is more reliable than grepping
    captured text for a message string.
    """
    cmd = [
        "steamcmd",
        # A Linux steamcmd refuses a Windows-only app with "Invalid platform"
        # unless told which platform to resolve depots for. Must precede +login.
        "+@sSteamCmdForcePlatformType",
        "windows",
        "+login",
        username,
        "+app_update",
        str(appid),
        "validate",
        "+quit",
    ]
    returncode, output = runlog.run_logged(cmd, logger, timeout=3600)
    crashed = returncode == -signal.SIGSEGV
    return ValidateResult(
        completed=returncode == 0,
        crashed_on_install_script=crashed,
        returncode=returncode,
        output=output,
    )
