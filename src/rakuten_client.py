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


class DeadlineReached(Exception):
    pass


def remaining(deadline: float | None) -> float:
    seconds = float("inf") if deadline is None else deadline - time.monotonic()
    if seconds <= 0:
        raise DeadlineReached()
    return seconds

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

    def wait(self, deadline: float | None = None) -> None:
        with self._lock:
            now = time.monotonic()
            target = self._last + self.interval
            while now < target:
                if target - now >= remaining(deadline):
                    raise DeadlineReached()
                time.sleep(target - now)
                now = time.monotonic()
            self._last = now


_rate_limiter = RateLimiter(config.REQUEST_INTERVAL_SEC)


class DbRateLimiter:
    """Postgres運用（サーバーレス等の複数インスタンス）向け。

    rate_state行のSELECT ... FOR UPDATEで全インスタンスのAPIリクエストを直列化し、
    前回リクエストから1.2秒未満ならロックを保持したままsleepする（R1）。
    """

    def __init__(self, interval: float):
        self.interval = interval

    def wait(self, deadline: float | None = None) -> None:
        import datetime as dt

        from sqlalchemy import text

        from . import db
        eng = db.get_engine()
        with eng.begin() as conn:
            if deadline is not None:
                # Bound lock waits as well as network waits on PostgreSQL.
                ms = max(1, int(min(remaining(deadline), 2.0) * 1000))
                conn.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": f"{ms}ms"})
            conn.execute(text(
                "INSERT INTO rate_state (id, last_at) VALUES (1, :epoch) "
                "ON CONFLICT (id) DO NOTHING"), {"epoch": dt.datetime(1970, 1, 1)})
            row = conn.execute(text(
                "SELECT last_at FROM rate_state WHERE id = 1 FOR UPDATE")).one()
            now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            elapsed = (now - row.last_at).total_seconds()
            if elapsed < self.interval:
                if self.interval - elapsed >= remaining(deadline):
                    raise DeadlineReached()
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

    def search(self, api: str, params: dict[str, Any], deadline: float | None = None) -> Optional[dict]:
        from sqlalchemy.exc import SQLAlchemyError
        try:
            return self._search(api, params, deadline)
        except (DeadlineReached, SQLAlchemyError):
            logger.warning("%s: time budget or database lock exhausted", api)
            return None

    def _search(self, api: str, params: dict[str, Any], deadline: float | None) -> Optional[dict]:
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
        if config.SITE_URL:
            # 2026年版APIは「許可されたWebサイト」(origins)とOrigin/Refererを突合する。
            # 登録ドメインをOrigin(スキーム+ホスト)とRefererの両方で明示する。
            headers["Origin"] = config.SITE_URL.rstrip("/")
            headers["Referer"] = config.SITE_URL
        for attempt in range(config.MAX_RETRIES):
            remaining(deadline)
            if deadline is None:
                self.rate_limiter.wait()
            else:
                self.rate_limiter.wait(deadline=deadline)
            try:
                # A connect + read timeout must fit within the shared deadline.
                allowance = min(8.0, remaining(deadline) / 2)
                resp = self.session.get(url, params=q, timeout=(min(3.0, allowance), allowance), headers=headers)
            except requests.RequestException as exc:
                logger.warning("%s: 接続エラー(%s) attempt=%d", api, exc, attempt + 1)
                if attempt + 1 < config.MAX_RETRIES:
                    wait = config.BACKOFF_BASE_SEC * (2 ** attempt)
                    if wait >= remaining(deadline):
                        return None
                    time.sleep(wait)
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
                if attempt + 1 < config.MAX_RETRIES:
                    if wait >= remaining(deadline):
                        return None
                    time.sleep(wait)
                continue
            logger.error("%s: 予期しないHTTP %d", api, resp.status_code)
            return None

        logger.error("%s: リトライ上限到達", api)
        return None
