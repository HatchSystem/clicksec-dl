"""コマンドライン入口。終了コード: 0 成功 / 1 一部失敗 / 2 設定・認証エラー。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from . import __version__
from .auth import LoginError, login
from .catalog import Catalog, catalog_path, load_catalog, save_catalog, scan
from .download import Outcome, build_url, download_one
from .env import load_dotenv
from .http import new_session
from .months import month_range, parse_month
from .products import PRODUCTS, Product
from .symbols import select_symbols

log = logging.getLogger("clicksec_dl")

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_CONFIG = 2

ENV_USERNAME = "CLICKSEC_J_USERNAME"
ENV_PASSWORD = "CLICKSEC_J_PASSWORD"
ENV_USER_AGENT = "CLICKSEC_USER_AGENT"


def _month_arg(text: str) -> tuple[int, int]:
    try:
        return parse_month(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _years_arg(text: str) -> range:
    """YYYY または YYYY-YYYY を年の範囲にする。"""
    parts = text.split("-", 1)
    if not all(p.isdigit() and len(p) == 4 for p in parts):
        raise argparse.ArgumentTypeError(f"YYYY または YYYY-YYYY で指定してください: {text!r}")
    start, end = int(parts[0]), int(parts[-1])
    if end < start:
        raise argparse.ArgumentTypeError(f"終了年が開始年より前です: {text!r}")
    return range(start, end + 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clicksec-dl",
        description="GMOクリック証券の FXネオ / CFD ヒストリカルデータ ZIP をローカルへ保存する。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    verbosity = argparse.ArgumentParser(add_help=False)
    group = verbosity.add_mutually_exclusive_group()
    group.add_argument("-v", "--verbose", action="store_true", help="詳細ログを表示する")
    group.add_argument("-q", "--quiet", action="store_true", help="警告以上だけ表示する")

    catalog_opts = argparse.ArgumentParser(add_help=False)
    catalog_opts.add_argument(
        "--catalog-dir",
        type=Path,
        default=Path("catalog"),
        metavar="DIR",
        help="銘柄カタログの保存先（既定: catalog）",
    )

    # ログインしてサイトへ要求するコマンドの共通オプション
    remote = argparse.ArgumentParser(add_help=False)
    remote.add_argument("--interval", type=float, metavar="SEC", help="リクエスト間の待機秒")
    remote.add_argument(
        "--timeout", type=float, default=60.0, metavar="SEC", help="HTTP タイムアウト秒"
    )
    remote.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        metavar="PATH",
        help="認証情報を読む .env ファイル（既定: ./.env）",
    )

    download = argparse.ArgumentParser(add_help=False)
    download.add_argument(
        "--from",
        dest="from_month",
        required=True,
        type=_month_arg,
        metavar="YYYY-MM",
        help="開始年月",
    )
    download.add_argument(
        "--to",
        dest="to_month",
        type=_month_arg,
        metavar="YYYY-MM",
        help="終了年月（省略時は --from と同じ月）",
    )
    download.add_argument(
        "--symbols",
        nargs="+",
        metavar="CODE",
        help="銘柄コード（省略時はカタログの全銘柄）。一覧は `clicksec-dl symbols <product>`",
    )
    download.add_argument(
        "--out", type=Path, default=Path("data"), help="保存先ルート（既定: data）"
    )
    download.add_argument(
        "--force", action="store_true", help="既存ファイルがあっても再取得して上書きする"
    )
    download.add_argument(
        "--extract", action="store_true", help="ZIP の中身を同じディレクトリへ展開する"
    )
    download.add_argument(
        "--dry-run", action="store_true", help="ログインせず、保存済みカタログで対象だけ表示する"
    )
    download.add_argument(
        "--no-scan",
        action="store_true",
        help="一覧ページを再走査せず、保存済みのカタログだけで対象を決める",
    )
    download.add_argument(
        "--retries", type=int, default=3, metavar="N", help="1 件あたりの最大試行回数"
    )

    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for product in PRODUCTS.values():
        sub.add_parser(
            product.name,
            parents=[download, remote, catalog_opts, verbosity],
            help=f"{product.label} のヒストリカルデータを取得する",
        )

    symbols_parser = sub.add_parser(
        "symbols", parents=[catalog_opts, verbosity], help="カタログの銘柄を一覧表示する"
    )
    symbols_parser.add_argument("product", choices=sorted(PRODUCTS))

    catalog_parser = sub.add_parser("catalog", help="銘柄カタログを操作する")
    catalog_sub = catalog_parser.add_subparsers(dest="catalog_command", required=True)
    update = catalog_sub.add_parser(
        "update",
        parents=[remote, catalog_opts, verbosity],
        help="一覧ページを走査してカタログを更新する",
    )
    update.add_argument("product", choices=sorted(PRODUCTS))
    update.add_argument(
        "--years",
        type=_years_arg,
        metavar="YYYY[-YYYY]",
        help="走査する年（省略時はサイトにある全年）",
    )
    return parser


def configure_logging(verbose: bool, quiet: bool) -> None:
    """パッケージのロガーだけを標準エラー出力へ向ける。root は触らない。"""
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.handlers.clear()
    log.addHandler(handler)
    log.setLevel(level)


def _load_catalog_or_error(catalog_dir: Path, product: Product) -> Catalog | None:
    try:
        return load_catalog(catalog_dir, product)
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        log.error("カタログを読めません (%s): %s", catalog_path(catalog_dir, product), e)
        raise _ConfigError from None


class _ConfigError(Exception):
    """ログ出力済みの設定エラー。"""


def run_symbols(product: Product, args: argparse.Namespace) -> int:
    catalog = _load_catalog_or_error(args.catalog_dir, product)
    if catalog is None or not catalog.entries:
        log.error(
            "カタログがありません。`clicksec-dl catalog update %s` で作成してください", product.name
        )
        return EXIT_CONFIG
    print(
        f"{product.label} ({product.name}) の銘柄: {len(catalog.entries)} 件"
        f"（カタログ更新日 {catalog.updated_at}）"
    )
    id_w = max(len(e.id) for e in catalog.entries)
    code_w = max(len(e.code) for e in catalog.entries)
    for e in catalog.entries:
        span = f"{min(e.months)} 〜 {max(e.months)}" if e.months else "-"
        print(f"  {e.id:<{id_w}}  {e.code:<{code_w}}  {span:<19}  {e.name}")
    return EXIT_OK


def _credentials(env_file: Path) -> tuple[str, str] | None:
    load_dotenv(env_file)
    username = os.environ.get(ENV_USERNAME)
    password = os.environ.get(ENV_PASSWORD)
    if not username or not password:
        log.error(
            "環境変数 %s / %s が設定されていません（%s にも記載できます）",
            ENV_USERNAME,
            ENV_PASSWORD,
            env_file,
        )
        return None
    return username, password


def _login(product: Product, args: argparse.Namespace):
    creds = _credentials(args.env_file)
    if creds is None:
        raise _ConfigError
    session = new_session(os.environ.get(ENV_USER_AGENT))
    try:
        ctx = login(session, product, *creds, timeout=args.timeout)
    except LoginError as e:
        log.error("ログイン失敗: %s", e)
        raise _ConfigError from None
    except requests.RequestException as e:
        log.error("ログイン中の通信エラー: %s", e)
        raise _ConfigError from None
    log.info("ログイン成功")
    return session, ctx


def _scan_and_save(session, product, catalog, ctx, args, years) -> None:
    interval = args.interval if args.interval is not None else product.default_interval
    stats = scan(
        session, product, catalog, ctx.form, years=years, interval=interval, timeout=args.timeout
    )
    path = save_catalog(args.catalog_dir, catalog)
    if stats.new_symbols:
        log.info("新しい銘柄: %s", ", ".join(stats.new_symbols))
    log.info(
        "カタログ更新: %d 銘柄、新しい月 %d 件 → %s", len(catalog.entries), stats.new_months, path
    )


def run_catalog_update(product: Product, args: argparse.Namespace) -> int:
    catalog = _load_catalog_or_error(args.catalog_dir, product) or Catalog(product.name)
    session, ctx = _login(product, args)
    try:
        _scan_and_save(session, product, catalog, ctx, args, args.years)
    except requests.RequestException as e:
        log.error("一覧ページの取得に失敗しました: %s", e)
        return EXIT_PARTIAL
    return EXIT_OK


def run_download(product: Product, args: argparse.Namespace) -> int:
    try:
        months = month_range(args.from_month, args.to_month or args.from_month)
    except ValueError as e:
        log.error("%s", e)
        return EXIT_CONFIG
    if args.retries < 1:
        log.error("--retries は 1 以上を指定してください")
        return EXIT_CONFIG

    catalog = _load_catalog_or_error(args.catalog_dir, product) or Catalog(product.name)
    session = ctx = None
    if not args.dry_run:
        session, ctx = _login(product, args)
        if not args.no_scan:
            # 対象期間の年だけ一覧を再走査し、新しい銘柄・月をカタログへ取り込む
            years = sorted({y for y, _ in months})
            try:
                _scan_and_save(session, product, catalog, ctx, args, years)
            except requests.RequestException as e:
                log.warning("一覧ページの取得に失敗したため、保存済みのカタログを使います: %s", e)

    if not catalog.entries:
        log.error(
            "カタログに銘柄がありません。`clicksec-dl catalog update %s` を実行してください",
            product.name,
        )
        return EXIT_CONFIG
    try:
        symbols = select_symbols(catalog.symbols(), args.symbols)
    except ValueError as e:
        log.error("%s", e)
        return EXIT_CONFIG

    # 年月ごとに使う ID を決める。走査済みの年は、一覧にリンクがある月だけを要求する
    jobs = []
    for y, m in months:
        for s in symbols:
            resolved = catalog.resolve(s.code, y, m)
            if resolved is not None:
                jobs.append((y, m, resolved))
    skipped = len(months) * len(symbols) - len(jobs)
    out_root: Path = args.out
    log.info(
        "%s: %d-%02d 〜 %d-%02d、%d 銘柄、計 %d 件（一覧に無い %d 件は除外）→ %s",
        product.label,
        *months[0],
        *months[-1],
        len(symbols),
        len(jobs),
        skipped,
        out_root / product.name,
    )

    if args.dry_run:
        for y, m, s in jobs:
            print(f"{y}-{m:02d} {s.code:<14} {build_url(product, y, m, s)}")
        return EXIT_OK

    interval = args.interval if args.interval is not None else product.default_interval
    counts: Counter[Outcome] = Counter()
    for i, (y, m, s) in enumerate(jobs):
        if i > 0 and interval > 0:
            time.sleep(interval)
        r = download_one(
            session,
            product,
            y,
            m,
            s,
            out_root=out_root,
            extra_form=ctx.form,
            retries=args.retries,
            force=args.force,
            extract=args.extract,
            timeout=args.timeout,
        )
        counts[r.outcome] += 1
        _log_result(r)

    log.info(
        "完了: 成功 %d / 既存 %d / データなし %d / 失敗 %d",
        counts[Outcome.DOWNLOADED],
        counts[Outcome.EXISTING],
        counts[Outcome.NO_DATA],
        counts[Outcome.FAILED],
    )
    return EXIT_PARTIAL if counts[Outcome.FAILED] else EXIT_OK


def _log_result(r) -> None:
    head = f"{r.year}-{r.month:02d} {r.symbol.code}"
    if r.outcome is Outcome.DOWNLOADED:
        log.info("[成功]     %s → %s", head, r.path)
    elif r.outcome is Outcome.EXISTING:
        log.info("[既存]     %s (%s)", head, r.path)
    elif r.outcome is Outcome.NO_DATA:
        log.info("[データなし] %s: %s", head, r.detail)
    else:
        log.error("[失敗]     %s: %s", head, r.detail)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose, args.quiet)
    try:
        if args.command == "symbols":
            return run_symbols(PRODUCTS[args.product], args)
        if args.command == "catalog":
            return run_catalog_update(PRODUCTS[args.product], args)
        return run_download(PRODUCTS[args.command], args)
    except _ConfigError:
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
