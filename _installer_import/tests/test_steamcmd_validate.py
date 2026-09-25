import logging
import signal

from steam_installer.steamcmd_validate import run_steamcmd_validate


def test_run_steamcmd_validate_argv_and_result(monkeypatch):
    seen = {}

    def fake_run_logged(cmd, logger, timeout=None):
        seen["cmd"] = cmd
        seen["timeout"] = timeout
        return 0, "all good"

    monkeypatch.setattr(
        "steam_installer.steamcmd_validate.runlog.run_logged", fake_run_logged
    )

    result = run_steamcmd_validate(1771300, "krzys2000", logging.getLogger("t"))

    cmd = seen["cmd"]
    # The platform flag must precede +login, and no force_install_dir may appear:
    # it sets a LIBRARY ROOT and pointing it at the game dir caused the original
    # "Invalid platform" failure.
    assert cmd.index("+@sSteamCmdForcePlatformType") < cmd.index("+login")
    assert "force_install_dir" not in " ".join(cmd)
    assert cmd[cmd.index("+app_update") + 1 : cmd.index("+app_update") + 3] == [
        "1771300",
        "validate",
    ]
    assert result.completed and result.returncode == 0
    assert result.output == "all good"
    assert not result.crashed_on_install_script


def test_run_steamcmd_validate_detects_the_install_script_segfault(monkeypatch):
    """The known steamcmd bug kills the process with SIGSEGV; checking the
    signal beats grepping captured text for a message string."""
    monkeypatch.setattr(
        "steam_installer.steamcmd_validate.runlog.run_logged",
        lambda cmd, logger, timeout=None: (-signal.SIGSEGV, ""),
    )

    result = run_steamcmd_validate(1, "u", logging.getLogger("t"))

    assert result.crashed_on_install_script
    assert not result.completed
