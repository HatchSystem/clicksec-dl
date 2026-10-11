import pytest

from clicksec_dl.auth import LOGIN_URL, LoginError, extract_guid, login
from clicksec_dl.products import CFD, FX
from conftest import FakeResponse, FakeSession

# SSO が返すリダイレクト URL を模した値（GUID 以外も架空）
TOKEN_URL = (
    "https://kabu.click-sec.com/sec2/to-main?t=GUID%3A99999%2CCSID%3Aabc%2CACNB%3A000000"
    "%2CSIGN%3AZmFrZQ%3D%3D&p=03&rp="
)


def _login_session(final: FakeResponse) -> FakeSession:
    session = FakeSession([FakeResponse(), final])
    session.cookies.set("JSESSIONID", "abc")
    return session


def _redirected(text: str = "<html>top</html>") -> FakeResponse:
    return FakeResponse(
        text=text,
        url="https://kabu.click-sec.com/sec2/mypage/top.do;jsessionid=x",
        history=[FakeResponse(status_code=302, url=LOGIN_URL), FakeResponse(url=TOKEN_URL)],
    )


def test_login_fx_posts_product_fields():
    session = _login_session(_redirected())
    ctx = login(session, FX, "user", "pass")

    method, url, kwargs = session.calls[1]
    assert (method, url) == ("POST", LOGIN_URL)
    assert kwargs["data"] == {
        "j_username": "user",
        "j_password": "pass",
        "LoginForm": "Login",
        "s": "01",
        "p": "03",
        "sp": "",
        "rp": "",
    }
    assert ctx.form == {}  # FX は guid を送らない
    assert len(session.calls) == 2


def test_login_cfd_takes_guid_from_redirect_token():
    ctx = login(_login_session(_redirected()), CFD, "user", "pass")
    assert ctx.guid == "99999"
    assert ctx.form == {"guid": "99999"}


def test_login_cfd_fails_without_guid():
    session = _login_session(FakeResponse(text="<html>top</html>"))
    with pytest.raises(LoginError, match="guid"):
        login(session, CFD, "user", "pass")


def test_extract_guid_falls_back_to_hidden_input():
    resp = FakeResponse(text='<input type="hidden" id="f_guid" name="guid" value="12345" />')
    assert extract_guid(resp) == "12345"


def test_extract_guid_ignores_lookalikes():
    resp = FakeResponse(url="https://x/?t=NOTGUID%3A1%2CCSID%3A2")
    assert extract_guid(resp) is None


def test_login_fails_without_session_cookie():
    session = FakeSession([FakeResponse(), FakeResponse()])
    with pytest.raises(LoginError, match="JSESSIONID"):
        login(session, FX, "user", "pass")


def test_login_fails_when_form_is_shown_again():
    session = _login_session(FakeResponse(text='<input name="j_password">'))
    with pytest.raises(LoginError, match="再表示"):
        login(session, FX, "user", "pass")
