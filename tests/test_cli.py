import logging

import pytest

from clicksec_dl import cli
from clicksec_dl.catalog import Catalog, ListedSymbol, save_catalog


@pytest.fixture(autouse=True)
def _reset_logging():
    yield
    logging.getLogger("clicksec_dl").handlers.clear()


@pytest.fixture
def catalog_dir(tmp_path):
    catalog = Catalog("fx")
    catalog.merge(
        2016,
        [
            ListedSymbol("01", "USDJPY", "米ドル/円", {"2016-01", "2016-02"}),
            ListedSymbol("21", "USDJPY", "米ドル/円", {"2016-01", "2016-02", "2016-03"}),
            ListedSymbol("22", "EURJPY", "ユーロ/円", {"2016-02", "2016-03"}),
        ],
        "2026-10-01",
    )
    catalog.merge(2015, [ListedSymbol("01", "USDJPY", "米ドル/円", {"2015-12"})], "2026-10-01")
    save_catalog(tmp_path / "catalog", catalog)
    return tmp_path / "catalog"


def test_symbols_lists_catalog(catalog_dir, capsys):
    assert cli.main(["symbols", "fx", "--catalog-dir", str(catalog_dir)]) == 0
    out = capsys.readouterr().out
    assert "3 件" in out
    assert "01" in out and "2015-12 〜 2016-02" in out and "米ドル/円" in out


def test_symbols_without_catalog_is_config_error(tmp_path, capsys):
    assert cli.main(["symbols", "cfd", "--catalog-dir", str(tmp_path)]) == cli.EXIT_CONFIG
    assert "catalog update cfd" in capsys.readouterr().err


def test_dry_run_resolves_ids_and_skips_unlisted_months(catalog_dir, capsys):
    code = cli.main(
        [
            "fx",
            "--from",
            "2015-12",
            "--to",
            "2016-03",
            "--catalog-dir",
            str(catalog_dir),
            "--dry-run",
        ]
    )
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    pairs = [
        (line.split()[0], line.split()[1], line.split("&c=")[1].split("&")[0]) for line in lines
    ]
    assert pairs == [
        ("2015-12", "USDJPY", "01"),
        ("2016-01", "USDJPY", "21"),
        ("2016-02", "EURJPY", "22"),
        ("2016-02", "USDJPY", "21"),
        ("2016-03", "EURJPY", "22"),
        ("2016-03", "USDJPY", "21"),
    ]


def test_dry_run_without_catalog_is_config_error(tmp_path):
    code = cli.main(["fx", "--from", "2016-01", "--catalog-dir", str(tmp_path), "--dry-run"])
    assert code == cli.EXIT_CONFIG


def test_unknown_symbol_is_config_error(catalog_dir, capsys):
    code = cli.main(
        [
            "fx",
            "--from",
            "2016-01",
            "--symbols",
            "NOPE",
            "--catalog-dir",
            str(catalog_dir),
            "--dry-run",
        ]
    )
    assert code == cli.EXIT_CONFIG
    assert "NOPE" in capsys.readouterr().err


def test_reversed_range_is_config_error():
    assert cli.main(["fx", "--from", "2025-02", "--to", "2025-01"]) == cli.EXIT_CONFIG


@pytest.mark.parametrize(
    "argv", [["fx", "--from", "2025-13"], ["catalog", "update", "fx", "--years", "2026-2020"]]
)
def test_invalid_arguments_are_usage_errors(argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2


def test_missing_credentials_is_config_error(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(cli.ENV_USERNAME, raising=False)
    monkeypatch.delenv(cli.ENV_PASSWORD, raising=False)
    code = cli.main(["fx", "--from", "2024-12", "--env-file", str(tmp_path / "none")])
    assert code == cli.EXIT_CONFIG
    assert cli.ENV_USERNAME in capsys.readouterr().err


def test_credentials_from_env_file_reach_login(tmp_path, monkeypatch):
    monkeypatch.delenv(cli.ENV_USERNAME, raising=False)
    monkeypatch.delenv(cli.ENV_PASSWORD, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CLICKSEC_J_USERNAME=u\nCLICKSEC_J_PASSWORD=p\n", encoding="utf-8")

    seen = {}

    def fake_login(session, product, username, password, **kwargs):
        seen.update(username=username, password=password)
        raise cli.LoginError("テスト用に失敗させる")

    monkeypatch.setattr(cli, "login", fake_login)
    code = cli.main(["catalog", "update", "fx", "--env-file", str(env_file)])

    assert code == cli.EXIT_CONFIG
    assert seen == {"username": "u", "password": "p"}


def _period(argv, now):
    args = cli.build_parser().parse_args(["fx", *argv])
    return cli.resolve_period(args, now)


@pytest.mark.parametrize(
    "argv, expected",
    [
        (["--this-month"], [(2026, 1)]),
        (["--last-month"], [(2025, 12)]),  # 年をまたぐ
        (["--last-month", "--this-month"], [(2025, 12), (2026, 1)]),
        (["--from", "2025-06"], [(2025, 6)]),
    ],
)
def test_resolve_period(argv, expected):
    from datetime import datetime

    from clicksec_dl.months import JST

    assert _period(argv, datetime(2026, 1, 5, tzinfo=JST)) == expected


@pytest.mark.parametrize(
    "argv, message",
    [
        (["--this-month", "--from", "2025-01"], "同時に指定できません"),
        (["--last-month", "--to", "2025-01"], "同時に指定できません"),
        ([], "期間を指定してください"),
    ],
)
def test_resolve_period_rejects_invalid(argv, message):
    with pytest.raises(ValueError, match=message):
        _period(argv, None)


def test_missing_period_is_config_error(capsys):
    assert cli.main(["fx", "--dry-run"]) == cli.EXIT_CONFIG
    assert "期間を指定してください" in capsys.readouterr().err
