"""名寄せ・ノイズ除去・関連度スコア（§6.2）・成人向け排除（R9）。"""
from __future__ import annotations

import re
import unicodedata

from . import config


_GOODS_TITLE_MARKERS = (
    "アクリル", "キーホルダー", "キーチェーン", "缶バッジ", "ステッカー",
    "クリアファイル", "ポスター", "ジグソーパズル", "ぬいぐるみ",
    "フィギュア", "チャーム", "タオル", "クッション", "マグカップ",
    "トートバッグ", "ショッピングバッグ", "Tシャツ", "ホルダー",
)


def classify_media(media: str, title: str) -> str:
    """楽天BooksGameに混在する非ゲームのキャラクターグッズを表示上補正する。"""
    if media == "game" and any(marker in (title or "") for marker in _GOODS_TITLE_MARKERS):
        return "goods"
    return media


def normalize(text: str) -> str:
    """照合用正規化: NFKC → 小文字 → 空白・中点類を除去。"""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[\s・･·、,．.]+", "", t)


def name_variants(name: str, aliases: list[str]) -> list[str]:
    return [normalize(n) for n in [name, *aliases] if n and normalize(n)]


def name_in_text(name: str, text: str) -> bool:
    """Latin names must not match inside another word (Eve != Evelyn)."""
    needle = normalize(name)
    haystack = normalize(text)
    if re.fullmatch(r"[a-z0-9!_-]+", needle):
        # Keep word boundaries before removing spaces/punctuation.
        haystack = unicodedata.normalize("NFKC", text or "").casefold()
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", haystack))
    return bool(needle and needle in haystack)


def _author_parts(author_raw: str) -> list[str]:
    """複数名義（スラッシュ・カンマ区切り）を正規化して分割。"""
    raw = unicodedata.normalize("NFKC", author_raw or "")
    # Ampersands and middle dots may belong to a band's/person's name.
    parts = re.split(r"[/,、，×]", raw)
    for group in re.findall(r"\(([^()]*)\)", raw):
        group = re.sub(r"^\s*cv[.:：]?\s*", "", group, flags=re.I)
        parts.extend(re.split(r"[・/,、]", group))
    return [normalize(p) for p in parts if normalize(p)]


def relevance_score(record: dict, name: str, aliases: list[str], anchors: list[str] | None = None) -> float:
    """フィールド一致=1.0 / タイトル一致=0.7 / 説明文のみ=0.4 / 不一致=0.0"""
    variants = name_variants(name, aliases)
    if not variants:
        return 0.0
    # 曖昧名プロファイル（anchors指定あり）: 全APIを対象に、
    # 「アーティスト/著者の完全一致」か「公開アンカー語の出現」のどちらかを必須にする。
    # （部分一致 hana⊂Hanada や、APIの曖昧なartistName一致による混入を防ぐ。）
    anchors = anchors or []
    author_raw = record.get("author_or_artist", "") or ""
    exact_author = any(v in _author_parts(author_raw) for v in variants)
    if anchors and not exact_author:
        haystack = " ".join([
            record.get("title", ""), author_raw, record.get("caption", ""),
        ])
        if not any(name_in_text(anchor, haystack) for anchor in anchors):
            return 0.0
    if exact_author:
        return config.SCORE_FIELD_MATCH
    for v in [name, *aliases]:
        if name_in_text(v, record.get("title", "")):
            return config.SCORE_TITLE_MATCH
    for v in [name, *aliases]:
        if name_in_text(v, record.get("caption", "")):
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


def is_noise(record: dict) -> bool:
    """幅が広すぎる周辺商品（中古・楽譜/スコア・カラオケ等）を判定して既定で除外。

    個人が「推し本人の新刊・新譜・発売予定」を見つけやすくするためのフィルタ。
    タイトルまたは著者/アーティスト欄にNG_NOISE_WORDSを含む商品を対象にする。
    config.FILTER_NOISE=False（環境変数OSHI_FILTER_NOISE=0）で無効化できる。
    """
    if not config.FILTER_NOISE:
        return False
    hay = normalize(" ".join([record.get("title", ""),
                              record.get("author_or_artist", "")]))
    return any(normalize(w) in hay for w in config.NG_NOISE_WORDS)


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
        if is_excluded(r) or is_noise(r):
            continue
        score = relevance_score(r, name, aliases, anchors)
        if score < config.SCORE_THRESHOLD:
            continue
        # 説明文だけに名前が出る「幅が広すぎる関連商品」は、信頼フィールド
        # （author/artistName）検索の結果以外では既定で除外する。
        if (not config.SHOW_CAPTION_ONLY
                and not r.get("trusted_field_match")
                and score <= config.SCORE_CAPTION_MATCH):
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
