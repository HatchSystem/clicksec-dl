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


def test_current_month_uses_jst():
    from datetime import UTC, datetime

    from clicksec_dl.months import current_month

    # UTC では 9/30 だが、日本時間では 10/1
    assert current_month(datetime(2026, 9, 30, 15, 0, tzinfo=UTC)) == (2026, 10)
    assert current_month(datetime(2026, 9, 30, 14, 59, tzinfo=UTC)) == (2026, 9)


def test_previous_and_next_month_cross_year():
    from clicksec_dl.months import next_month, previous_month

    assert previous_month((2026, 1)) == (2025, 12)
    assert previous_month((2026, 10)) == (2026, 9)
    assert next_month((2025, 12)) == (2026, 1)


def test_month_end_is_next_month_start_in_jst():
    from clicksec_dl.months import JST, month_end

    assert month_end((2025, 12)).isoformat() == "2026-01-01T00:00:00+09:00"
    assert month_end((2026, 2)).tzinfo is JST
