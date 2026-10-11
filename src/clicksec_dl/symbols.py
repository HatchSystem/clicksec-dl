"""銘柄の識別子と、銘柄コード指定の解決。銘柄の一覧はカタログ（catalog.py）が持つ。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# サーバーから得たコードは保存ディレクトリ名に使うため、安全な文字だけを受け入れる
_SAFE_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9]+$")


@dataclass(frozen=True)
class Symbol:
    id: str  # ダウンロード URL の c= に渡す ID。銘柄間で重複することがある
    code: str  # ダウンロード URL の n= に渡し、保存ディレクトリ名にも使うコード。一意


def is_safe_symbol(symbol_id: str, code: str) -> bool:
    return bool(_SAFE_ID_RE.match(symbol_id) and _SAFE_CODE_RE.match(code)) and ".." not in code


def select_symbols(available: Sequence[Symbol], codes: list[str] | None) -> list[Symbol]:
    """銘柄コードの指定を Symbol の一覧へ変換する。未指定なら全銘柄、未知のコードは ValueError。"""
    if not codes:
        return list(available)
    by_code = {s.code.lower(): s for s in available}
    unknown = [c for c in codes if c.lower() not in by_code]
    if unknown:
        raise ValueError(
            f"未知の銘柄コードです: {', '.join(unknown)}"
            "（`clicksec-dl symbols <product>` で一覧を確認できます）"
        )
    # 指定順を保ち、重複は除く
    seen: set[str] = set()
    result: list[Symbol] = []
    for c in codes:
        key = c.lower()
        if key not in seen:
            seen.add(key)
            result.append(by_code[key])
    return result
