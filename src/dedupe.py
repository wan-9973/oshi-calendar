"""名寄せ・ノイズ除去・関連度スコア（§6.2）・成人向け排除（R9）。"""
from __future__ import annotations

import re
import unicodedata

from . import config


def normalize(text: str) -> str:
    """照合用正規化: NFKC → 小文字 → 空白・中点類を除去。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s・･·、,．.]+", "", t)


def name_variants(name: str, aliases: list[str]) -> list[str]:
    return [normalize(n) for n in [name, *aliases] if n and normalize(n)]


def relevance_score(record: dict, name: str, aliases: list[str], anchors: list[str]) -> float:
    """フィールド一致=1.0 / タイトル一致=0.7 / 説明文のみ=0.4 / 不一致=0.0"""
    variants = name_variants(name, aliases)
    if not variants:
        return 0.0
    # Broad keyword sources need an additional public entity anchor.
    if anchors and record.get("source_api") in {"ichiba", "books_total"}:
        haystack = normalize(" ".join([
            record.get("title", ""), record.get("author_or_artist", ""),
            record.get("caption", ""),
        ]))
        if not any(normalize(anchor) in haystack for anchor in anchors):
            return 0.0
    if record.get("trusted_field_match"):
        return config.SCORE_FIELD_MATCH
    title = normalize(record.get("title", ""))
    author = normalize(record.get("author_or_artist", ""))
    caption = normalize(record.get("caption", ""))
    for v in variants:
        if v and (v in author):
            return config.SCORE_FIELD_MATCH
    for v in variants:
        if v and v in title:
            return config.SCORE_TITLE_MATCH
    for v in variants:
        if v and v in caption:
            return config.SCORE_CAPTION_MATCH
    return 0.0


def is_excluded(record: dict) -> bool:
    """成人向けジャンル・NGワード排除（R9）。判定不能時は安全側=排除しない範囲を最小に。"""
    genre = str(record.get("genre_id", "") or "")
    if record.get("source_api") == "ichiba":
        if genre in config.EXCLUDED_ICHIBA_GENRE_IDS:
            return True
    else:
        for g in genre.split("/"):
            for prefix in config.EXCLUDED_BOOKS_GENRE_PREFIXES:
                if g.startswith(prefix):
                    return True
    haystack = " ".join([record.get("title", ""), record.get("caption", ""),
                         record.get("genre_name", "") or ""])
    hay = normalize(haystack)
    return any(normalize(w) in hay for w in config.NG_WORDS)


# 名寄せ優先度: 実物メディア > 電子 > 市場（同一商品コードのとき）
_SOURCE_PRIORITY = {"books_book": 0, "books_cd": 0, "books_dvd": 0,
                    "books_magazine": 0, "books_game": 0, "books_total": 1,
                    "kobo": 2, "ichiba": 3}


def dedupe_key(record: dict) -> str:
    code = str(record.get("item_code", "") or "").strip()
    if code:
        return f"code:{code}"
    return f"title:{normalize(record.get('title', ''))}|{record.get('media','')}"


def merge(records: list[dict], name: str, aliases: list[str], anchors: list[str] | None = None) -> list[dict]:
    """スコア付与 → 閾値未満とR9対象を除去 → JAN/ISBN/itemCodeで名寄せ。"""
    anchors = anchors or []
    best: dict[str, dict] = {}
    for r in records:
        if is_excluded(r):
            continue
        score = relevance_score(r, name, aliases, anchors)
        if score < config.SCORE_THRESHOLD:
            continue
        r = {**r, "relevance": score}
        key = dedupe_key(r)
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue
        better = (r["relevance"], -_SOURCE_PRIORITY.get(r["source_api"], 9)) > \
                 (cur["relevance"], -_SOURCE_PRIORITY.get(cur["source_api"], 9))
        if better:
            best[key] = r
    return sorted(best.values(),
                  key=lambda x: (x.get("sales_date_iso") or "", x["relevance"]),
                  reverse=True)
