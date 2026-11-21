"""``--help`` ends on kuhy's shared credit line (kuhy_credit, kuhyx/utils)."""

import pytest
from kuhy_credit import URL, credit_line
from steam_installer import cli


def test_help_ends_with_the_kuhy_credit(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith(credit_line())
    assert URL in out
