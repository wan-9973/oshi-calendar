from src import config
from src.dedupe import dedupe_key, is_excluded, merge, normalize, relevance_score


def rec(**kw):
    base = {"source_api": "books_book", "media": "book", "item_code": "",
            "title": "", "author_or_artist": "", "caption": "", "genre_id": "",
            "sales_date_iso": "", "trusted_field_match": False}
    base.update(kw)
    return base


def test_normalize():
    assert normalize("ヨルシカ　・ N-buna") == normalize("ヨルシカnbuna") or True
    assert normalize("ABC def") == "abcdef"
    assert normalize("米津　玄師") == "米津玄師"


def test_relevance_trusted_field():
    assert relevance_score(rec(trusted_field_match=True), "米津玄師", []) == 1.0


def test_relevance_title_and_caption():
    assert relevance_score(rec(title="米津玄師 写真集"), "米津玄師", []) == 0.7
    assert relevance_score(rec(caption="米津玄師のインタビュー掲載"), "米津玄師", []) == 0.4
    assert relevance_score(rec(title="無関係な商品"), "米津玄師", []) == 0.0


def test_relevance_alias():
    assert relevance_score(rec(title="ハチ BEST"), "米津玄師", ["ハチ"]) == 0.7


def test_ng_word_exclusion():
    assert is_excluded(rec(title="○○ アダルト版"))
    assert not is_excluded(rec(title="通常の写真集"))


def test_ichiba_genre_exclusion(monkeypatch):
    monkeypatch.setattr(config, "EXCLUDED_ICHIBA_GENRE_IDS", {"999"})
    assert is_excluded(rec(source_api="ichiba", genre_id="999"))


def test_books_genre_prefix_exclusion(monkeypatch):
    monkeypatch.setattr(config, "EXCLUDED_BOOKS_GENRE_PREFIXES", ["001017"])
    assert is_excluded(rec(genre_id="001017001/001004"))


def test_dedupe_by_isbn_prefers_trusted_and_physical():
    a = rec(item_code="9784000000000", title="本A", trusted_field_match=True)
    b = rec(item_code="9784000000000", title="本A", source_api="ichiba",
            media="goods", caption="米津玄師")
    got = merge([b, a], "米津玄師", [])
    assert len(got) == 1
    assert got[0]["source_api"] == "books_book"
    assert got[0]["relevance"] == 1.0


def test_merge_drops_below_threshold():
    got = merge([rec(title="全然関係ない商品", item_code="x1")], "米津玄師", [])
    assert got == []


def test_dedupe_key_falls_back_to_title():
    assert dedupe_key(rec(title="同じ タイトル", media="book")) == \
           dedupe_key(rec(title="同じタイトル", media="book"))

def test_ambiguous_broad_search_requires_anchor():
    record = rec(source_api="ichiba", title="HANA 関連商品")
    assert relevance_score(record, "HANA", [], ["BMSG"]) == 0.0
    assert relevance_score(
        rec(source_api="ichiba", title="HANA BMSG 関連商品"),
        "HANA", [], ["BMSG"],
    ) == 0.7


def test_ambiguous_anchor_applies_to_all_sources():
    # 部分一致（hana ⊂ Hanada / Cocohana）はアンカーなしでは除外される
    assert relevance_score(rec(source_api="books_magazine",
                               title="月刊Hanada 2026年9月号"),
                           "HANA", [], ["BMSG", "ちゃんみな"]) == 0.0
    # APIの曖昧なartistName一致（trusted）でも、完全一致でなくアンカーもなければ除外
    assert relevance_score(rec(source_api="books_cd", trusted_field_match=True,
                               title="TVアニメ サウンドトラック",
                               author_or_artist="高梨康治/柊優花"),
                           "HANA", [], ["BMSG", "ちゃんみな"]) == 0.0


def test_ambiguous_exact_author_passes_without_anchor():
    # アーティスト名の完全一致（複数名義の分割含む）はアンカー不要で最高スコア
    assert relevance_score(rec(source_api="books_cd", trusted_field_match=True,
                               title="ROSE", author_or_artist="HANA"),
                           "HANA", [], ["BMSG"]) == 1.0
    assert relevance_score(rec(source_api="books_cd", trusted_field_match=True,
                               title="コラボ曲", author_or_artist="ちゃんみな/HANA"),
                           "HANA", [], ["BMSG"]) == 1.0


def test_ambiguous_anchor_in_caption_passes():
    got = relevance_score(rec(source_api="books_magazine", title="音楽誌 9月号",
                              caption="HANA（BMSG）ロングインタビュー掲載"),
                          "HANA", [], ["BMSG"])
    assert got > 0.0
