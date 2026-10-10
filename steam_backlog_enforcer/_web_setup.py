"""``POST /api/setup``: store the Steam credentials, after Steam accepts them.

The CLI's setup writes whatever is typed; the web form checks first, so a
typo cannot leave the enforcer with a key that fails on its next pass. One
``GetPlayerSummaries`` call proves both halves: Steam answers 401/403 for a
bad key, and an empty ``players`` list for a SteamID it does not know.
Nothing is written unless that call succeeds, and the key is never echoed
back — the reply is the same ``SetupStatus`` that ``GET`` serves.
"""

from __future__ import annotations

from http import HTTPStatus
import re
from typing import TYPE_CHECKING, Final

import requests

from steam_backlog_enforcer._command_gate import lock_reason
from steam_backlog_enforcer._config_setup import save_credentials
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer._web_io import Reply, ok
from steam_backlog_enforcer._web_views import setup_status
from steam_backlog_enforcer.config import Config, State

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Request

_SUMMARIES_URL: Final = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
_TIMEOUT_SECONDS: Final = 15
_API_KEY = re.compile(r"^[0-9A-Fa-f]{32}$")
_STEAM_ID = re.compile(r"^7656119\d{10}$")


def _field(request: Request, name: str, pattern: re.Pattern[str], what: str) -> str:
    """One validated, stripped string field of the body.

    Raises:
        ApiError: ``invalid_params`` when it is missing or malformed.
    """
    raw = request.body.get(name)
    value = raw.strip() if isinstance(raw, str) else ""
    if not pattern.fullmatch(value):
        msg = f"{name} must be {what}."
        raise ApiError(msg, code="invalid_params")
    return value


def verify_with_steam(api_key: str, steam_id: str) -> None:
    """Ask Steam whether *api_key* works and *steam_id* exists.

    Raises:
        ApiError: ``invalid_params`` for a rejected key or unknown id,
            ``op_failed`` (502) when Steam cannot be asked at all.
    """
    try:
        resp = requests.get(
            _SUMMARIES_URL,
            params={"key": api_key, "steamids": steam_id},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        msg = (
            f"Could not reach the Steam Web API to check the key: {type(exc).__name__}."
        )
        raise ApiError(msg, code="op_failed") from None
    if resp.status_code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
        msg = "Steam rejected this API key."
        raise ApiError(msg, code="invalid_params")
    if resp.status_code != HTTPStatus.OK:
        msg = f"The Steam Web API answered HTTP {resp.status_code}; try again."
        raise ApiError(msg, code="op_failed")
    try:
        players = resp.json()["response"]["players"]
    except ValueError, KeyError, TypeError:
        msg = "The Steam Web API sent an unexpected reply."
        raise ApiError(msg, code="op_failed") from None
    if not players:
        msg = "Steam knows no account with this SteamID64."
        raise ApiError(msg, code="invalid_params")


def save_setup(request: Request) -> Reply:
    """``POST /api/setup`` — validate live, then save like the CLI does."""
    api_key = _field(request, "steam_api_key", _API_KEY, "a 32-character hex key")
    steam_id = _field(request, "steam_id", _STEAM_ID, "a 17-digit SteamID64")
    reason = lock_reason("setup", Config.load(), State.load())
    if reason is not None:
        raise ApiError(reason, code="locked")
    verify_with_steam(api_key, steam_id)
    return ok(setup_status(save_credentials(api_key, steam_id)))
