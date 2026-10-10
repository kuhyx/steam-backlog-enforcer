"""Wire format shared by the daemon's control socket and its client.

One JSON object per line in, one per line out, then the connection closes.
Kept free of every enforcer import so the unprivileged web server can load the
client without dragging the root daemon's modules (and their side effects) in.

Error codes are the contract's (``DOCS-web-control-api.md``) plus two that only
the daemon can raise: ``op_failed`` (the privileged action ran and failed) and
``unsupported`` (the daemon is not supervised, so a restart would be a stop).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

SOCKET_PATH: Final = Path("/run/steam-backlog-enforcer/ctl.sock")

# A request is a few short fields; anything bigger is a mistake or an attack.
MAX_REQUEST_BYTES: Final = 4096
# The longest legitimate response is journal_tail at its cap.
MAX_RESPONSE_BYTES: Final = 1024 * 1024

# Error codes.
WRONG_PHRASE: Final = "wrong_phrase"
INVALID_PARAMS: Final = "invalid_params"
UNKNOWN_OP: Final = "unknown_command"
LOCKED: Final = "locked"
BUSY: Final = "busy"
COUNTDOWN_RUNNING: Final = "countdown_running"
PENDING_LAPSED: Final = "pending_lapsed"
RATE_LIMITED: Final = "rate_limited"
OP_FAILED: Final = "op_failed"
UNSUPPORTED: Final = "unsupported"


class CtlError(Exception):
    """A request the daemon refused or could not carry out.

    Attributes:
        code: Machine-readable error code (see the constants above).
        message: Human-readable text, safe to show in the UI.
        data: Extra fields for the caller (e.g. ``retry_after_seconds``).
    """

    def __init__(
        self, code: str, message: str, data: dict[str, object] | None = None
    ) -> None:
        """Build the error.

        Args:
            code: Error code.
            message: Human-readable text.
            data: Optional extra fields carried alongside the error.
        """
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.data = data or {}


class DaemonUnreachableError(Exception):
    """The control socket is missing, refused us, or closed without answering."""


def encode_line(obj: dict[str, object]) -> bytes:
    """Serialise *obj* as one newline-terminated JSON line."""
    return json.dumps(obj, separators=(",", ":")).encode("utf-8") + b"\n"


def decode_line(raw: bytes) -> object:
    """Parse one JSON line.

    Raises:
        ValueError: If *raw* is not valid UTF-8 JSON.
    """
    return json.loads(raw.decode("utf-8"))


def ok_response(data: dict[str, object]) -> bytes:
    """The success line for *data*."""
    return encode_line({"ok": True, "data": data})


def error_response(error: CtlError) -> bytes:
    """The failure line for *error*."""
    body: dict[str, object] = {
        "ok": False,
        "error": error.code,
        "message": error.message,
    }
    if error.data:
        body["data"] = error.data
    return encode_line(body)
