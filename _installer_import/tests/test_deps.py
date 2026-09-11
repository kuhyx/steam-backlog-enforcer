"""The external-binary check. Moved here from test_cli.py with the code it covers."""

import pytest

from steam_installer import deps


def test_nothing_missing_when_both_tools_are_on_path(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert deps.missing_tools(skip_steamcmd=False) == []
    deps.require(skip_steamcmd=False)


def test_steamcmd_is_not_required_when_it_is_skipped(monkeypatch):
    monkeypatch.setattr(
        deps.shutil, "which", lambda name: None if name == "steamcmd" else "/usr/bin/dd"
    )
    assert deps.missing_tools(skip_steamcmd=True) == []
    assert deps.missing_tools(skip_steamcmd=False) == ["steamcmd"]


def test_missing_tool_raises_with_the_command_that_fixes_it(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    with pytest.raises(deps.DependencyError) as excinfo:
        deps.require(skip_steamcmd=False)

    message = str(excinfo.value)
    assert "depotdownloader" in message
    assert "steamcmd" in message
    assert "./install.sh" in message
