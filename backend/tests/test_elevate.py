import pytest
from stfu.apo.elevate import _quote_arg


def test_quote_arg_accepts_expected_tokens():
    assert _quote_arg("register") == "'register'"
    assert _quote_arg("Capture") == "'Capture'"
    assert _quote_arg("{A5C595A5-CE9C-41DE-B555-82867799E74B}") == "'{A5C595A5-CE9C-41DE-B555-82867799E74B}'"
    assert _quote_arg("--apo-admin") == "'--apo-admin'"
    assert _quote_arg("stfu.apo.admin_cli") == "'stfu.apo.admin_cli'"


@pytest.mark.parametrize("evil", [
    "'; calc.exe; '",
    "a b",
    "x$(whoami)",
    "y`ncalc",
    "z;rm",
    "",
    "cl'sid",
])
def test_quote_arg_rejects_injection_attempts(evil):
    with pytest.raises(ValueError):
        _quote_arg(evil)
