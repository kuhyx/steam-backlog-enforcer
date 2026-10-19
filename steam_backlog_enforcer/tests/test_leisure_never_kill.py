"""The never-kill set: the desktop survives a forged or buggy now.json."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING
from unittest.mock import patch

from leisure_watch.facts import Focus, Now, Reason
import pytest

from steam_backlog_enforcer._leisure_kill import LeisureKiller
from steam_backlog_enforcer._leisure_never_kill import never_kill
from steam_backlog_enforcer._playtime_state import PlaytimeRules, PlaytimeState
from steam_backlog_enforcer._shadow import ShadowVerdict
from steam_backlog_enforcer.tests._isolate_leisure import leisure_proc
from steam_backlog_enforcer.tests._leisure_fake_proc import FakeProc, add_proc

if TYPE_CHECKING:
    from pathlib import Path

_PY = "/usr/bin/python3.14"
_RULES = PlaytimeRules(
    budget_seconds=100.0,
    warn_at=(),
    sigkill_after=30.0,
    count_launchers=False,
    enforcement=True,
    demo=False,
    leisure=True,
)
_SPENT = PlaytimeState(day_key="2026-11-02", seconds=100.0)


@pytest.fixture
def proc(tmp_path: Path) -> Path:
    return leisure_proc(tmp_path)


class TestNeverKill:
    @pytest.mark.parametrize(
        ("exe", "args", "why"),
        [
            ("/usr/bin/i3", ("i3",), "i3"),
            ("/usr/bin/i3bar", ("i3bar",), "i3bar"),
            ("/usr/bin/i3blocks", ("i3blocks",), "i3blocks"),
            ("/usr/lib/Xorg", ("Xorg", ":0"), "xorg"),
            ("/usr/bin/Xwayland", ("Xwayland",), "xwayland"),
            ("/usr/lib/systemd/systemd", ("systemd", "--user"), "systemd"),
            ("/usr/bin/dbus-broker", ("dbus-broker",), "dbus-broker"),
            ("/usr/bin/dbus-daemon", ("dbus-daemon",), "dbus-daemon"),
            ("/usr/bin/pipewire-pulse", ("pipewire-pulse",), "pipewire-pulse"),
            ("/usr/bin/pipewire", ("pipewire",), "pipewire"),
            ("/usr/bin/wireplumber", ("wireplumber",), "wireplumber"),
            ("/usr/bin/pulseaudio", ("pulseaudio",), "pulseaudio"),
            ("/usr/bin/sshd", ("sshd",), "sshd"),
            ("/usr/bin/ssh-agent", ("ssh-agent",), "ssh-agent"),
            ("/usr/bin/gpg-agent", ("gpg-agent",), "gpg-agent"),
            ("/usr/bin/tmux", ("tmux",), "tmux"),
            ("/usr/bin/screen", ("screen",), "screen"),
            ("/usr/bin/alacritty", ("alacritty",), "alacritty"),
            ("/usr/bin/kitty", ("kitty",), "kitty"),
            ("/usr/bin/xterm", ("xterm",), "xterm"),
            ("/usr/bin/foot", ("foot",), "foot"),
            ("/usr/bin/zsh", ("-zsh",), "zsh"),
            ("/usr/bin/bash", ("bash",), "bash"),
            ("/usr/bin/fish", ("fish",), "fish"),
            ("/usr/bin/sh", ("sh", "-c", "x"), "sh"),
            ("/usr/bin/sudo", ("sudo", "x"), "sudo"),
            ("/usr/bin/keepassxc", ("keepassxc",), "keepassxc"),
            ("/usr/bin/dunst", ("dunst",), "dunst"),
            ("/usr/lib/xfce4/notifyd/xfce4-notifyd", ("x",), "xfce4-notifyd"),
            ("/usr/bin/vim (deleted)", ("vim",), None),
            ("/usr/bin/mpv", ("mpv",), None),
            ("/usr/bin/shellcheck", ("shellcheck",), None),
            ("/usr/bin/screenkey", ("screenkey",), None),
            ("/opt/helium-browser-bin/helium", ("helium",), None),
        ],
    )
    def test_by_binary(
        self, proc: Path, exe: str, args: tuple[str, ...], why: str | None
    ) -> None:
        add_proc(proc, FakeProc(10, exe=exe, argv=args))
        assert never_kill(10) == why

    @pytest.mark.parametrize(
        ("args", "why"),
        [
            (("/usr/bin/python", "/usr/bin/terminator"), "terminator"),
            (("python3", "-m", "leisure_watch", "run"), "leisure_watch"),
            (
                ("python3", "/home/kuhy/.local/bin/daily-limits", "--sync"),
                "daily_limits",
            ),
            (("python3", "-m", "screen_locker._web"), "screen_locker"),
            (("python3", "/x/leetcode_guard_tray.py"), "leetcode_guard_tray"),
            (("python3", "-m", "wsg_grabber"), None),
            (("python3", "-c", "import leisure_watch"), None),
        ],
    )
    def test_by_python_script(
        self, proc: Path, args: tuple[str, ...], why: str | None
    ) -> None:
        add_proc(proc, FakeProc(10, exe=_PY, argv=args))
        assert never_kill(10) == why

    @pytest.mark.parametrize(
        ("exe", "args", "why"),
        [
            ("/home/kuhy/.local/share/claude/versions/2.1.302", ("x",), "claude"),
            ("/x/claude_agent_sdk/_bundled/claude", ("claude",), "claude"),
            (
                "/usr/bin/node",
                ("node", "/x/@anthropic-ai/claude-code/cli.js"),
                "claude",
            ),
            ("/usr/bin/node", ("node", "/x/server.js"), None),
            ("/usr/bin/node", ("node",), None),
        ],
    )
    def test_claude(
        self, proc: Path, exe: str, args: tuple[str, ...], why: str | None
    ) -> None:
        add_proc(proc, FakeProc(10, exe=exe, argv=args))
        assert never_kill(10) == why


class TestKillerRefuses:
    def test_a_forged_fact_cannot_kill_the_desktop(
        self, proc: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        add_proc(proc, FakeProc(10, exe="/usr/bin/i3", argv=("i3",)))
        add_proc(proc, FakeProc(11, exe="/usr/bin/alacritty", argv=("alacritty",)))
        add_proc(proc, FakeProc(12, exe="/usr/bin/mpv"))
        fact = Now(
            ts=0.0,
            seq=1,
            state="leisure",
            paused_by=None,
            reasons=(
                Reason("failclosed", "failclosed:x", 10, "x"),
                Reason("focus", "app:alacritty", 11, "x"),
                Reason("media", "app:mpv", 12, "mpv"),
            ),
            focus=Focus("i3", "", None, idle=False),
        )
        verdict = ShadowVerdict(paused_by=None, keys=("k",), fact=fact)
        records: list[tuple[str, dict[str, object]]] = []

        class Log:
            def record(self, event: str, **fields: object) -> None:
                records.append((event, fields))

        killer = LeisureKiller(Log())
        with patch.object(os, "kill") as kill, caplog.at_level(logging.WARNING):
            for stamp in (0.0, 3.0, 40.0):
                killer.enforce(_SPENT, _RULES, verdict=verdict, stamp=stamp)
        assert {c.args[0] for c in kill.call_args_list} == {12}
        refused = [f for e, f in records if e == "leisure_kill_refused"]
        assert sorted((f["pid"], f["name"]) for f in refused) == [
            (10, "i3"),
            (11, "alacritty"),
        ]
        assert sum("never killed" in r.getMessage() for r in caplog.records) == 2

    def test_a_refusal_without_a_log_only_warns(
        self, proc: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        add_proc(proc, FakeProc(10, exe="/usr/bin/i3", argv=("i3",)))
        reasons = (Reason("failclosed", "failclosed:x", 10, "x"),)
        fact = Now(0.0, 1, "leisure", None, reasons, Focus("i3", "", None, idle=False))
        verdict = ShadowVerdict(paused_by=None, keys=("k",), fact=fact)
        with patch.object(os, "kill") as kill, caplog.at_level(logging.WARNING):
            LeisureKiller(None).enforce(_SPENT, _RULES, verdict=verdict, stamp=0.0)
        kill.assert_not_called()
        assert "never killed" in caplog.text
