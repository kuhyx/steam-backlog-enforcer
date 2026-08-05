import pytest

from steam_installer import vdf


def test_parse_flat_block():
    text = """
"AppState"
{
	"appid"		"1771300"
	"name"		"Kingdom Come: Deliverance II"
}
"""
    result = vdf.parse(text)
    assert result == {
        "AppState": {
            "appid": "1771300",
            "name": "Kingdom Come: Deliverance II",
        }
    }


def test_parse_nested_blocks():
    text = """
"AppState"
{
	"InstalledDepots"
	{
		"1771302"
		{
			"manifest"		"257127247679847518"
			"size"		"199419496"
		}
	}
}
"""
    result = vdf.parse(text)
    assert (
        result["AppState"]["InstalledDepots"]["1771302"]["manifest"]
        == "257127247679847518"
    )


def test_parse_handles_comments_and_blank_lines():
    text = """
// leading comment
"AppState"
{

	"appid"		"1" // trailing comment
}
"""
    result = vdf.parse(text)
    assert result == {"AppState": {"appid": "1"}}


def test_roundtrip_dumps_then_parse():
    data = {
        "appid": "1771300",
        "InstalledDepots": {
            "1771302": {"manifest": "257127247679847518", "size": "199419496"},
        },
    }
    text = vdf.dumps("AppState", data)
    reparsed = vdf.parse(text)
    assert reparsed == {"AppState": data}


def test_empty_input_returns_empty_dict():
    assert vdf.parse("") == {}


def test_dumps_reescapes_backslashes_so_round_trip_is_stable():
    r"""Real regression: appmanifest_228980.acf (Steamworks Common
    Redistributables) stores Windows paths like
    `_CommonRedist\\vcredist\\2015\\installscript.vdf`. The tokenizer consumes
    the escapes, so writing values back unescaped halved the backslashes on
    every parse/dump cycle and silently corrupted the InstallScripts paths."""
    original = (
        '"AppState"\n{\n\t"InstallScripts"\n\t{\n'
        '\t\t"228990"\t\t"_CommonRedist\\\\vcredist\\\\2015\\\\installscript.vdf"\n'
        "\t}\n}\n"
    )
    once = vdf.dumps("AppState", vdf.parse(original)["AppState"])
    assert once.strip() == original.strip()

    # And it must be a fixed point, not merely correct on the first pass.
    twice = vdf.dumps("AppState", vdf.parse(once)["AppState"])
    assert twice == once
    assert (
        vdf.parse(twice)["AppState"]["InstallScripts"]["228990"]
        == "_CommonRedist\\vcredist\\2015\\installscript.vdf"
    )


def test_dumps_escapes_embedded_quotes():
    data = {"name": 'Game "Deluxe" Edition'}
    assert vdf.parse(vdf.dumps("AppState", data))["AppState"] == data


def test_parse_error_message_includes_position():
    err = vdf.VdfParseError("boom", 7)
    assert str(err) == "boom (at position 7)"


def test_parse_empty_input_returns_empty_dict():
    assert vdf.parse("") == {}
    assert vdf.parse("   \n\t  ") == {}


def test_parse_rejects_root_key_without_a_block():
    with pytest.raises(vdf.VdfParseError, match="expected '{' after root key"):
        vdf.parse('"AppState"\n')


def test_parse_rejects_truncated_input_after_a_key():
    """A crash mid-write used to leave exactly this shape on disk."""
    with pytest.raises(vdf.VdfParseError, match="unexpected end of input"):
        vdf.parse('"AppState"\n{\n\t"installdir"')


def test_parse_tolerates_unquoted_tokens():
    """Rare in Steam's own files, but the tokenizer accepts them."""
    assert vdf.parse("AppState\n{\n\tinstalldir\tGame\n}\n") == {
        "AppState": {"installdir": "Game"}
    }


def test_parse_ignores_comment_lines():
    text = '// leading comment\n"AppState"\n{\n\t"installdir"\t\t"Game"\n}\n'
    assert vdf.parse(text) == {"AppState": {"installdir": "Game"}}


def test_parse_reads_scalar_value_after_key():
    """The non-block branch: a key whose value is a plain token."""
    assert vdf.parse('"AppState"\n{\n\t"StateFlags"\t\t"4"\n}\n') == {
        "AppState": {"StateFlags": "4"}
    }


def test_parse_tolerates_an_unterminated_block():
    """A truncated manifest (what a crash mid-write leaves behind) parses to
    whatever was complete, rather than raising -- the caller's own validity
    checks then reject it."""
    assert vdf.parse('"AppState"\n{\n\t"installdir"\t\t"Game"\n') == {
        "AppState": {"installdir": "Game"}
    }
