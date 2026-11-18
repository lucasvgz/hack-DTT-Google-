"""Unit tests for French/international financial number and unit parsing."""

from urd_verifier.ingestion.number_parser import (
    detect_unit_in_text,
    extract_numbers_from_text,
    parse_financial_number,
)


def test_parse_french_numbers_and_negatives():
    assert parse_financial_number("1 234,5").value == 1234.5
    assert parse_financial_number("1\u00a0234,50").value == 1234.5
    assert parse_financial_number("(45,2)").value == -45.2
    assert parse_financial_number("- 120,4").value == -120.4
    p = parse_financial_number("+4,2 %")
    assert p is not None
    assert p.value == 4.2
    assert p.is_percent is True
    assert p.unit == "%"


def test_parse_units_and_ignore_non_numbers():
    p_m = parse_financial_number("1 300 M€")
    assert p_m is not None
    assert p_m.value == 1300.0
    assert p_m.unit == "M€"
    assert p_m.scale_multiplier == 1_000_000.0

    assert parse_financial_number("Note 14") is None
    assert parse_financial_number("—") is None
    assert detect_unit_in_text("Tableau 1 (en k€)") == ("k€", 1_000.0)
    assert detect_unit_in_text("Montants en milliards d'euros") == ("Md€", 1_000_000_000.0)


def test_extract_numbers_skips_years():
    nums = extract_numbers_from_text(
        "En 2025, le chiffre d'affaires progresse de +5,0 % à 1 300 M€."
    )
    values = [n.value for n in nums]
    assert 2025.0 not in values
    assert 5.0 in values
    assert 1300.0 in values
