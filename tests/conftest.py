"""テスト用の偽 HTTP セッション。実サーバーへは接続しない。"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import pytest
import requests
from requests.cookies import RequestsCookieJar


@dataclass
class FakeResponse:
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    content: bytes = b""
    text: str = ""
    url: str = ""
    encoding: str | None = None
    history: list[FakeResponse] = field(default_factory=list)
    apparent_encoding: str = "utf-8"

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """与えた応答（または例外）を呼び出し順に返す。"""

    def __init__(self, responses: list[FakeResponse | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []
        self.cookies = RequestsCookieJar()
        self.headers: dict[str, str] = {}

    def get(self, url: str, **kwargs) -> FakeResponse:
        return self._next("GET", url, kwargs)

    def post(self, url: str, **kwargs) -> FakeResponse:
        return self._next("POST", url, kwargs)

    def _next(self, method: str, url: str, kwargs: dict) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"予定外のリクエスト: {method} {url}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def zip_response(filename: str, files: dict[str, bytes] | None = None) -> FakeResponse:
    return FakeResponse(
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        content=make_zip(files or {"a.csv": b"1,2,3\n"}),
    )


@pytest.fixture
def no_sleep():
    return lambda _seconds: None
