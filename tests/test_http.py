import logging

import pytest

from clicksec_dl.auth import login
from clicksec_dl.http import new_session, redact_url
from clicksec_dl.products import FX
from conftest import FakeResponse, FakeSession


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://kabu.click-sec.com/sec2/mypage/top.do;jsessionid=8AA8B0FE.ap13",
            "https://kabu.click-sec.com/sec2/mypage/top.do;jsessionid=***",
        ),
        (
            "https://x/a.do;JSESSIONID=ABC?y=1",
            "https://x/a.do;JSESSIONID=***?y=1",
        ),
        ("https://x/a.do?jsessionid=ABC&y=1", "https://x/a.do?jsessionid=***&y=1"),
        ("https://x/a.do?y=1", "https://x/a.do?y=1"),
    ],
)
def test_redact_url(url, expected):
    assert redact_url(url) == expected


def test_login_debug_log_hides_session_id(caplog):
    secret = "8AA8B0FEA8B51BA269554C1A8BB141A4.ap13"
    session = FakeSession(
        [FakeResponse(), FakeResponse(url=f"https://x/top.do;jsessionid={secret}")]
    )
    session.cookies.set("JSESSIONID", secret)

    with caplog.at_level(logging.DEBUG, logger="clicksec_dl"):
        login(session, FX, "user", "S3cret-Pw!")

    assert secret not in caplog.text
    assert "S3cret-Pw!" not in caplog.text


def test_new_session_sends_browser_headers():
    session = new_session()
    assert session.headers["User-Agent"].startswith("Mozilla/5.0")
    assert "ja" in session.headers["Accept-Language"]
    assert new_session("custom-agent").headers["User-Agent"] == "custom-agent"
