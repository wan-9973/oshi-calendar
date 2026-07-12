"""横断検索（§6）: 8API直列呼び出し → 正規化 → 名寄せ → DB保存。

部分成功を正常系とする（§5.2）。ドキュメントと実レスポンスの差異は実レスポンスを正とし、
フォールバックチェーンで吸収して差分をログする（§12）。
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Callable, Optional

from . import config, db
from .calendar_service import parse_sales_date
from .dedupe import merge
from .rakuten_client import RakutenClient

logger = logging.getLogger(__name__)


def _first(item: dict, *keys: str, default: str = "") -> Any:
    for k in keys:
        v = item.get(k)
        if v not in (None, "", []):
            return v
    return default


def _to_int(v) -> int | None:
    """API応答の数値フィールドは空文字・文字列数値が混在するため安全に変換（Postgres対策）。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _image(item: dict) -> str:
    v = _first(item, "largeImageUrl", "mediumImageUrl", "smallImageUrl")
    if v:
        return v
    for k in ("mediumImageUrls", "smallImageUrls"):
        urls = item.get(k)
        if isinstance(urls, list) and urls:
            u = urls[0]
            if isinstance(u, dict):  # formatVersion=1系フォールバック
                return u.get("imageUrl", "")
            return str(u)
    return ""


def _affiliate_url(item: dict, api: str) -> str:
    """リンクは楽天ドメインのみ（R6）。affiliateUrl優先、なければitemUrl。"""
    return _first(item, "affiliateUrl", "itemUrl")


def _normalize(api: str, media: str, item: dict, trusted: bool) -> Optional[dict]:
    url = _affiliate_url(item, api)
    title = _first(item, "title", "itemName")
    if not url or not title:
        logger.info("%s: url/titleを解決できずスキップ keys=%s", api, sorted(item.keys())[:20])
        return None
    raw_date = str(_first(item, "salesDate", "releaseDate"))
    iso, precision = parse_sales_date(raw_date)
    price = _to_int(item.get("itemPrice"))
    availability = _to_int(item.get("availability"))
    return {
        "source_api": api,
        "media": media,
        "item_code": str(_first(item, "isbn", "jan", "itemCode", "itemNumber")),
        "title": str(title),
        "author_or_artist": str(_first(item, "author", "artistName", "label", "publisherName", "shopName")),
        "caption": str(_first(item, "itemCaption")),
        "genre_id": str(_first(item, "booksGenreId", "koboGenreId", "genreId")),
        "sales_date": raw_date,
        "sales_date_iso": iso,
        "sales_date_precision": precision,
        "item_url": url,
        "image_url": _image(item),
        "price": price,
        "availability": availability,
        "trusted_field_match": trusted,
    }


def _items_of(resp: dict) -> list[dict]:
    items = resp.get("Items") or resp.get("items") or []
    out = []
    for it in items:
        if isinstance(it, dict) and "Item" in it:  # formatVersion=1フォールバック
            it = it["Item"]
        if isinstance(it, dict):
            out.append(it)
    return out


# 検索プラン（docs/phase0_field_mapping.md §3）。1推し名あたり8リクエスト。
def _plan(name: str) -> list[tuple[str, str, dict, bool]]:
    common_books = {"sort": "-releaseDate", "outOfStockFlag": 1, "hits": 30}
    return [
        ("books_book", "book", {"author": name, **common_books}, True),
        ("books_cd", "cd", {"artistName": name, **common_books}, True),
        ("books_dvd", "dvd", {"artistName": name, **common_books}, True),
        ("books_magazine", "magazine", {"title": name, **common_books}, False),
        ("books_game", "game", {"title": name, **common_books}, False),
        ("kobo", "ebook", {"author": name, "hits": 30}, True),
        ("ichiba", "goods", {"keyword": name, "sort": "-updateTimestamp", "hits": 30}, False),
        ("books_total", "mixed", {"keyword": name, "hits": 30, "outOfStockFlag": 1}, False),
    ]


def requests_per_oshi(alias_count: int = 0) -> int:
    return 8 * (1 + min(alias_count, config.ALIAS_MAX))


ProgressCb = Optional[Callable[[str, int, int], None]]

_MEDIA_LABEL = {"books_book": "書籍", "books_cd": "CD", "books_dvd": "DVD/Blu-ray",
                "books_magazine": "雑誌", "books_game": "ゲーム", "kobo": "電子書籍",
                "ichiba": "グッズ", "books_total": "総合"}


def search_all(name: str, aliases: list[str] | None = None,
               client: RakutenClient | None = None,
               progress: ProgressCb = None) -> dict:
    """全API直列検索。返り値: {'records': [...], 'failed_apis': [...]}"""
    aliases = (aliases or [])[: config.ALIAS_MAX]
    client = client or RakutenClient()
    records: list[dict] = []
    failed: list[str] = []
    plans = []
    for q in [name, *aliases]:
        plans.extend(_plan(q))
    total = len(plans)
    for i, (api, media, params, trusted) in enumerate(plans):
        if progress:
            progress(f"{_MEDIA_LABEL[api]}を検索中", i, total)
        resp = client.search(api, params)
        if resp is None:
            failed.append(api)
            continue  # 部分成功で継続（§12）
        for raw in _items_of(resp):
            rec = _normalize(api, media, raw, trusted)
            if rec:
                records.append(rec)
    merged = merge(records, name, aliases, anchors or [])
    if progress:
        progress("完了", total, total)
    return {"records": merged, "failed_apis": failed}


def save_results(oshi_id: int, merged: list[dict]) -> int:
    """名寄せ済み結果をitems/price_cacheへ保存。新規件数を返す。"""
    now = db.utcnow()
    new_count = 0
    with db.session() as s:
        existing = {r.item_code: r for r in
                    s.query(db.Item).filter(db.Item.oshi_id == oshi_id).all()}
        seen_codes = set()
        for rec in merged:
            code = rec["item_code"] or f"t:{rec['title'][:100]}"
            seen_codes.add(code)
            row = existing.get(code)
            if row is None:
                row = db.Item(oshi_id=oshi_id, item_code=code, first_seen_at=now)
                s.add(row)
                new_count += 1
            row.source_api = rec["source_api"]
            row.media = rec["media"]
            row.title = rec["title"]
            row.author_or_artist = rec["author_or_artist"]
            row.sales_date = rec["sales_date"]
            row.sales_date_iso = rec["sales_date_iso"]
            row.sales_date_precision = rec["sales_date_precision"]
            row.item_url = rec["item_url"]
            row.image_url = rec["image_url"]
            row.relevance = rec["relevance"]
            row.meta_fetched_at = now
            if rec.get("price") is not None:
                s.merge(db.PriceCache(item_code=code, price=rec["price"],
                                      availability=rec.get("availability"),
                                      fetched_at=now))
        s.commit()
    return new_count


def find_or_create_oshi(name: str, aliases: list[str] | None = None) -> tuple[int, bool]:
    """共有キャッシュとしてのoshi行（個人と紐付けない。R8）。(id, created)"""
    import json
    with db.session() as s:
        row = s.query(db.Oshi).filter(db.Oshi.name == name).one_or_none()
        if row:
            row.last_searched_at = db.utcnow()
            s.commit()
            return row.id, False
        row = db.Oshi(name=name, aliases_json=json.dumps(aliases or [], ensure_ascii=False))
        s.add(row)
        s.flush()
        s.add(db.CrawlQueue(oshi_id=row.id, next_crawl_at=db.utcnow()))
        s.commit()
        return row.id, True
