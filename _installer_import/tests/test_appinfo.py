import pytest

from steam_installer import appinfo


def _app_block(monkeypatch, block):
    monkeypatch.setattr(appinfo, "_fetch_app_block", lambda appid: block)


# Shape taken from a real `app_info_print 1771300`: 12 depots, of which an
# english/windows install only ever fetches three.
KCD2_DEPOTS = {
    "228989": {"depotfromapp": "228980", "config": {"oslist": "windows"}},
    "1771302": {"config": {"oslist": "windows"}},
    "1771303": {"config": {"oslist": "windows"}},
    "1771304": {"dlcappid": "3406020", "config": {"oslist": "windows"}},
    "1771305": {"config": {"oslist": "windows", "language": "czech"}},
    "1771306": {"config": {"oslist": "windows", "language": "english"}},
    "1771307": {"config": {"oslist": "windows", "language": "french"}},
    "4075290": {"dlcappid": "4075290"},
    "branches": {"public": {"buildid": "23914554"}},
}


def test_get_depot_plan_selects_only_this_language_and_os(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})

    plan = appinfo.get_depot_plan(1771300, language="english", os_name="windows")

    assert plan.required == {"1771302", "1771303", "1771306"}
    assert plan.shared == {"228989"}
    assert plan.all_expected == {"1771302", "1771303", "1771306", "228989"}


def test_get_depot_plan_switches_language(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    plan = appinfo.get_depot_plan(1771300, language="czech")
    assert "1771305" in plan.required
    assert "1771306" not in plan.required


def test_get_depot_plan_excludes_other_os(monkeypatch):
    _app_block(
        monkeypatch,
        {"depots": {"10": {"config": {"oslist": "linux"}}, "11": {"config": {}}}},
    )
    plan = appinfo.get_depot_plan(1771300, os_name="windows")
    assert plan.required == {"11"}


def test_get_depot_plan_skips_optional_depots(monkeypatch):
    _app_block(monkeypatch, {"depots": {"10": {"optional": "1"}, "11": {}}})
    assert appinfo.get_depot_plan(1771300).required == {"11"}


def test_get_depot_plan_rejects_malformed_depots_section(monkeypatch):
    _app_block(monkeypatch, {"depots": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="depots"):
        appinfo.get_depot_plan(1771300)


def test_get_depot_plan_with_no_depots_is_empty(monkeypatch):
    """An app with no depot list yields nothing required -- callers must not
    read that as "everything downloaded fine"."""
    _app_block(monkeypatch, {})
    plan = appinfo.get_depot_plan(1771300)
    assert plan.required == set()
    assert plan.shared == set()


def test_get_build_id_reads_public_branch(monkeypatch):
    _app_block(monkeypatch, {"depots": KCD2_DEPOTS})
    assert appinfo.get_build_id(1771300) == "23914554"


def test_get_build_id_missing_branch_returns_none(monkeypatch):
    _app_block(monkeypatch, {"depots": {"branches": {}}})
    assert appinfo.get_build_id(1771300) is None


def test_get_build_id_without_depots_returns_none(monkeypatch):
    _app_block(monkeypatch, {})
    assert appinfo.get_build_id(1771300) is None


def test_get_metadata_reads_name_and_installdir(monkeypatch):
    _app_block(
        monkeypatch,
        {
            "common": {
                "name": "Kingdom Come: Deliverance II",
                "installdir": "KingdomComeDeliverance2",
            }
        },
    )
    metadata = appinfo.get_metadata(1771300)
    assert metadata.name == "Kingdom Come: Deliverance II"
    assert metadata.installdir == "KingdomComeDeliverance2"


def test_get_metadata_falls_back_to_config_installdir(monkeypatch):
    _app_block(
        monkeypatch,
        {"common": {"name": "Game"}, "config": {"installdir": "GameDir"}},
    )
    assert appinfo.get_metadata(1).installdir == "GameDir"


def test_get_metadata_requires_name(monkeypatch):
    _app_block(monkeypatch, {"common": {"installdir": "GameDir"}})
    with pytest.raises(appinfo.AppInfoError, match="no name field"):
        appinfo.get_metadata(1)


def test_get_metadata_requires_installdir(monkeypatch):
    _app_block(monkeypatch, {"common": {"name": "Game"}})
    with pytest.raises(appinfo.AppInfoError, match="no installdir"):
        appinfo.get_metadata(1)


def test_get_metadata_rejects_malformed_common_section(monkeypatch):
    _app_block(monkeypatch, {"common": "not-a-dict"})
    with pytest.raises(appinfo.AppInfoError, match="no 'common' section"):
        appinfo.get_metadata(1)


class _FakeCompleted:
    def __init__(self, stdout):
        self.stdout = stdout
        self.returncode = 0


# What steamcmd actually emits: its own log lines, then the VDF block.
STEAMCMD_OUTPUT = """Redirecting stderr to '/home/u/.steam/logs/stderr.txt'
Logging directory: '/home/u/.steam/logs'
"@sSteamCmdForcePlatformType" = "windows"
Logging in user 'anonymous' to Steam Public...OK
"1771300"
{
\t"common"
\t{
\t\t"name"\t\t"Kingdom Come: Deliverance II"
\t\t"installdir"\t\t"KingdomComeDeliverance2"
\t}
\t"depots"
\t{
\t\t"1771303"
\t\t{
\t\t\t"config"
\t\t\t{
\t\t\t\t"oslist"\t\t"windows"
\t\t\t}
\t\t}
\t\t"branches"
\t\t{
\t\t\t"public"
\t\t\t{
\t\t\t\t"buildid"\t\t"23914554"
\t\t\t}
\t\t}
\t}
}
"""


def test_fetch_app_block_parses_real_steamcmd_output(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return _FakeCompleted(STEAMCMD_OUTPUT)

    monkeypatch.setattr(appinfo.subprocess, "run", fake_run)

    metadata = appinfo.get_metadata(1771300)

    assert metadata.name == "Kingdom Come: Deliverance II"
    assert metadata.installdir == "KingdomComeDeliverance2"
    # The platform flag must precede +login or a Windows-only app comes back empty.
    cmd = seen["cmd"]
    assert cmd.index("+@sSteamCmdForcePlatformType") < cmd.index("+login")
    assert cmd[cmd.index("+@sSteamCmdForcePlatformType") + 1] == "windows"


def test_get_build_id_through_the_real_parser(monkeypatch):
    monkeypatch.setattr(
        appinfo.subprocess, "run", lambda cmd, **kw: _FakeCompleted(STEAMCMD_OUTPUT)
    )
    assert appinfo.get_build_id(1771300) == "23914554"


def test_fetch_app_block_raises_when_appid_header_absent(monkeypatch):
    """steamcmd prints its usual log noise even for an unknown app; without the
    `"<appid>"` header there is no app info to parse."""
    monkeypatch.setattr(
        appinfo.subprocess,
        "run",
        lambda cmd, **kw: _FakeCompleted("Logging in user 'anonymous'...OK\n"),
    )
    with pytest.raises(appinfo.AppInfoError, match="did not return app info"):
        appinfo.get_metadata(999999999)


def test_fetch_app_block_raises_when_block_is_not_a_mapping(monkeypatch):
    """Defensive guard against a shape vdf.parse cannot currently produce (it
    always yields a dict for a `{ ... }` block). Exercised by injecting a parser
    that returns a scalar, so the guard stays correct if vdf ever changes."""
    monkeypatch.setattr(
        appinfo.subprocess,
        "run",
        lambda cmd, **kw: _FakeCompleted('"1771300"\n{\n}\n'),
    )
    monkeypatch.setattr(appinfo.vdf, "parse", lambda text: {"1771300": "scalar"})

    with pytest.raises(appinfo.AppInfoError, match="unexpected app_info_print"):
        appinfo.get_metadata(1771300)


def test_get_build_id_handles_non_dict_sections(monkeypatch):
    for text in (
        '"1"\n{\n\t"depots"\t\t"scalar"\n}\n',
        '"1"\n{\n\t"depots"\n\t{\n\t\t"branches"\t\t"scalar"\n\t}\n}\n',
        '"1"\n{\n\t"depots"\n\t{\n\t\t"branches"\n\t\t{\n\t\t\t"public"\t\t"x"\n\t\t}\n\t}\n}\n',
    ):
        monkeypatch.setattr(
            appinfo.subprocess, "run", lambda cmd, _t=text, **kw: _FakeCompleted(_t)
        )
        assert appinfo.get_build_id(1) is None


def test_get_build_id_returns_none_when_buildid_not_a_string(monkeypatch):
    text = '"1"\n{\n\t"depots"\n\t{\n\t\t"branches"\n\t\t{\n\t\t\t"public"\n\t\t\t{\n\t\t\t\t"buildid"\n\t\t\t\t{\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n'
    monkeypatch.setattr(
        appinfo.subprocess, "run", lambda cmd, **kw: _FakeCompleted(text)
    )
    assert appinfo.get_build_id(1) is None
