import dataclasses

import pytest
import requests

from clicksec_dl.download import Outcome, build_url, download_one, filename_from_headers
from clicksec_dl.products import CFD, FX
from clicksec_dl.symbols import Symbol
from conftest import FakeResponse, FakeSession, make_zip, zip_response

USDJPY = Symbol("21", "USDJPY")
JP225 = Symbol("00001060000", "JP225")


@pytest.mark.parametrize(
    "header, expected",
    [
        ('attachment; filename="USDJPY_202412.zip"', "USDJPY_202412.zip"),
        ("attachment; filename=USDJPY_202412.zip", "USDJPY_202412.zip"),
        ('attachment; filename="dir/../x.zip"', "x.zip"),
        ('attachment; filename="C:\\\\tmp\\\\x.zip"', "x.zip"),
        ("attachment; filename*=UTF-8''%E3%83%86%E3%82%B9%E3%83%88.zip", "テスト.zip"),
        ("attachment", None),
        ("", None),
    ],
)
def test_filename_from_headers(header, expected):
    assert filename_from_headers({"Content-Disposition": header}) == expected


def test_build_url_pads_month():
    assert build_url(FX, 2025, 1, USDJPY) == (
        "https://tb.click-sec.com/fx/historical/historicalDataDownload.do?y=2025&m=01&c=21&n=USDJPY"
    )


def test_download_saves_zip(tmp_path, no_sleep):
    session = FakeSession([zip_response("USDJPY_202412.zip")])
    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)

    assert r.outcome is Outcome.DOWNLOADED
    assert r.path == tmp_path / "fx" / "USDJPY" / "USDJPY_202412.zip"
    assert r.path.is_file()
    assert session.calls[0][0] == "GET"


def test_download_cfd_posts_extra_form(tmp_path, no_sleep):
    session = FakeSession([zip_response("JP225_202412.zip")])
    r = download_one(
        session, CFD, 2024, 12, JP225, out_root=tmp_path, extra_form={"guid": "1"}, sleep=no_sleep
    )

    assert r.outcome is Outcome.DOWNLOADED
    method, url, kwargs = session.calls[0]
    assert method == "POST"
    assert url.startswith(CFD.download_url)
    assert kwargs["data"] == {"guid": "1"}


def test_download_no_data_when_no_filename(tmp_path, no_sleep):
    session = FakeSession([FakeResponse(content=b"<html>")])
    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)
    assert r.outcome is Outcome.NO_DATA
    assert not (tmp_path / "fx").exists()


def test_download_no_data_when_not_zip(tmp_path, no_sleep):
    session = FakeSession(
        [FakeResponse(headers={"Content-Disposition": 'attachment; filename="error.html"'})]
    )
    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)
    assert r.outcome is Outcome.NO_DATA
    assert "error.html" in r.detail


def test_download_retries_then_fails(tmp_path):
    sleeps: list[float] = []
    session = FakeSession(
        [
            requests.ConnectionError("boom"),
            FakeResponse(status_code=500),
            FakeResponse(headers={"Content-Disposition": 'filename="x.zip"'}, content=b"junk"),
        ]
    )
    r = download_one(
        session, FX, 2024, 12, USDJPY, out_root=tmp_path, retries=3, sleep=sleeps.append
    )

    assert r.outcome is Outcome.FAILED
    assert "ZIP" in r.detail
    assert sleeps == [1, 2]  # 最後の試行の後は待たない
    assert not (tmp_path / "fx" / "USDJPY" / "x.zip").exists()
    assert not (tmp_path / "fx" / "USDJPY" / "x.zip.part").exists()


def test_download_recovers_on_retry(tmp_path, no_sleep):
    session = FakeSession([FakeResponse(status_code=503), zip_response("USDJPY_202412.zip")])
    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)
    assert r.outcome is Outcome.DOWNLOADED
    assert len(session.calls) == 2


def test_download_keeps_existing_file(tmp_path, no_sleep):
    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202412.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"keep me")
    session = FakeSession([zip_response("USDJPY_202412.zip")])

    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)

    assert r.outcome is Outcome.EXISTING
    assert existing.read_bytes() == b"keep me"


def test_download_force_overwrites(tmp_path, no_sleep):
    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202412.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    session = FakeSession([zip_response("USDJPY_202412.zip")])

    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, force=True, sleep=no_sleep)

    assert r.outcome is Outcome.DOWNLOADED
    assert existing.read_bytes() != b"old"


def test_download_skips_request_when_filename_predictable(tmp_path, no_sleep):
    product = dataclasses.replace(FX, filename_pattern="{code}_{yyyy}{mm}.zip")
    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202412.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"keep me")
    session = FakeSession([])

    r = download_one(session, product, 2024, 12, USDJPY, out_root=tmp_path, sleep=no_sleep)

    assert r.outcome is Outcome.EXISTING
    assert session.calls == []


def test_download_extracts_when_requested(tmp_path, no_sleep):
    session = FakeSession([zip_response("USDJPY_202412.zip", {"USDJPY_20241202.csv": b"x"})])
    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, extract=True, sleep=no_sleep)

    assert r.outcome is Outcome.DOWNLOADED
    assert (tmp_path / "fx" / "USDJPY" / "USDJPY_20241202.csv").read_bytes() == b"x"


def test_download_extracts_existing_zip(tmp_path, no_sleep):
    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202412.zip"
    existing.parent.mkdir(parents=True)
    from conftest import make_zip

    existing.write_bytes(make_zip({"a.csv": b"a"}))
    session = FakeSession([zip_response("USDJPY_202412.zip")])

    r = download_one(session, FX, 2024, 12, USDJPY, out_root=tmp_path, extract=True, sleep=no_sleep)

    assert r.outcome is Outcome.EXISTING
    assert (tmp_path / "fx" / "USDJPY" / "a.csv").read_bytes() == b"a"


def _set_mtime(path, when):
    import os

    os.utime(path, (when.timestamp(), when.timestamp()))


def test_download_refreshes_partial_month_file(tmp_path, no_sleep):
    from datetime import datetime

    from clicksec_dl.months import JST

    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202609.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"partial")
    _set_mtime(existing, datetime(2026, 9, 15, tzinfo=JST))  # 9 月の途中で取得した途中版
    session = FakeSession([zip_response("USDJPY_202609.zip", {"d.csv": b"full"})])

    r = download_one(session, FX, 2026, 9, USDJPY, out_root=tmp_path, sleep=no_sleep)

    assert r.outcome is Outcome.DOWNLOADED
    assert r.detail == "途中版を更新"
    assert existing.read_bytes() != b"partial"


def test_download_refresh_overwrites_extracted_csv(tmp_path, no_sleep):
    from datetime import datetime

    from clicksec_dl.months import JST

    symbol_dir = tmp_path / "fx" / "USDJPY"
    symbol_dir.mkdir(parents=True)
    zip_path = symbol_dir / "USDJPY_202609.zip"
    zip_path.write_bytes(make_zip({"d.csv": b"partial"}))
    _set_mtime(zip_path, datetime(2026, 9, 15, tzinfo=JST))
    (symbol_dir / "d.csv").write_bytes(b"partial")
    session = FakeSession([zip_response("USDJPY_202609.zip", {"d.csv": b"full"})])

    download_one(session, FX, 2026, 9, USDJPY, out_root=tmp_path, extract=True, sleep=no_sleep)

    assert (symbol_dir / "d.csv").read_bytes() == b"full"


def test_download_keeps_file_saved_after_month_end(tmp_path, no_sleep):
    from datetime import datetime

    from clicksec_dl.months import JST

    existing = tmp_path / "fx" / "USDJPY" / "USDJPY_202609.zip"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"complete")
    _set_mtime(existing, datetime(2026, 10, 3, tzinfo=JST))
    session = FakeSession([])

    r = download_one(session, FX, 2026, 9, USDJPY, out_root=tmp_path, sleep=no_sleep)

    assert r.outcome is Outcome.EXISTING
    assert session.calls == []
