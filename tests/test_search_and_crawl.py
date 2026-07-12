"""search_service / crawler / retention 縺ｮ邨仙粋繝・せ繝茨ｼ・PI縺ｯ繝｢繝・け・峨・""
import datetime as dt
from unittest.mock import MagicMock

from src import db
from src.crawler import capacity_estimate, run_once as crawl_once
from src.retention import run_once as retention_once
from src.search_service import (find_or_create_oshi, requests_per_oshi,
                                save_results, search_all)


def fake_client(items_by_api):
    client = MagicMock()

    def search(api, params):
        return {"count": len(items_by_api.get(api, [])),
                "items": items_by_api.get(api, [])}
    client.search.side_effect = search
    return client


BOOK = {"title": "繝・せ繝井ｽ懷ｮｶ縺ｮ譁ｰ蛻・, "author": "繝・せ繝井ｽ懷ｮｶ", "isbn": "9784111111111",
        "salesDate": "2026蟷ｴ08譛・0譌･", "itemCaption": "隱ｬ譏・,
        "itemUrl": "https://books.rakuten.co.jp/x", 
        "affiliateUrl": "https://hb.afl.rakuten.co.jp/hgc/xxx/?pc=https%3A%2F%2Fbooks.rakuten.co.jp%2Fx",
        "largeImageUrl": "https://thumbnail.image.rakuten.co.jp/x.jpg",
        "itemPrice": 1980, "availability": 5, "booksGenreId": "001004"}

GOODS = {"itemName": "繝・せ繝井ｽ懷ｮｶ 繧｢繧ｯ繝ｪ繝ｫ繧ｹ繧ｿ繝ｳ繝・, "itemCode": "shop:10001",
         "itemUrl": "https://item.rakuten.co.jp/shop/10001/",
         "affiliateUrl": "https://hb.afl.rakuten.co.jp/hgc/xxx/?pc=item",
         "mediumImageUrls": ["https://thumbnail.image.rakuten.co.jp/g.jpg"],
         "itemPrice": 1500, "availability": 1, "genreId": "101"}


def test_search_all_normalizes_and_merges(test_db):
    client = fake_client({"books_book": [BOOK], "ichiba": [GOODS]})
    result = search_all("繝・せ繝井ｽ懷ｮｶ", client=client)
    assert client.search.call_count == 8  # 8API逶ｴ蛻・
    recs = result["records"]
    assert len(recs) == 2
    book = next(r for r in recs if r["media"] == "book")
    assert book["item_code"] == "9784111111111"
    assert book["sales_date_iso"] == "2026-08-10"
    assert book["relevance"] == 1.0
    assert book["item_url"].startswith("https://hb.afl.rakuten.co.jp/")  # R6
    goods = next(r for r in recs if r["media"] == "goods")
    assert goods["relevance"] == 0.7  # 繧ｿ繧､繝医Ν荳閾ｴ
    assert result["failed_apis"] == []


def test_partial_failure_is_normal(test_db):
    client = fake_client({"books_book": [BOOK]})
    client.search.side_effect = lambda api, p: (
        None if api == "ichiba" else {"count": 0, "items": [BOOK] if api == "books_book" else []})
    result = search_all("繝・せ繝井ｽ懷ｮｶ", client=client)
    assert result["failed_apis"] == ["ichiba"]
    assert len(result["records"]) == 1  # 驛ｨ蛻・・蜉溘〒邨先棡縺ｯ謌千ｫ・


def test_save_results_detects_new_items(test_db):
    oshi_id, created = find_or_create_oshi("繝・せ繝井ｽ懷ｮｶ")
    assert created
    client = fake_client({"books_book": [BOOK]})
    r1 = search_all("繝・せ繝井ｽ懷ｮｶ", client=client)
    assert save_results(oshi_id, r1["records"]) == 1
    assert save_results(oshi_id, r1["records"]) == 0  # 2蝗樒岼縺ｯ譁ｰ逹縺ｪ縺・
    with test_db.session() as s:
        pc = s.get(test_db.PriceCache, "9784111111111")
        assert pc.price == 1980


def test_crawler_updates_queue_and_counts_new(test_db):
    oshi_id, _ = find_or_create_oshi("繝・せ繝井ｽ懷ｮｶ")
    client = fake_client({"books_book": [BOOK]})
    stats = crawl_once(budget=100, client=client)
    assert stats["crawled"] == 1
    assert stats["new_items"] == 1
    with test_db.session() as s:
        q = s.get(test_db.CrawlQueue, oshi_id)
        assert q.next_crawl_at > test_db.utcnow()
        # R4: 谺｡蝗槫ｷ｡蝗槭・7譌･莉･蜀・
        assert q.next_crawl_at <= test_db.utcnow() + dt.timedelta(days=7, minutes=1)


def test_crawler_respects_budget(test_db):
    for i in range(3):
        find_or_create_oshi(f"謗ｨ縺養i}")
    client = fake_client({})
    stats = crawl_once(budget=requests_per_oshi(0) * 2, client=client)
    assert stats["crawled"] == 2  # 莠育ｮ怜・縺ｮ2謗ｨ縺励・縺ｿ


def test_crawler_skips_hidden_oshi(test_db):
    oshi_id, _ = find_or_create_oshi("髱櫁｡ｨ遉ｺ縺ｮ謗ｨ縺・)
    with test_db.session() as s:
        s.get(test_db.Oshi, oshi_id).hidden = 1
        s.commit()
    client = fake_client({"books_book": [BOOK]})

    stats = crawl_once(budget=100, client=client)

    assert stats["crawled"] == 0
    assert client.search.call_count == 0
    with test_db.session() as s:
        assert s.get(test_db.CrawlQueue, oshi_id).next_crawl_at > test_db.utcnow()


def test_capacity_estimate_positive():
    assert capacity_estimate() > 0


def test_retention_expires_price_and_requeues_meta(test_db):
    oshi_id, _ = find_or_create_oshi("繝・せ繝井ｽ懷ｮｶ")
    now = test_db.utcnow()
    with test_db.session() as s:
        s.add(test_db.Item(oshi_id=oshi_id, source_api="books_book", item_code="X",
                           title="蜿､縺・膚蜩・, item_url="https://books.rakuten.co.jp/x",
                           meta_fetched_at=now - dt.timedelta(days=91)))
        s.add(test_db.PriceCache(item_code="X", price=100, availability=1,
                                 fetched_at=now - dt.timedelta(hours=25)))
        s.add(test_db.PriceCache(item_code="Y", price=200, availability=1,
                                 fetched_at=now - dt.timedelta(hours=1)))
        q = s.get(test_db.CrawlQueue, oshi_id)
        q.next_crawl_at = now + dt.timedelta(days=5)
        s.commit()
    stats = retention_once(now=now)
    assert stats["price_deleted"] == 1          # R2: 24h雜・・縺ｿ蜑企勁
    assert stats["meta_requeued"] == 1          # R3: 90d雜・・繧ｭ繝･繝ｼ蜈磯ｭ
    with test_db.session() as s:
        assert s.get(test_db.PriceCache, "Y") is not None
        assert s.get(test_db.CrawlQueue, oshi_id).next_crawl_at < now


def test_retention_deletes_unused_oshi(test_db):
    oshi_id, _ = find_or_create_oshi("蠢倥ｌ繧峨ｌ縺滓耳縺・)
    now = test_db.utcnow()
    with test_db.session() as s:
        o = s.get(test_db.Oshi, oshi_id)
        o.last_searched_at = now - dt.timedelta(days=91)
        o.last_viewed_at = now - dt.timedelta(days=91)
        s.commit()
    stats = retention_once(now=now)
    assert stats["oshi_deleted"] == 1
    with test_db.session() as s:
        assert s.get(test_db.Oshi, oshi_id) is None

