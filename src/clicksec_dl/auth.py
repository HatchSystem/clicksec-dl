"""クリック証券 SSO へのログイン。"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

import requests

from .http import redact_url
from .products import Product

LOGIN_PAGE_URL = "https://sec-sso.click-sec.com/loginweb/"
LOGIN_URL = "https://sec-sso.click-sec.com/loginweb/sso-redirect"

# SSO が発行するトークン（リダイレクト URL の t=）は "GUID:<数字>,CSID:...,SIGN:..." の形
_GUID_IN_TOKEN_RE = re.compile(r"(?:^|,)GUID:(\d+)(?:,|$)")
_GUID_IN_PAGE_RE = re.compile(r"""name=["']guid["'][^>]*value=["'](\d+)["']""", re.IGNORECASE)

log = logging.getLogger(__name__)


class LoginError(Exception):
    """ログインに失敗した。"""


@dataclass
class LoginContext:
    guid: str | None  # 口座の guid。CFD の一覧・ダウンロード要求に必要
    form: dict[str, str] = field(default_factory=dict)  # 一覧・ダウンロード要求に付けるフォーム


def extract_guid(resp: requests.Response) -> str | None:
    """ログイン応答（リダイレクト履歴と本文）から口座の guid を取り出す。

    リダイレクト URL には署名付きトークンが含まれるため、URL そのものはログへ出さない。
    """
    for r in [*getattr(resp, "history", []), resp]:
        for values in parse_qs(urlsplit(r.url or "").query).values():
            for value in values:
                m = _GUID_IN_TOKEN_RE.search(value)
                if m:
                    return m.group(1)
    m = _GUID_IN_PAGE_RE.search(resp.text or "")
    return m.group(1) if m else None


def login(
    session: requests.Session,
    product: Product,
    username: str,
    password: str,
    *,
    timeout: float = 30.0,
) -> LoginContext:
    """ログインし、一覧・ダウンロード要求に必要な情報を返す。失敗時は LoginError。

    Cookie、トークン、パスワードの値はログへ出さない。
    """
    log.debug("ログインページを取得: %s", LOGIN_PAGE_URL)
    page = session.get(LOGIN_PAGE_URL, timeout=timeout)
    page.raise_for_status()

    form = {
        "j_username": username,
        "j_password": password,
        "LoginForm": "Login",
        **product.login_form,
    }
    log.debug("ログイン要求を送信: %s (%s)", LOGIN_URL, product.label)
    resp = session.post(LOGIN_URL, data=form, timeout=timeout)
    resp.raise_for_status()
    log.debug("ログイン応答: status=%s url=%s", resp.status_code, redact_url(resp.url))

    if session.cookies.get("JSESSIONID") is None:
        raise LoginError("JSESSIONID が発行されませんでした。ID / パスワードを確認してください。")

    # ログインフォームが再表示された場合は認証失敗とみなす
    resp.encoding = resp.encoding or "shift_jis"
    if "j_password" in resp.text:
        raise LoginError("ログインフォームが再表示されました。ID / パスワードを確認してください。")

    guid = extract_guid(resp)
    if product.requires_guid and guid is None:
        raise LoginError(f"{product.label} に必要な guid をログイン応答から取得できませんでした。")
    log.debug("guid: %s", "取得済み" if guid else "なし")

    return LoginContext(guid=guid, form={"guid": guid} if product.requires_guid else {})
