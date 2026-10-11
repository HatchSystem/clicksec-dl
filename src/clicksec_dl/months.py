"""年月の解釈と期間の展開。"""

from __future__ import annotations

import re

_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")

YearMonth = tuple[int, int]


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
    year, month = start
    while (year, month) <= end:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out
