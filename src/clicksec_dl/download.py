"""ヒストリカルデータ ZIP の取得、リトライ、結果分類。"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from urllib.parse import unquote

import requests

from .products import Product
from .storage import InvalidZipError, extract_zip, save_zip
from .symbols import Symbol

log = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"""filename(\*)?=\s*(?:"([^"]*)"|([^;]*))""", re.IGNORECASE)


class Outcome(StrEnum):
    DOWNLOADED = "downloaded"  # 新規に保存した
    EXISTING = "existing"  # 既に同名ファイルがあり保存しなかった
    NO_DATA = "no_data"  # サーバーがファイルを返さなかった（その月のデータなし）
    FAILED = "failed"  # リトライ上限まで失敗した


@dataclass
class Result:
    product: str
    year: int
    month: int
    symbol: Symbol
    outcome: Outcome
    path: Path | None = None
    detail: str = ""


@dataclass
class Fetched:
    filename: str | None
    content: bytes


def filename_from_headers(headers) -> str | None:
    """Content-Disposition からファイル名（basename）を取り出す。無ければ None。"""
    cd = headers.get("Content-Disposition", "")
    m = _FILENAME_RE.search(cd)
    if not m:
        return None
    value = (m.group(2) if m.group(2) is not None else m.group(3) or "").strip()
    if m.group(1) and "''" in value:  # RFC 5987: filename*=UTF-8''name
        value = unquote(value.split("''", 1)[1])
    # サーバーが返す名前を保存先パスに使うため、ディレクトリ部分は捨てる
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name in {".", ".."}:
        return None
    return name


def build_url(product: Product, year: int, month: int, symbol: Symbol) -> str:
    return f"{product.download_url}?y={year}&m={month:02d}&c={symbol.id}&n={symbol.code}"


def fetch(
    session: requests.Session,
    product: Product,
    year: int,
    month: int,
    symbol: Symbol,
    *,
    extra_form: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> Fetched:
    url = build_url(product, year, month, symbol)
    if product.method == "GET":
        resp = session.get(url, timeout=timeout)
    else:
        resp = session.post(url, data=extra_form or {}, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return Fetched(filename_from_headers(resp.headers), resp.content)


def download_one(
    session: requests.Session,
    product: Product,
    year: int,
    month: int,
    symbol: Symbol,
    *,
    out_root: Path,
    extra_form: dict[str, str] | None = None,
    retries: int = 3,
    force: bool = False,
    extract: bool = False,
    timeout: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Result:
    """1 件（年月 × 銘柄）をダウンロードして保存し、結果を返す。"""
    symbol_dir = out_root / product.name / symbol.code

    def result(outcome: Outcome, path: Path | None = None, detail: str = "") -> Result:
        return Result(product.name, year, month, symbol, outcome, path, detail)

    def finish_existing(path: Path) -> Result:
        if extract:
            extract_zip(path, symbol_dir, force=force)
        return result(Outcome.EXISTING, path)

    # ファイル名が予測できるなら、リクエスト前に既存判定して通信を省く
    predicted = product.predict_filename(year, month, symbol)
    if predicted and not force and (symbol_dir / predicted).exists():
        return finish_existing(symbol_dir / predicted)

    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            fetched = fetch(
                session, product, year, month, symbol, extra_form=extra_form, timeout=timeout
            )
        except requests.RequestException as e:
            last_error = f"リクエスト失敗: {e}"
            log.warning(
                "%s %d-%02d (試行 %d/%d): %s",
                symbol.code,
                year,
                month,
                attempt,
                retries,
                last_error,
            )
            _backoff(sleep, attempt, retries)
            continue

        if fetched.filename is None:
            return result(Outcome.NO_DATA, detail="Content-Disposition にファイル名がありません")
        if not fetched.filename.lower().endswith(".zip"):
            return result(Outcome.NO_DATA, detail=f"ZIP 以外の応答: {fetched.filename}")

        target = symbol_dir / fetched.filename
        if target.exists() and not force:
            return finish_existing(target)

        try:
            save_zip(target, fetched.content)
        except InvalidZipError as e:
            last_error = str(e)
            log.warning(
                "%s %d-%02d (試行 %d/%d): %s",
                symbol.code,
                year,
                month,
                attempt,
                retries,
                last_error,
            )
            _backoff(sleep, attempt, retries)
            continue

        if extract:
            extract_zip(target, symbol_dir, force=force)
        return result(Outcome.DOWNLOADED, target)

    return result(Outcome.FAILED, detail=last_error)


def _backoff(sleep: Callable[[float], None], attempt: int, retries: int) -> None:
    if attempt < retries:
        sleep(min(2 ** (attempt - 1), 8))
