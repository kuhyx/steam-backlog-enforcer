"""Shared test setup.

`test_module_is_runnable_as_a_script` runs `python -m steam_installer.cli` in a
subprocess. Without the hook below, coverage collected in that child is thrown
away and the `__main__` guard looks uncovered.
"""

import os
import pathlib

import pytest


@pytest.fixture
def coverage_subprocess_env():
    """Env for a child process that should also record coverage."""
    env = os.environ.copy()
    root = pathlib.Path(__file__).resolve().parent.parent
    env["COVERAGE_PROCESS_START"] = str(root / "pyproject.toml")
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    return env
