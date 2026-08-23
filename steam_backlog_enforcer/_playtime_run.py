"""Running the privileged commands a playtime block needs.

One helper, shared by the mount side and the process-kill side, so the
"log the failure and carry on" policy is written once.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)


def _run(cmd: list[str]) -> bool:
    """Run a privileged command, reporting success.

    The single subprocess seam in this module, so tests can assert on exact
    argv without ever executing ``mount``.

    Args:
        cmd: Argument vector to execute.

    Returns:
        True if the command exited zero.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, check=False, timeout=15)
    except (OSError, subprocess.SubprocessError):
        logger.exception("Playtime block command failed: %s", cmd)
        return False
    if result.returncode != 0:
        logger.warning("Playtime block command exited %d: %s", result.returncode, cmd)
    return result.returncode == 0
