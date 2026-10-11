"""商品（FXネオ / CFD）ごとのログイン・一覧・ダウンロード設定。"""

from __future__ import annotations

from dataclasses import dataclass

from .symbols import Symbol


@dataclass(frozen=True)
class Product:
    name: str  # サブコマンド名かつ保存ディレクトリ名
    label: str
    login_form: dict[str, str]  # SSO ログインフォームの商品固有フィールド
    list_url: str  # 年ごとのダウンロードリンクが並ぶ一覧ページ
    download_url: str
    method: str  # 一覧・ダウンロード要求の HTTP メソッド
    requires_guid: bool  # 要求のフォームに口座の guid が必要か
    default_interval: float  # リクエスト間の待機秒
    # サーバーが返すファイル名が予測できる場合の書式。既存ファイルの事前スキップに使う。
    # 使える置換: {code} {id} {yyyy} {mm}
    filename_pattern: str | None = None

    def predict_filename(self, year: int, month: int, symbol: Symbol) -> str | None:
        if self.filename_pattern is None:
            return None
        return self.filename_pattern.format(
            code=symbol.code, id=symbol.id, yyyy=f"{year:04d}", mm=f"{month:02d}"
        )


FX = Product(
    name="fx",
    label="FXネオ",
    login_form={"s": "01", "p": "03", "sp": "", "rp": ""},
    list_url="https://tb.click-sec.com/fx/historical/historicalDataList.do",
    download_url="https://tb.click-sec.com/fx/historical/historicalDataDownload.do",
    method="GET",
    requires_guid=False,
    default_interval=1.0,
    filename_pattern="{code}_{yyyy}{mm}.zip",  # 2026-10 に実サーバーで確認
)

CFD = Product(
    name="cfd",
    label="CFD",
    login_form={"s": "05", "p": "01", "sp": "02", "rp": ""},
    list_url="https://tb.click-sec.com/cfd/historical/historicalDataList.do",
    download_url="https://tb.click-sec.com/cfd/historical/historicalDataDownload.do",
    method="POST",
    requires_guid=True,  # guid なしの一覧要求は 302 で弾かれる（2026-10 に確認）
    default_interval=2.0,
    filename_pattern="{code}_{yyyy}{mm}.zip",  # 2026-10 に実サーバーで確認
)

PRODUCTS: dict[str, Product] = {FX.name: FX, CFD.name: CFD}
