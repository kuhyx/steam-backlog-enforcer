"""Base class of every error this package raises on purpose, and the crash guard."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import logging
    from pathlib import Path
    from types import TracebackType


class InstallerError(Exception):
    """A failure the installer reports and exits on, as opposed to a bug."""


class CrashGuard:
    """Context manager: log any ``Exception`` with the run-log path, swallow it.

    ``try/except Exception`` would say the same, but pylint's broad-exception
    check rejects it. ``KeyboardInterrupt`` and other ``BaseException`` pass.
    """

    def __init__(self, logger: logging.Logger, log_path: Path) -> None:
        """Remember where a crash is reported."""
        self.logger = logger
        self.log_path = log_path

    def __enter__(self) -> None:
        """Nothing to set up."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        """Report an ``Exception`` and swallow it; let everything else pass."""
        if not isinstance(exc, Exception):
            return False
        self.logger.error(
            "Run failed with an unhandled error", exc_info=(exc_type, exc, tb)
        )
        self.logger.info("Run log (send this): %s", self.log_path)
        return True
