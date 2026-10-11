"""銘柄カタログ: 一覧ページから銘柄 ID・コード・取得できる月を集め、JSON に保存する。

一覧ページは年ごとに「銘柄 × 月」のダウンロードリンクを並べている。リンクがある月だけが
取得できる。カタログは走査結果を既存の内容へ統合し、サイトから消えた銘柄も削除しない。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

from .products import Product
from .symbols import Symbol, is_safe_symbol

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# FX: <a href="historicalDataDownload.do?y=2026&m=01&c=21&n=USDJPY">
_HREF_RE = re.compile(r"historicalDataDownload\.do\?y=(\d{4})&m=(\d{1,2})&c=([^&]+)&n=([^&#]+)")
# CFD: <a href="javascript:dl_onclick(2026,'01','00001060000','JP225');void(0)">
_ONCLICK_RE = re.compile(
    r"dl_onclick\(\s*'?(\d{4})'?\s*,\s*'?(\d{1,2})'?\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)"
)


@dataclass
class ListedSymbol:
    """一覧ページの 1 行。"""

    id: str
    code: str
    name: str
    months: set[str] = field(default_factory=set)  # "YYYY-MM"


@dataclass
class ListPage:
    years: list[int]  # 年の選択肢
    symbols: list[ListedSymbol]


class _ListPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.years: list[int] = []
        self.rows: list[tuple[str, list[str]]] = []  # (表示名, リンク先)
        self._in_year_select = False
        self._in_row = False
        self._in_name_cell = False
        self._name_parts: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "select" and a.get("name") == "y":
            self._in_year_select = True
        elif tag == "option" and self._in_year_select and (a.get("value") or "").isdigit():
            self.years.append(int(a["value"]))
        elif tag == "tr":
            self._in_row, self._name_parts, self._links = True, [], []
        elif tag == "td" and self._in_row and "col01" in (a.get("class") or "").split():
            self._in_name_cell = True
        elif tag == "a" and self._in_row and a.get("href"):
            self._links.append(a["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "select":
            self._in_year_select = False
        elif tag == "td":
            self._in_name_cell = False
        elif tag == "tr" and self._in_row:
            if self._links:
                self.rows.append((" ".join("".join(self._name_parts).split()), self._links))
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_name_cell:
            self._name_parts.append(data)


def parse_list_page(html: str) -> ListPage:
    """一覧ページの HTML から年の選択肢と、銘柄ごとの取得できる月を取り出す。"""
    parser = _ListPageParser()
    parser.feed(html)
    parser.close()

    by_key: dict[tuple[str, str], ListedSymbol] = {}
    for name, links in parser.rows:
        for link in links:
            m = _HREF_RE.search(link) or _ONCLICK_RE.search(link)
            if not m:
                continue
            year, month, symbol_id, code = m.groups()
            if not is_safe_symbol(symbol_id, code):
                log.warning("安全でない銘柄 ID / コードを無視しました: %r %r", symbol_id, code)
                continue
            month_num = int(month)
            if not 1 <= month_num <= 12:
                continue
            entry = by_key.setdefault((symbol_id, code), ListedSymbol(symbol_id, code, name))
            entry.months.add(f"{int(year):04d}-{month_num:02d}")
    return ListPage(sorted(set(parser.years)), list(by_key.values()))


@dataclass
class CatalogEntry:
    id: str
    code: str
    name: str
    months: set[str] = field(default_factory=set)
    first_seen: str = ""  # 初めて一覧に現れた日（YYYY-MM-DD）
    last_seen: str = ""  # 最後に一覧で確認した日

    @property
    def symbol(self) -> Symbol:
        return Symbol(self.id, self.code)

    def has_month(self, year: int, month: int) -> bool:
        return f"{year:04d}-{month:02d}" in self.months


@dataclass
class Catalog:
    product: str
    entries: list[CatalogEntry] = field(default_factory=list)
    scanned_years: dict[int, str] = field(default_factory=dict)  # 年 → 最後に走査した日
    updated_at: str = ""

    def symbols(self) -> list[Symbol]:
        """コードごとに 1 件、最も新しい月まで使われている ID の Symbol を返す。"""
        latest: dict[str, CatalogEntry] = {}
        for e in self.entries:
            cur = latest.get(e.code)
            if cur is None or _latest_month(e) > _latest_month(cur):
                latest[e.code] = e
        return [latest[code].symbol for code in sorted(latest, key=str.lower)]

    def resolve(self, code: str, year: int, month: int) -> Symbol | None:
        """その年月に使う ID を決める。同じコードでも時期によって ID が異なる。

        例: FX の USDJPY は 2016-02 までが ID 01、2016-01 以降が ID 21。
        走査済みの年で一覧にリンクが無い月は None（要求しない）。未走査の年は最新の ID で試す。
        """
        candidates = [e for e in self.entries if e.code == code]
        if not candidates:
            return None
        listed = [e for e in candidates if e.has_month(year, month)]
        if listed:
            return max(listed, key=_latest_month).symbol
        if year in self.scanned_years:
            return None
        return max(candidates, key=_latest_month).symbol

    def merge(self, year: int, listed: Iterable[ListedSymbol], today: str) -> MergeStats:
        """1 年分の走査結果を統合する。カタログにある月は削除しない。"""
        stats = MergeStats()
        index = {(e.id, e.code): e for e in self.entries}
        for item in listed:
            months = {m for m in item.months if m.startswith(f"{year:04d}-")}
            e = index.get((item.id, item.code))
            if e is None:
                e = CatalogEntry(item.id, item.code, item.name, set(), today, today)
                self.entries.append(e)
                index[(e.id, e.code)] = e
                stats.new_symbols.append(f"{e.code}(ID {e.id})")
            new_months = months - e.months
            stats.new_months += len(new_months)
            e.months |= months
            e.name = item.name or e.name
            e.last_seen = today
        self.scanned_years[year] = today
        self.updated_at = today
        self.entries.sort(key=lambda e: (e.id, e.code))
        return stats

    def to_json(self) -> dict:
        return {
            "schema": SCHEMA_VERSION,
            "product": self.product,
            "updated_at": self.updated_at,
            "scanned_years": {str(y): d for y, d in sorted(self.scanned_years.items())},
            "symbols": [
                {
                    "id": e.id,
                    "code": e.code,
                    "name": e.name,
                    "first_seen": e.first_seen,
                    "last_seen": e.last_seen,
                    "months": sorted(e.months),
                }
                for e in self.entries
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> Catalog:
        if data.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"未対応のカタログ形式です: schema={data.get('schema')!r}")
        entries = []
        for s in data.get("symbols", []):
            if not is_safe_symbol(s["id"], s["code"]):
                raise ValueError(f"安全でない銘柄 ID / コード: {s['id']!r} {s['code']!r}")
            entries.append(
                CatalogEntry(
                    s["id"],
                    s["code"],
                    s.get("name", ""),
                    set(s.get("months", [])),
                    s.get("first_seen", ""),
                    s.get("last_seen", ""),
                )
            )
        return cls(
            product=data["product"],
            entries=entries,
            scanned_years={int(y): d for y, d in data.get("scanned_years", {}).items()},
            updated_at=data.get("updated_at", ""),
        )


def _latest_month(e: CatalogEntry) -> str:
    return max(e.months, default="")


@dataclass
class MergeStats:
    new_symbols: list[str] = field(default_factory=list)
    new_months: int = 0


def catalog_path(catalog_dir: Path, product: Product) -> Path:
    return catalog_dir / f"{product.name}.json"


def load_catalog(catalog_dir: Path, product: Product) -> Catalog | None:
    path = catalog_path(catalog_dir, product)
    if not path.is_file():
        return None
    catalog = Catalog.from_json(json.loads(path.read_text(encoding="utf-8")))
    if catalog.product != product.name:
        raise ValueError(f"{path} は {catalog.product} のカタログです")
    return catalog


def save_catalog(catalog_dir: Path, catalog: Catalog) -> Path:
    path = catalog_dir / f"{catalog.product}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(catalog.to_json(), ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)
    return path


def fetch_list_page(
    session: requests.Session,
    product: Product,
    year: int | None,
    form: dict[str, str],
    *,
    timeout: float = 30.0,
) -> ListPage:
    params = {} if year is None else {"y": str(year)}
    if product.method == "GET":
        resp = session.get(product.list_url, params=params, timeout=timeout)
    else:
        resp = session.post(
            product.list_url, data={**form, **params}, timeout=timeout, allow_redirects=False
        )
    if resp.status_code != 200:
        raise requests.HTTPError(f"一覧ページの取得に失敗しました: HTTP {resp.status_code}")
    # charset が無いと requests は ISO-8859-1 とみなすため、本文から推定する（FX は CP932）
    if "charset" not in resp.headers.get("Content-Type", "").lower():
        resp.encoding = resp.apparent_encoding
    return parse_list_page(resp.text)


def scan(
    session: requests.Session,
    product: Product,
    catalog: Catalog,
    form: dict[str, str],
    *,
    years: Iterable[int] | None = None,
    interval: float = 1.0,
    timeout: float = 30.0,
    today: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> MergeStats:
    """一覧ページを年ごとに取得してカタログへ統合する。years 未指定ならサイトの全年。

    サイトが選択肢に出していない年は走査しない。
    """
    today = today or datetime.now().strftime("%Y-%m-%d")
    first = fetch_list_page(session, product, None, form, timeout=timeout)
    available = set(first.years)
    targets = sorted(available if years is None else set(years) & available)
    skipped = sorted(set(years or []) - available)
    if skipped:
        log.info("サイトの一覧に無い年は走査しません: %s", ", ".join(map(str, skipped)))

    total = MergeStats()
    for i, year in enumerate(targets):
        if i > 0 and interval > 0:
            sleep(interval)
        page = fetch_list_page(session, product, year, form, timeout=timeout)
        stats = catalog.merge(year, page.symbols, today)
        log.debug("%s %d 年: %d 銘柄", product.label, year, len(page.symbols))
        total.new_symbols += stats.new_symbols
        total.new_months += stats.new_months
    return total
