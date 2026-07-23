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
