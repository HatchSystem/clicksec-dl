"""年月の解釈と期間の展開。"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")

# 当月・前月や月の終了は日本時間で判定する（日本に夏時間はないので UTC+9 固定）
JST = timezone(timedelta(hours=9), "JST")

YearMonth = tuple[int, int]


def current_month(now: datetime | None = None) -> YearMonth:
    now = (now or datetime.now(JST)).astimezone(JST)
    return now.year, now.month


def previous_month(ym: YearMonth) -> YearMonth:
    year, month = ym
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(ym: YearMonth) -> YearMonth:
    year, month = ym
    return (year + 1, 1) if month == 12 else (year, month + 1)


def month_end(ym: YearMonth) -> datetime:
    """その月が終わる時刻（翌月 1 日 0:00 JST）。"""
    year, month = next_month(ym)
    return datetime(year, month, 1, tzinfo=JST)


def parse_month(text: str) -> YearMonth:
    m = _MONTH_RE.match(text.strip())
    if not m:
        raise ValueError(f"年月は YYYY-MM 形式で指定してください: {text!r}")
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"月は 01〜12 の範囲で指定してください: {text!r}")
    return year, month


def month_range(start: YearMonth, end: YearMonth) -> list[YearMonth]:
    """start から end まで（両端含む）の年月を月単位で列挙する。"""
    if end < start:
        raise ValueError(
            f"--to ({end[0]}-{end[1]:02d}) が --from ({start[0]}-{start[1]:02d}) より前です"
        )
    out: list[YearMonth] = []
    ym = start
    while ym <= end:
        out.append(ym)
        ym = next_month(ym)
    return out
