import pytest

from app.services import normalization as n


def test_clean_text_collapses_whitespace_and_control_chars():
    assert n.clean_text("  Acme \n  Corp\x00 ") == "Acme Corp"
    assert n.clean_text("   ") is None


def test_email_normalised_and_validated():
    assert n.normalize_email(" Dana@Example.COM ") == "dana@example.com"
    with pytest.raises(ValueError):
        n.normalize_email("not-an-email")


def test_url_normalisation_and_scheme_allowlist():
    assert n.normalize_url("WWW.Acme.com/path") == ("https://acme.com", "acme.com")
    with pytest.raises(ValueError):
        n.normalize_url("javascript:alert(1)")
    with pytest.raises(ValueError):
        n.normalize_url("ftp://acme.com")
    with pytest.raises(ValueError):
        n.normalize_url("localhost")


def test_industry_and_country_aliases():
    assert n.normalize_industry("Heating and Cooling") == "hvac"
    assert n.normalize_industry("Unknown Biz") == "unknown biz"
    assert n.normalize_country("usa") == "United States"
    assert n.normalize_country("U.S.") == "United States"


@pytest.mark.parametrize("raw,expected", [("5k", 5000.0), ("$1,250", 1250.0), ("unknown", None), (None, None), (300, 300.0)])
def test_budget_parsing(raw, expected):
    assert n.parse_budget(raw) == expected


def test_budget_rejects_garbage_and_negative():
    with pytest.raises(ValueError):
        n.parse_budget("lots")
    with pytest.raises(ValueError):
        n.parse_budget(-5)


def test_optional_bool_keeps_unknown_distinct_from_false():
    assert n.parse_optional_bool("yes") is True
    assert n.parse_optional_bool("no") is False
    assert n.parse_optional_bool("") is None
    assert n.parse_optional_bool("unknown") is None
