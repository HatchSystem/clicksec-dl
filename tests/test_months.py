import pytest

from clicksec_dl.months import month_range, parse_month


def test_parse_month_accepts_two_and_one_digit_months():
    assert parse_month("2024-12") == (2024, 12)
    assert parse_month("2025-1") == (2025, 1)


@pytest.mark.parametrize("text", ["2024", "2024-13", "2024-00", "202412", "2024/12", ""])
def test_parse_month_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_month(text)


def test_month_range_is_inclusive_and_crosses_year():
    assert month_range((2024, 11), (2025, 2)) == [(2024, 11), (2024, 12), (2025, 1), (2025, 2)]


def test_month_range_single_month():
    assert month_range((2025, 3), (2025, 3)) == [(2025, 3)]


def test_month_range_rejects_reversed():
    with pytest.raises(ValueError):
        month_range((2025, 2), (2025, 1))
