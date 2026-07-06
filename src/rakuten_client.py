"""楽天ウェブサービスAPIクライアント。

ハードルール:
- R1: 全リクエストをプロセス内で直列化し1.2秒以上の間隔を保証（スレッドセーフ）
- 429/5xx: 指数バックオフ最大5回。400系はスキップしてログ（404=結果なし扱い）
- 部分成功を正常系とする（呼び出し側は None を「このAPIは今回取れなかった」として継続）
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

import requests

from . import config

logger = logging.getLogger(__name__)

# エンドポイント（docs/phase0_field_mapping.md で原文確認済み）
ENDPOINTS = {
    "books_book":     "https://openapi.rakuten.co.jp/services/api/BooksBook/Search/20170404",
    "books_cd":       "https://openapi.rakuten.co.jp/services/api/BooksCD/Search/20170404",
    "books_dvd":      "https://openapi.rakuten.co.jp/services/api/BooksDVD/Search/20170404",
    "books_magazine": "https://openapi.rakuten.co.jp/services/api/BooksMagazine/Search/20170404",
    "books_game":     "https://openapi.rakuten.co.jp/services/api/BooksGame/Search/20170404",
    "books_total":    "https://openapi.rakuten.co.jp/services/api/BooksTotal/Search/20170404",
    "kobo":           "https://openapi.rakuten.co.jp/services/api/Kobo/EbookSearch/20170426",
    "ichiba":         "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401",
}


class RateLimiter:
    """プロセス内グローバルの直列レートリミッタ（R1）。"""

    def __init__(self, interval: float):
        self.interval = interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.interval:
                time.sleep(self.interval - delta)
            self._last = time.monotonic()


_rate_limiter = RateLimiter(config.REQUEST_INTERVAL_SEC)


class DbRateLimiter:
    """Postgres運用（サーバーレス等の複数インスタンス）向け。

    rate_state行のSELECT ... FOR UPDATEで全インスタンスのAPIリクエストを直列化し、
    前回リクエストから1.2秒未満ならロックを保持したままsleepする（R1）。
    """

    def __init__(self, interval: float):
        self.interval = interval

    def wait(self) -> None:
        import datetime as dt

        from sqlalchemy import text

        from . import db
        eng = db.get_engine()
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO rate_state (id, last_at) VALUES (1, :epoch) "
                "ON CONFLICT (id) DO NOTHING"), {"epoch": dt.datetime(1970, 1, 1)})
            row = conn.execute(text(
                "SELECT last_at FROM rate_state WHERE id = 1 FOR UPDATE")).one()
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            elapsed = (now - row.last_at).total_seconds()
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            conn.execute(text("UPDATE rate_state SET last_at = :now WHERE id = 1"),
                         {"now": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)})


def default_rate_limiter():
    """Postgres接続時はDB直列化、それ以外（SQLite/ローカル1プロセス）はプロセス内直列化。"""
    if config.DATABASE_URL:
        return DbRateLimiter(config.REQUEST_INTERVAL_SEC)
    return _rate_limiter


class RakutenClient:
    def __init__(self, session: Optional[requests.Session] = None,
                 rate_limiter: Optional[RateLimiter] = None):
        if not config.RAKUTEN_APP_ID:
            logger.warning("RAKUTEN_APP_ID が未設定です。リクエストは失敗します。")
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter or default_rate_limiter()

    def search(self, api: str, params: dict[str, Any]) -> Optional[dict]:
        """1回の検索。成功時はレスポンスdict、恒久的失敗時はNone。"""
        url = ENDPOINTS[api]
        q: dict[str, Any] = {
            "applicationId": config.RAKUTEN_APP_ID,
            "format": "json",
            "formatVersion": 2,
            **params,
        }
        if config.RAKUTEN_ACCESS_KEY:
            q["accessKey"] = config.RAKUTEN_ACCESS_KEY
        if config.RAKUTEN_AFFILIATE_ID:
            q["affiliateId"] = config.RAKUTEN_AFFILIATE_ID

        headers = {}
        if config.SITE_URL:  # 「許可されたWebサイト」との突合に備えRefererを明示
            headers["Referer"] = config.SITE_URL
        for attempt in range(config.MAX_RETRIES):
            self.rate_limiter.wait()
            try:
                resp = self.session.get(url, params=q, timeout=30, headers=headers)
            except requests.RequestException as exc:
                logger.warning("%s: 接続エラー(%s) attempt=%d", api, exc, attempt + 1)
                time.sleep(config.BACKOFF_BASE_SEC * (2 ** attempt))
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    logger.error("%s: JSONデコード失敗", api)
                    return None
            if resp.status_code == 404:  # not_found = 該当なし
                return {"count": 0, "Items": [], "items": []}
            if resp.status_code == 400:
                logger.error("%s: 400 wrong_parameter params=%s body=%s",
                             api, {k: v for k, v in q.items()
                                   if k not in ("applicationId", "accessKey", "affiliateId")},
                             resp.text[:300])
                return None
            if resp.status_code in (429, 500, 503):
                wait = config.BACKOFF_BASE_SEC * (2 ** attempt)
                logger.warning("%s: HTTP %d retry in %.1fs", api, resp.status_code, wait)
                time.sleep(wait)
                continue
            logger.error("%s: 予期しないHTTP %d", api, resp.status_code)
            return None

        logger.error("%s: リトライ上限到達", api)
        return None
