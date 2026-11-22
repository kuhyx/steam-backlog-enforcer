"""The external-binary check. Moved here from test_cli.py with the code it covers."""

import pytest

from steam_installer import deps


def test_nothing_missing_when_depotdownloader_is_on_path(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert deps.missing_tools() == []
    deps.require()


def test_steamcmd_is_never_required(monkeypatch):
    monkeypatch.setattr(
        deps.shutil, "which", lambda name: None if name == "steamcmd" else "/usr/bin/dd"
    )
    assert deps.missing_tools() == []


def test_missing_tool_raises_with_the_command_that_fixes_it(monkeypatch):
    monkeypatch.setattr(deps.shutil, "which", lambda name: None)

    with pytest.raises(deps.DependencyError) as excinfo:
        deps.require()

    message = str(excinfo.value)
    assert "depotdownloader" in message
    assert "steamcmd" not in message
    assert "./install.sh" in message
