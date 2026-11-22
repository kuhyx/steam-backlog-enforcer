"""Per-game CompatToolMapping entries, inserted into config.vdf as text."""

import pytest

from steam_installer import compat_map

HEAD = '''"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"SecretToken"\t\t"do-not-print-me"
'''
TAIL = '''\t\t\t}
\t\t}
\t}
\t"Music"
\t{
\t\t"CompatToolMapping"\t\t"decoy outside the Steam block"
\t}
}
'''


def _entry(appid, name, priority, indent="\t\t\t\t\t"):
    return (
        f'{indent}"{appid}"\n{indent}{{\n'
        f'{indent}\t"name"\t\t"{name}"\n{indent}\t"config"\t\t""\n'
        f'{indent}\t"priority"\t\t"{priority}"\n{indent}}}\n'
    )


def _config(tmp_path, mapping=None):
    body = HEAD
    if mapping is not None:
        body += '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n' + mapping + "\t\t\t\t}\n"
    path = tmp_path / "config.vdf"
    path.write_text(body + TAIL)
    path.chmod(0o600)
    return path


@pytest.fixture(autouse=True)
def _steam_closed(monkeypatch):
    monkeypatch.setattr(compat_map.recognize, "steam_client_pids", list)


def test_adds_the_block_when_there_is_none(tmp_path):
    path = _config(tmp_path)
    before = path.read_text()

    outcome = compat_map.map_app(path, 1201270)

    assert outcome.action == "mapped"
    text = path.read_text()
    assert compat_map.current(path, 1201270) == ("proton-cachyos-native", "250")
    # Everything Steam wrote is still there byte for byte.
    assert text.replace(_mapping_block(1201270), "") == before
    assert path.stat().st_mode & 0o777 == 0o600


def _mapping_block(appid):
    return (
        '\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n'
        + _entry(appid, "proton-cachyos-native", "250")
        + "\t\t\t\t}\n"
    )


def test_adds_an_entry_to_an_existing_block(tmp_path):
    path = _config(tmp_path, _entry(10, "proton_9", "250"))
    assert compat_map.map_app(path, 20).action == "mapped"
    assert compat_map.current(path, 10) == ("proton_9", "250")
    assert compat_map.current(path, 20) == ("proton-cachyos-native", "250")


def test_replaces_valves_own_choice(tmp_path):
    path = _config(tmp_path, _entry(20, "proton_experimental", "100"))
    outcome = compat_map.map_app(path, 20)
    assert outcome.action == "mapped"
    assert "proton_experimental" in outcome.detail
    assert compat_map.current(path, 20) == ("proton-cachyos-native", "250")
    assert path.read_text().count('"20"') == 1


def test_replaces_an_empty_entry(tmp_path):
    path = _config(tmp_path, _entry(20, "", "250"))
    assert compat_map.map_app(path, 20).action == "mapped"
    assert compat_map.current(path, 20) == ("proton-cachyos-native", "250")


def test_keeps_a_tool_kuhy_picked_himself(tmp_path):
    path = _config(tmp_path, _entry(20, "GE-Proton10", "250"))
    before = path.read_text()
    outcome = compat_map.map_app(path, 20)
    assert outcome.action == "kept"
    assert "GE-Proton10" in outcome.detail
    assert path.read_text() == before


def test_a_second_run_changes_nothing(tmp_path):
    path = _config(tmp_path)
    compat_map.map_app(path, 20)
    once = path.read_text()
    assert compat_map.map_app(path, 20).action == "already"
    assert path.read_text() == once


def test_refuses_while_steam_runs(tmp_path, monkeypatch):
    path = _config(tmp_path)
    before = path.read_text()
    monkeypatch.setattr(compat_map.recognize, "steam_client_pids", lambda: [7])
    with pytest.raises(compat_map.CompatMapError, match="Steam is running"):
        compat_map.map_app(path, 20)
    assert path.read_text() == before


@pytest.mark.parametrize(
    "text",
    [
        '"InstallConfigStore"\n{\n}\n',
        '"InstallConfigStore"\n{\n\t"Software" { }\n}\n',
        '"InstallConfigStore"\n{\n\t}\n\t}\n',
        '{\n}\n',
    ],
)
def test_an_unexpected_layout_is_refused_without_echoing_lines(tmp_path, text):
    path = tmp_path / "config.vdf"
    path.write_text(text + '"x"\t"do-not-print-me"\n')
    with pytest.raises(compat_map.CompatMapError) as excinfo:
        compat_map.map_app(path, 20)
    assert "do-not-print-me" not in str(excinfo.value)


def test_missing_config_is_an_error(tmp_path):
    with pytest.raises(compat_map.CompatMapError, match="cannot read"):
        compat_map.current(tmp_path / "nope.vdf", 1)


def test_current_is_none_for_an_unmapped_app(tmp_path):
    assert compat_map.current(_config(tmp_path), 20) is None
    assert compat_map.current(_config(tmp_path, _entry(10, "x", "1")), 20) is None


def test_keys_match_case_insensitively(tmp_path):
    path = _config(tmp_path)
    path.write_text(path.read_text().replace('"Steam"', '"steam"'))
    assert compat_map.map_app(path, 20).action == "mapped"
    assert compat_map.current(path, 20) == ("proton-cachyos-native", "250")


def test_config_path_is_under_the_steam_root(tmp_path):
    assert compat_map.config_path(tmp_path) == tmp_path / "config" / "config.vdf"


def test_a_value_spanning_lines_is_read_as_one_value(tmp_path):
    """Steam stores some values with embedded newlines (seen in the real file)."""
    path = _config(tmp_path)
    path.write_text(path.read_text().replace(
        '"SecretToken"\t\t"do-not-print-me"', '"SecretToken"\t\t"line one\nline {two}"'))
    assert compat_map.map_app(path, 20).action == "mapped"
    assert compat_map.current(path, 20) == ("proton-cachyos-native", "250")


def test_an_entry_sharing_a_line_with_its_key_is_refused(tmp_path):
    path = _config(tmp_path, '\t\t\t\t\t"20" {\n\t\t\t\t\t\t"name" "x"\n\t\t\t\t\t}\n')
    with pytest.raises(compat_map.CompatMapError, match="unexpected layout"):
        compat_map.map_app(path, 20)


def test_an_entry_closing_on_a_shared_line_is_refused(tmp_path):
    path = _config(tmp_path, '\t\t\t\t\t"20"\n\t\t\t\t\t{\n\t\t\t\t\t\t"name" "" }\n')
    with pytest.raises(compat_map.CompatMapError, match="unexpected layout"):
        compat_map.map_app(path, 20)


def test_unquoted_tokens_are_refused(tmp_path):
    path = _config(tmp_path)
    path.write_text(path.read_text().replace('"SecretToken"', "SecretToken"))
    with pytest.raises(compat_map.CompatMapError, match="line 9: unexpected layout"):
        compat_map.current(path, 20)


def test_a_failed_replace_leaves_the_file_and_no_temp(tmp_path, monkeypatch):
    path = _config(tmp_path)
    before = path.read_text()

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(compat_map.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        compat_map.map_app(path, 20)
    assert path.read_text() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["config.vdf"]
