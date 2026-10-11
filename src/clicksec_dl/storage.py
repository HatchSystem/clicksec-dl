"""ローカル保存と ZIP 展開。"""

from __future__ import annotations

import shutil
import zipfile
from datetime import timedelta
from pathlib import Path, PurePosixPath

from .months import YearMonth, month_end

# 月末最終日のデータが翌日に反映される場合に備えた余裕
COMPLETE_MARGIN = timedelta(days=1)


def is_complete(path: Path, ym: YearMonth) -> bool:
    """保存済みの月次 ZIP が、その月の終了後に取得したもの（完全版）か。

    月の途中で取得した ZIP はその時点までのデータしか含まないため、途中版として扱う。
    """
    return path.stat().st_mtime >= (month_end(ym) + COMPLETE_MARGIN).timestamp()


class InvalidZipError(ValueError):
    """受信した内容が ZIP として開けない。"""


class UnsafeZipEntryError(ValueError):
    """展開先の外へ書き込もうとする ZIP エントリ。"""


def save_zip(target: Path, content: bytes) -> None:
    """一時ファイルへ書いて ZIP として検証し、成功したら target へ置き換える。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    part.write_bytes(content)
    if not zipfile.is_zipfile(part):
        part.unlink(missing_ok=True)
        raise InvalidZipError(f"ZIP として読めません: {target.name}")
    part.replace(target)


def _safe_member_path(dest_dir: Path, member_name: str) -> Path:
    name = member_name.replace("\\", "/")
    pure = PurePosixPath(name)
    if pure.is_absolute() or ".." in pure.parts or ":" in name:
        raise UnsafeZipEntryError(f"安全でないエントリ名: {member_name!r}")
    out = (dest_dir / Path(*pure.parts)).resolve()
    if not out.is_relative_to(dest_dir.resolve()):
        raise UnsafeZipEntryError(f"展開先の外を指すエントリ名: {member_name!r}")
    return out


def extract_zip(zip_path: Path, dest_dir: Path, *, force: bool = False) -> list[Path]:
    """ZIP の中身を dest_dir へ展開する。既存ファイルは force でなければ残す。

    戻り値は実際に書き出したファイルの一覧。
    """
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out = _safe_member_path(dest_dir, info.filename)
            if out.exists() and not force:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, out.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            written.append(out)
    return written
