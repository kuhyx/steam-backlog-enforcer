"""Typed parameters of the commands the web UI can run.

The CLI parses ``sys.argv`` per command; the web sends a flat JSON object.
This table is the one description of that object, used twice: the command
catalog serves it to the UI as ``ParamSpec[]`` (so forms are server-driven),
and the job store validates every request against it before a job exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from steam_backlog_enforcer._store_window import (
    DEFAULT_WINDOW_MINUTES,
    MAX_WINDOW_MINUTES,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

ParamType = Literal["int", "string", "app_id"]
ParamValue = int | str


@dataclass(frozen=True)
class ParamSpec:
    """One parameter, shaped like the TS ``ParamSpec`` contract type."""

    name: str
    label: str
    type: ParamType
    required: bool = True
    min: int | None = None
    max: int | None = None
    default: ParamValue | None = None
    help: str | None = None

    def to_json(self) -> dict[str, object]:
        """Return the contract object, omitting unset optional keys."""
        out: dict[str, object] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "required": self.required,
        }
        for key in ("min", "max", "default", "help"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


_APP_ID = ParamSpec("app_id", "Steam app id", "app_id", min=1)

PARAMS: Final[dict[str, tuple[ParamSpec, ...]]] = {
    "pick-manual": (_APP_ID,),
    "abandon-pick": (_APP_ID,),
    "add-exception": (
        _APP_ID,
        ParamSpec(
            "reason",
            "Reason",
            "string",
            help="A genuine justification of at least 5 words.",
        ),
    ),
    "block-gaming": (ParamSpec("days", "Days", "int", min=1),),
    "unblock": (
        ParamSpec(
            "minutes",
            "Minutes",
            "int",
            required=False,
            min=1,
            max=MAX_WINDOW_MINUTES,
            default=DEFAULT_WINDOW_MINUTES,
        ),
    ),
    # Only the 60-second demo budget runs as a job; restarting the real
    # enforcer is the daemon's job.
    "enforce": (
        ParamSpec(
            "demo",
            "Demo mode (1 = 60-second budget)",
            "int",
            required=False,
            min=0,
            max=1,
            default=0,
        ),
    ),
    # Not a CLI command: POST /api/backups/{id}/restore runs it as a job.
    "restore-backup": (ParamSpec("backup_id", "Backup id", "string"),),
}


class InvalidParamsError(ValueError):
    """A request's params do not match the command's :class:`ParamSpec` list."""


def _coerce(spec: ParamSpec, raw: object) -> ParamValue:
    """Convert one raw JSON value to the spec's type, enforcing its bounds."""
    if spec.type == "string":
        if not isinstance(raw, str) or not raw.strip():
            msg = f"{spec.name} must be a non-empty string"
            raise InvalidParamsError(msg)
        return raw.strip()
    # bool is an int subclass in Python; true/false is never a count.
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        msg = f"{spec.name} must be a whole number"
        raise InvalidParamsError(msg)
    try:
        value = int(raw)
    except ValueError as exc:
        msg = f"{spec.name} must be a whole number, got {raw!r}"
        raise InvalidParamsError(msg) from exc
    if spec.min is not None and value < spec.min:
        msg = f"{spec.name} must be at least {spec.min}"
        raise InvalidParamsError(msg)
    if spec.max is not None and value > spec.max:
        msg = f"{spec.name} must be at most {spec.max}"
        raise InvalidParamsError(msg)
    return value


def validate_params(
    command: str, params: Mapping[str, object]
) -> dict[str, ParamValue]:
    """Return *params* coerced to their declared types, defaults filled in.

    Raises:
        InvalidParamsError: On an unknown, missing or out-of-range param.
    """
    specs = PARAMS.get(command, ())
    unknown = set(params) - {spec.name for spec in specs}
    if unknown:
        msg = f"Unknown param(s) for {command}: {', '.join(sorted(unknown))}"
        raise InvalidParamsError(msg)
    clean: dict[str, ParamValue] = {}
    for spec in specs:
        if spec.name in params:
            clean[spec.name] = _coerce(spec, params[spec.name])
        elif spec.default is not None:
            clean[spec.name] = spec.default
        elif spec.required:
            msg = f"Missing required param: {spec.name}"
            raise InvalidParamsError(msg)
    return clean
