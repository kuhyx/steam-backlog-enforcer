"""Tests for _web_auth — Host, Origin, token and the owner-only token file."""

from __future__ import annotations

from email.message import Message
import os
import stat

import pytest

from steam_backlog_enforcer import _web_auth
from steam_backlog_enforcer._web_errors import ApiError


def _headers(**fields: str) -> Message:
    message = Message()
    for name, value in fields.items():
        message[name] = value
    return message


class TestToken:
    def test_tokens_are_fresh_hex(self) -> None:
        first, second = _web_auth.new_token(), _web_auth.new_token()
        assert first != second
        assert len(first) == 64
        int(first, 16)

    def test_matching_token_passes(self) -> None:
        _web_auth.check_token("abc", "abc")

    @pytest.mark.parametrize("supplied", [None, "", "abd"])
    def test_missing_or_wrong_token_is_refused(self, supplied: str | None) -> None:
        with pytest.raises(ApiError) as err:
            _web_auth.check_token(supplied, "abc")
        assert err.value.code == "bad_token"


class TestTokenFile:
    def test_path_uses_the_runtime_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/x")
        path = _web_auth.token_path(8123)
        assert str(path) == "/run/x/steam-backlog-enforcer/web-8123.token"

    def test_path_falls_back_to_the_uid_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("XDG_RUNTIME_DIR")
        assert str(_web_auth.token_path(1)).startswith(f"/run/user/{os.getuid()}/")

    def test_written_owner_only_and_replaced(self) -> None:
        path = _web_auth.write_token_file("tok1", 9000)
        assert path.read_text(encoding="ascii") == "tok1\n"
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        _web_auth.write_token_file("tok2", 9000)
        assert path.read_text(encoding="ascii") == "tok2\n"
        assert not path.with_suffix(".tmp").exists()


class TestHostAndOrigin:
    def test_allowed_hosts(self) -> None:
        assert _web_auth.allowed_hosts(80) == {"127.0.0.1:80", "localhost:80"}

    def test_loopback_host_is_normalised(self) -> None:
        got = _web_auth.check_host(_headers(Host=" LocalHost:80 "), 80)
        assert got == "localhost:80"

    @pytest.mark.parametrize("fields", [{}, {"Host": "evil.example:80"}])
    def test_foreign_or_missing_host_is_refused(self, fields: dict[str, str]) -> None:
        with pytest.raises(ApiError) as err:
            _web_auth.check_host(_headers(**fields), 80)
        assert err.value.code == "bad_host"

    def test_same_origin_passes(self) -> None:
        _web_auth.check_origin(_headers(Origin="http://localhost:80"), "localhost:80")

    @pytest.mark.parametrize("fields", [{}, {"Origin": "http://evil.example"}])
    def test_other_origin_is_refused(self, fields: dict[str, str]) -> None:
        with pytest.raises(ApiError) as err:
            _web_auth.check_origin(_headers(**fields), "localhost:80")
        assert err.value.code == "bad_origin"


class TestInjectToken:
    def test_goes_right_after_head(self) -> None:
        out = _web_auth.inject_token(b"<html><HEAD lang=x><title>t</title>", "T")
        assert out == (
            b'<html><HEAD lang=x><meta name="sbe-token" content="T"><title>t</title>'
        )

    def test_prepended_without_a_head(self) -> None:
        out = _web_auth.inject_token(b"<p>x</p>", "T")
        assert out == b'<meta name="sbe-token" content="T"><p>x</p>'
