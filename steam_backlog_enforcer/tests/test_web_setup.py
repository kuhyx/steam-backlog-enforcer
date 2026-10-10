"""Tests for _web_setup — credentials are saved only after Steam accepts them."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from steam_backlog_enforcer import _web_setup
from steam_backlog_enforcer import config as _config
from steam_backlog_enforcer._web_errors import ApiError
from steam_backlog_enforcer.tests._web_request import make_request, payload_of

if TYPE_CHECKING:
    from steam_backlog_enforcer._web_io import Request

_PKG = "steam_backlog_enforcer._web_setup"
_KEY = "0123456789abcdef0123456789ABCDEF"
_ID = "76561190000000001"


def _steam(status: int = 200, body: object = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    if isinstance(body, Exception):
        resp.json.side_effect = body
    else:
        resp.json.return_value = body
    return resp


def _players(*names: str) -> dict[str, Any]:
    return {"response": {"players": [{"personaname": n} for n in names]}}


class TestField:
    def test_returns_the_stripped_value(self) -> None:
        request = make_request(body={"steam_id": f" {_ID} "})
        got = _web_setup._field(request, "steam_id", _web_setup._STEAM_ID, "an id")
        assert got == _ID

    @pytest.mark.parametrize("raw", [None, 5, "", "abc"])
    def test_rejects_missing_or_malformed(self, raw: object) -> None:
        request = make_request(body={"steam_id": raw})
        with pytest.raises(ApiError) as err:
            _web_setup._field(request, "steam_id", _web_setup._STEAM_ID, "an id")
        assert err.value.code == "invalid_params"


class TestVerifyWithSteam:
    def test_accepts_a_known_account(self) -> None:
        with patch(f"{_PKG}.requests.get", return_value=_steam(200, _players("x"))):
            _web_setup.verify_with_steam(_KEY, _ID)

    def test_network_failure_is_op_failed(self) -> None:
        with (
            patch(f"{_PKG}.requests.get", side_effect=requests.Timeout),
            pytest.raises(ApiError) as err,
        ):
            _web_setup.verify_with_steam(_KEY, _ID)
        assert err.value.code == "op_failed"
        assert "Timeout" in err.value.message

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_key(self, status: int) -> None:
        with (
            patch(f"{_PKG}.requests.get", return_value=_steam(status)),
            pytest.raises(ApiError) as err,
        ):
            _web_setup.verify_with_steam(_KEY, _ID)
        assert (err.value.code, err.value.message) == (
            "invalid_params",
            "Steam rejected this API key.",
        )

    def test_other_http_status(self) -> None:
        with (
            patch(f"{_PKG}.requests.get", return_value=_steam(500)),
            pytest.raises(ApiError) as err,
        ):
            _web_setup.verify_with_steam(_KEY, _ID)
        assert err.value.code == "op_failed"

    @pytest.mark.parametrize(
        "reply",
        [_steam(200, ValueError()), _steam(200, {}), _steam(200, {"response": None})],
    )
    def test_unexpected_reply_shape(self, reply: MagicMock) -> None:
        with (
            patch(f"{_PKG}.requests.get", return_value=reply),
            pytest.raises(ApiError) as err,
        ):
            _web_setup.verify_with_steam(_KEY, _ID)
        assert err.value.code == "op_failed"

    def test_unknown_account(self) -> None:
        with (
            patch(f"{_PKG}.requests.get", return_value=_steam(200, _players())),
            pytest.raises(ApiError) as err,
        ):
            _web_setup.verify_with_steam(_KEY, _ID)
        assert err.value.code == "invalid_params"


class TestSaveSetup:
    _LOCK = "steam_backlog_enforcer._web_setup.lock_reason"

    def _request(self, **body: str) -> Request:
        return make_request(
            body={"steam_api_key": _KEY, "steam_id": _ID, **body}, method="POST"
        )

    def test_bad_key_is_refused_first(self) -> None:
        with pytest.raises(ApiError) as err:
            _web_setup.save_setup(self._request(steam_api_key="short"))
        assert "steam_api_key" in err.value.message

    def test_bad_steam_id_is_refused(self) -> None:
        with pytest.raises(ApiError) as err:
            _web_setup.save_setup(self._request(steam_id="1"))
        assert "steam_id" in err.value.message

    def test_a_locked_setup_is_refused_before_asking_steam(self) -> None:
        with (
            patch(self._LOCK, return_value="Total block"),
            patch(f"{_PKG}.verify_with_steam") as verify,
            pytest.raises(ApiError) as err,
        ):
            _web_setup.save_setup(self._request())
        assert err.value.code == "locked"
        verify.assert_not_called()

    def test_steam_refusal_saves_nothing(self) -> None:
        with (
            patch(self._LOCK, return_value=None),
            patch(
                f"{_PKG}.verify_with_steam",
                side_effect=ApiError("no", code="invalid_params"),
            ),
            patch(f"{_PKG}.save_credentials") as save,
            pytest.raises(ApiError),
        ):
            _web_setup.save_setup(self._request())
        save.assert_not_called()

    def test_saves_and_never_echoes_the_key(self) -> None:
        with (
            patch(self._LOCK, return_value=None),
            patch(f"{_PKG}.verify_with_steam"),
        ):
            reply = _web_setup.save_setup(self._request())
        assert payload_of(reply) == {
            "configured": True,
            "has_api_key": True,
            "steam_id": _ID,
        }
        assert _KEY in _config.CONFIG_FILE.read_text(encoding="utf-8")
        assert _KEY not in str(reply.payload)
