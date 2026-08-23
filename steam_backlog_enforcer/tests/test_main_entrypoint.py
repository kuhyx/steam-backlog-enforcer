"""Tests for the ``python -m steam_backlog_enforcer.main`` entry point.

The shim exists so the invocation string baked into ``run.sh`` and the systemd
unit keeps working now that ``main`` is a package rather than a module.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch


class TestMainModule:
    """The ``__main__`` shim that keeps ``python -m ...main`` working."""

    def test_module_is_importable(self) -> None:
        """Importing the shim must not execute main()."""
        with patch("steam_backlog_enforcer.main.main") as mock_main:
            entry = importlib.import_module("steam_backlog_enforcer.main.__main__")
            assert entry.main is not None
        mock_main.assert_not_called()

    def test_guard_is_present(self) -> None:
        """The shim calls main() behind a ``__main__`` guard.

        Executing the shim here would call ``main()`` for real, so the guard is
        asserted on the source instead -- the runtime behaviour it produces is
        covered end-to-end by the CLI's own tests.
        """
        source = (
            Path(__file__).resolve().parents[1] / "main" / "__main__.py"
        ).read_text()
        assert 'if __name__ == "__main__":' in source
        assert "main()" in source
