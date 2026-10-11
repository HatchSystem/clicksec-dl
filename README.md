# clicksec-dl

GMOクリック証券の FXネオ / CFD ヒストリカルデータ ZIP を、指定した期間・銘柄についてローカルへダウンロードする CLI です。

> **非公式ツールです。** GMOクリック証券とは関係がなく、同社による承認・保証はありません。利用には同社の口座が必要です。利用者自身の口座で、同社の利用規約の範囲内で使ってください。サイトの仕様変更で動かなくなることがあります。ダウンロードしたデータの再配布可否は同社の規約を確認してください。

## セットアップ

Python 3.12 以上と [uv](https://docs.astral.sh/uv/) が必要です。

```sh
uv sync
cp .env.example .env   # ログイン ID / パスワードを記入
```

## 使い方

初回は銘柄カタログを作ります。サイトの一覧ページを年ごとに走査し、銘柄 ID・コード・取得できる月を `catalog/{fx|cfd}.json` に保存します（FX は約 20 ページ、1 秒間隔）。リポジトリには作成済みのカタログが含まれています。

```sh
uv run clicksec-dl catalog update fx
uv run clicksec-dl catalog update cfd --years 2024-2026   # 年を絞る場合
```

ダウンロード時は、対象期間の年の一覧ページを自動で再走査してカタログを更新し、一覧にリンクがある月だけを要求します。新しく追加された銘柄・月はこれで取り込まれます。サイトから消えた銘柄もカタログには残るため、過去の月を指定して取得できます。

```sh
# FXネオ: 2024-12〜2025-01 の USDJPY と EURJPY を data/ 以下へ保存
uv run clicksec-dl fx --from 2024-12 --to 2025-01 --symbols USDJPY EURJPY

# CFD: 2025-01 の全銘柄。ZIP の中身も展開する
uv run clicksec-dl cfd --from 2025-01 --extract

# カタログの銘柄一覧（ID、取得できる期間、表示名）
uv run clicksec-dl symbols fx

# ログインせずに対象だけ確認（保存済みカタログを使う）
uv run clicksec-dl fx --from 2024-12 --dry-run
```

同じ銘柄コードでも時期によって ID が異なることがあります（例: FX の USDJPY は 2016-02 までが ID `01`、2016-01 以降が `21`）。年月ごとにカタログから正しい ID を選ぶので、利用者はコードだけを指定します。

保存先は `data/{fx|cfd}/{銘柄コード}/{サーバーが返すファイル名}` です。同名ファイルが既にあれば取得をスキップし、`--force` で上書きします。

| オプション | 既定 | 説明 |
|---|---|---|
| `--from` / `--to` | 必須 / `--from` と同じ | 対象期間（YYYY-MM、両端含む） |
| `--symbols` | カタログの全銘柄 | 銘柄コード |
| `--out` | `data` | 保存先ルート |
| `--force` | off | 既存ファイルを再取得して上書き |
| `--extract` | off | ZIP の中身を同じディレクトリへ展開 |
| `--dry-run` | off | ログインせず、保存済みカタログで対象だけ表示 |
| `--no-scan` | off | 一覧ページを再走査せず、保存済みカタログだけで対象を決める |
| `--catalog-dir` | `catalog` | カタログの保存先 |
| `--interval` | FX 1 秒 / CFD 2 秒 | リクエスト間の待機 |
| `--retries` | 3 | 1 件あたりの最大試行回数 |
| `--env-file` | `.env` | 認証情報を読むファイル |

終了コード: `0` 全件成功、`1` 失敗した件がある、`2` 引数・認証情報・ログインのエラー。

## 環境変数

| 変数 | 必須 | 用途 |
|---|---|---|
| `CLICKSEC_J_USERNAME` | 必須 | ログイン ID |
| `CLICKSEC_J_PASSWORD` | 必須 | ログインパスワード |
| `CLICKSEC_USER_AGENT` | 任意 | 送信する User-Agent の上書き |

パスワードをコマンドライン引数で渡すオプションは、シェル履歴に残るため用意していません。CFD の要求に必要な口座の `guid` は、ログイン応答から自動で取得します。

## 仕組み

- ログインは同社 SSO のログインフォームへ ID とパスワードを送ります。CFD の要求に必要な口座の `guid` はログイン応答から取り出します。Cookie、トークン、`guid` はログへ出しません。
- 一覧ページ（`historicalDataList.do`）は、年ごとに「銘柄 × 月」のダウンロードリンクを並べています。リンクがある月だけを要求します。
- 同じコードでも時期によって ID が異なる銘柄や、複数の銘柄で ID を共有する例（CFD の `Copper_Futures` と `Iron_Ore_Futures`）があるため、カタログは ID とコードの組で管理します。
- ブラウザ相当のヘッダーを送り、要求の間に既定で FX 1 秒、CFD 2 秒の間隔を空けます。

## 開発

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## License

[MIT License](LICENSE)
