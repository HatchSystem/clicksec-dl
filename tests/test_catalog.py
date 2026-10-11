import json
from pathlib import Path

import pytest

from clicksec_dl.catalog import (
    Catalog,
    ListedSymbol,
    load_catalog,
    parse_list_page,
    save_catalog,
    scan,
)
from clicksec_dl.products import CFD, FX
from clicksec_dl.symbols import Symbol
from conftest import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_fx_page_keeps_ids_per_period_and_drops_unsafe_codes():
    page = parse_list_page(_fixture("fx_list_2016.html"))

    assert page.years == [2015, 2016]
    by_key = {(s.id, s.code): s for s in page.symbols}
    assert set(by_key) == {("01", "USDJPY"), ("21", "USDJPY")}
    assert by_key[("01", "USDJPY")].months == {"2016-01", "2016-02"}
    assert by_key[("21", "USDJPY")].months == {"2016-01", "2016-02", "2016-03"}
    assert by_key[("21", "USDJPY")].name == "米ドル/円"


def test_parse_cfd_page_reads_onclick_links_and_shared_ids():
    page = parse_list_page(_fixture("cfd_list_2024.html"))

    assert page.years == [2011, 2023, 2024]
    by_code = {s.code: s for s in page.symbols}
    assert by_code["JP225"].months == {"2024-01", "2024-02"}
    assert by_code["JP225"].name == "日本225"
    # 銅先物と鉄鉱石は同じ ID を共有している
    assert by_code["Copper_Futures"].id == by_code["Iron_Ore_Futures"].id == "00023070000"
    assert by_code["Iron_Ore_Futures"].months == {"2024-02"}


def _catalog_with_id_switch() -> Catalog:
    catalog = Catalog("fx")
    catalog.merge(
        2016,
        [
            ListedSymbol("01", "USDJPY", "米ドル/円", {"2016-01", "2016-02"}),
            ListedSymbol("21", "USDJPY", "米ドル/円", {"2016-01", "2016-02", "2016-03"}),
            ListedSymbol("22", "EURJPY", "ユーロ/円", {"2016-03"}),
        ],
        "2026-10-01",
    )
    catalog.merge(2015, [ListedSymbol("01", "USDJPY", "米ドル/円", {"2015-12"})], "2026-10-01")
    return catalog


def test_resolve_picks_id_by_period():
    catalog = _catalog_with_id_switch()

    assert catalog.resolve("USDJPY", 2015, 12) == Symbol("01", "USDJPY")
    # 両方の ID にリンクがある月は、より新しい月まで使われている ID を選ぶ
    assert catalog.resolve("USDJPY", 2016, 1) == Symbol("21", "USDJPY")
    assert catalog.resolve("USDJPY", 2016, 3) == Symbol("21", "USDJPY")


def test_resolve_skips_unlisted_months_in_scanned_years():
    catalog = _catalog_with_id_switch()

    assert catalog.resolve("EURJPY", 2016, 1) is None  # 走査済みの年でリンクなし
    assert catalog.resolve("EURJPY", 2015, 6) is None
    assert catalog.resolve("NOPE", 2016, 1) is None


def test_resolve_tries_latest_id_for_unscanned_years():
    catalog = _catalog_with_id_switch()
    assert catalog.resolve("USDJPY", 2027, 1) == Symbol("21", "USDJPY")


def test_symbols_returns_one_latest_id_per_code():
    assert _catalog_with_id_switch().symbols() == [Symbol("22", "EURJPY"), Symbol("21", "USDJPY")]


def test_merge_keeps_symbols_and_months_that_disappear():
    catalog = Catalog("cfd")
    catalog.merge(2023, [ListedSymbol("10", "INNIF", "インドNIF", {"2023-06"})], "2026-09-01")
    stats = catalog.merge(2024, [ListedSymbol("1", "JP225", "日本225", {"2024-01"})], "2026-10-01")

    assert stats.new_symbols == ["JP225(ID 1)"]
    innif = next(e for e in catalog.entries if e.code == "INNIF")
    assert innif.months == {"2023-06"}
    assert innif.last_seen == "2026-09-01"

    stats = catalog.merge(2024, [ListedSymbol("1", "JP225", "日本225", {"2024-01"})], "2026-10-02")
    assert stats.new_symbols == [] and stats.new_months == 0


def test_merge_ignores_months_outside_the_scanned_year():
    catalog = Catalog("fx")
    catalog.merge(2016, [ListedSymbol("21", "USDJPY", "", {"2016-01", "2017-01"})], "2026-10-01")
    assert catalog.entries[0].months == {"2016-01"}


def test_save_and_load_roundtrip(tmp_path):
    catalog = _catalog_with_id_switch()
    path = save_catalog(tmp_path, catalog)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    assert data["scanned_years"] == {"2015": "2026-10-01", "2016": "2026-10-01"}
    assert "米ドル/円" in path.read_text(encoding="utf-8")  # ensure_ascii=False

    loaded = load_catalog(tmp_path, FX)
    assert loaded.to_json() == catalog.to_json()
    assert load_catalog(tmp_path, CFD) is None


def test_load_rejects_unsafe_code(tmp_path):
    (tmp_path / "fx.json").write_text(
        json.dumps({"schema": 1, "product": "fx", "symbols": [{"id": "1", "code": "../x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="安全でない"):
        load_catalog(tmp_path, FX)


def test_scan_fetches_requested_years_only_if_listed(no_sleep):
    html = _fixture("cfd_list_2024.html")
    session = FakeSession([FakeResponse(text=html), FakeResponse(text=html)])
    catalog = Catalog("cfd")

    stats = scan(
        session,
        CFD,
        catalog,
        {"guid": "99999"},
        years=[2024, 2030],
        today="2026-10-11",
        sleep=no_sleep,
    )

    assert (
        len(session.calls) == 2
    )  # 年の選択肢の取得 + 2024 年。2030 年はサイトに無いので要求しない
    method, url, kwargs = session.calls[1]
    assert (method, url) == ("POST", CFD.list_url)
    assert kwargs["data"] == {"guid": "99999", "y": "2024"}
    assert kwargs["allow_redirects"] is False
    assert sorted(stats.new_symbols) == [
        "Copper_Futures(ID 00023070000)",
        "Iron_Ore_Futures(ID 00023070000)",
        "JP225(ID 00001060000)",
    ]
    assert catalog.scanned_years == {2024: "2026-10-11"}


def test_scan_fx_uses_get_with_year_param(no_sleep):
    html = _fixture("fx_list_2016.html")
    session = FakeSession([FakeResponse(text=html), FakeResponse(text=html)])

    scan(session, FX, Catalog("fx"), {}, years=[2016], today="2026-10-11", sleep=no_sleep)

    method, url, kwargs = session.calls[1]
    assert (method, url, kwargs["params"]) == ("GET", FX.list_url, {"y": "2016"})


def test_scan_raises_on_redirect():
    import requests

    session = FakeSession([FakeResponse(status_code=302)])
    with pytest.raises(requests.HTTPError, match="302"):
        scan(session, CFD, Catalog("cfd"), {}, years=[2024])
