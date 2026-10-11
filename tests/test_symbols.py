import pytest

from clicksec_dl.symbols import Symbol, is_safe_symbol, select_symbols

AVAILABLE = [Symbol("21", "USDJPY"), Symbol("22", "EURJPY"), Symbol("23", "GBPJPY")]


def test_select_all_when_unspecified():
    assert select_symbols(AVAILABLE, None) == AVAILABLE
    assert select_symbols(AVAILABLE, []) == AVAILABLE


def test_select_keeps_order_and_dedupes_case_insensitively():
    selected = select_symbols(AVAILABLE, ["eurjpy", "USDJPY", "EURJPY"])
    assert [s.code for s in selected] == ["EURJPY", "USDJPY"]


def test_select_rejects_unknown():
    with pytest.raises(ValueError, match="XXXYYY"):
        select_symbols(AVAILABLE, ["USDJPY", "XXXYYY"])


@pytest.mark.parametrize(
    "symbol_id, code, ok",
    [
        ("21", "USDJPY", True),
        ("00017060000", "EURO_50_Index", True),
        ("21", "../evil", False),
        ("21", "..", False),
        ("21", "a/b", False),
        ("21", "", False),
        ("2 1", "USDJPY", False),
        ("21", "x..y", False),
    ],
)
def test_is_safe_symbol(symbol_id, code, ok):
    assert is_safe_symbol(symbol_id, code) is ok
