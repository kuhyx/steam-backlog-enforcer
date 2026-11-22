"""The result of a store unblock / re-block check, and its failure report.

Kept apart from the checks themselves (``_store_verify``) so the report a
todo task is filed from has one plain home: which checks ran, which failed,
and the evidence gathered for a failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

UNBLOCK: Final = "unblock"
REBLOCK: Final = "re-block"
NETWORK_DOWN: Final = "network down"


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
