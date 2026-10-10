"""Tests for ``_command_params``: the typed param table and its validation."""

from __future__ import annotations

import pytest

from steam_backlog_enforcer._command_params import (
    PARAMS,
    InvalidParamsError,
    ParamSpec,
    validate_params,
)


class TestToJson:
    """Contract serialisation omits unset optional keys."""

    def test_minimal(self) -> None:
        spec = ParamSpec("n", "N", "int")
        assert spec.to_json() == {
            "name": "n",
            "label": "N",
            "type": "int",
            "required": True,
        }

    def test_full(self) -> None:
        spec = ParamSpec(
            "n", "N", "int", required=False, min=0, max=9, default=0, help="h"
        )
        assert spec.to_json() == {
            "name": "n",
            "label": "N",
            "type": "int",
            "required": False,
            "min": 0,
            "max": 9,
            "default": 0,
            "help": "h",
        }


class TestValidateParams:
    """Coercion, bounds, defaults and unknown/missing params."""

    def test_command_without_params(self) -> None:
        assert validate_params("status", {}) == {}

    def test_unknown_param(self) -> None:
        with pytest.raises(InvalidParamsError, match=r"Unknown param.*x, y"):
            validate_params("status", {"y": 1, "x": 2})

    def test_missing_required(self) -> None:
        with pytest.raises(InvalidParamsError, match="Missing required param: days"):
            validate_params("block-gaming", {})

    def test_default_filled(self) -> None:
        assert validate_params("unblock", {}) == {"minutes": 15}

    def test_optional_without_default_is_omitted(self) -> None:
        optional = ParamSpec("o", "O", "string", required=False)
        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(PARAMS, "probe", (optional,))
            assert validate_params("probe", {}) == {}

    def test_int_from_string(self) -> None:
        assert validate_params("block-gaming", {"days": " 7 "}) == {"days": 7}

    def test_string_is_stripped(self) -> None:
        assert validate_params("restore-backup", {"backup_id": " b1 "}) == {
            "backup_id": "b1"
        }

    @pytest.mark.parametrize("raw", ["", "   ", 5, None])
    def test_string_must_be_text(self, raw: object) -> None:
        with pytest.raises(InvalidParamsError, match="non-empty string"):
            validate_params("restore-backup", {"backup_id": raw})

    @pytest.mark.parametrize("raw", [True, 1.5, None, [1]])
    def test_int_must_be_integer_like(self, raw: object) -> None:
        with pytest.raises(InvalidParamsError, match="whole number"):
            validate_params("block-gaming", {"days": raw})

    def test_int_text_must_parse(self) -> None:
        with pytest.raises(InvalidParamsError, match="got 'abc'"):
            validate_params("block-gaming", {"days": "abc"})

    def test_below_min(self) -> None:
        with pytest.raises(InvalidParamsError, match="at least 1"):
            validate_params("block-gaming", {"days": 0})

    def test_above_max(self) -> None:
        with pytest.raises(InvalidParamsError, match="at most 30"):
            validate_params("unblock", {"minutes": 31})

    def test_boundaries_accepted(self) -> None:
        assert validate_params("unblock", {"minutes": 30}) == {"minutes": 30}
        assert validate_params("enforce", {"demo": 0}) == {"demo": 0}
