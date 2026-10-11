"""ブラウザ相当のヘッダーを持つ HTTP セッション。"""

from __future__ import annotations

import re

import requests

# URL に埋め込まれたセッション ID（;jsessionid=... や ?jsessionid=...）
_SESSION_IN_URL_RE = re.compile(r"([;?&]jsessionid=)[^;?&#/]*", re.IGNORECASE)


def redact_url(url: str) -> str:
    """ログ出力用に、URL 内のセッション ID を伏せる。"""
    return _SESSION_IN_URL_RE.sub(r"\1***", url)


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def browser_headers(user_agent: str | None = None) -> dict[str, str]:
    return {
        "User-Agent": user_agent or DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    }


def new_session(user_agent: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(browser_headers(user_agent))
    return session
