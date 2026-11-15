import datetime as dt
import time
from unittest.mock import MagicMock

from src import config, db
from src.dedupe import relevance_score
from src.quality import reclassify
from src.search_service import search_all, find_or_create_oshi
from src.crawler import run_once
from src.search_gate import acquire, key_for, release
from src.rakuten_client import RakutenClient, RateLimiter


def test_unrelated_authors_and_word_boundaries():
    for name, author in [("Eve", "Evelyn van Kelle"), ("M!LK", "M. L. Knight")]:
        assert relevance_score({"title": "無関係な本", "author_or_artist": author,
                                "trusted_field_match": True}, name, []) == 0
    assert relevance_score({"title": "Everyday Life"}, "Eve", []) == 0
    assert relevance_score({"title": "Eve 写真集"}, "Eve", []) == .7
    assert relevance_score({"author_or_artist": "Eve/別名義"}, "Eve", []) == 1
    assert relevance_score({"author_or_artist": "M!LK"}, "M!LK", []) == 1


def test_expired_deadline_makes_no_network_request():
    session = MagicMock()
    client = RakutenClient(session=session, rate_limiter=RateLimiter(0))
    assert client.search("books_cd", {}, deadline=time.monotonic() - 1) is None
    session.get.assert_not_called()
    result = search_all("Eve", client=client, deadline=time.monotonic() - 1)
    assert result["successful_requests"] == 0
    assert len(result["failed_apis"]) == result["total_requests"] == 8


def test_repair_is_reversible_and_dry_run_does_not_write(test_db):
    oid, _ = find_or_create_oshi("Eve")
    with db.session() as s:
        s.add_all([db.Item(oshi_id=oid, source_api="books_book", item_code="bad",
                           title="設計の本", author_or_artist="Evelyn van Kelle",
                           item_url="https://books.rakuten.co.jp/bad", relevance=1),
                   db.Item(oshi_id=oid, source_api="books_cd", item_code="good",
                           title="AIYOU", author_or_artist="Eve",
                           item_url="https://books.rakuten.co.jp/good", relevance=1)])
        s.commit()
    assert reclassify()["excluded"] == 1
    with db.session() as s:
        assert s.query(db.Item).filter_by(item_code="bad").one().quality_excluded == 0
    assert reclassify(apply=True)["excluded"] == 1
    with db.session() as s:
        assert s.query(db.Item).count() == 2
        assert s.query(db.Item).filter_by(item_code="bad").one().quality_excluded == 1
        assert s.query(db.Item).filter_by(item_code="good").one().quality_excluded == 0
    assert reclassify(apply=True)["changed"] == 0


def test_partial_failure_with_alias_is_not_total_failure(test_db):
    oid, _ = find_or_create_oshi("作家", ["別名"])
    client = MagicMock()
    client.search.side_effect = lambda api, params: None if params.get("author") == "作家" or params.get("artistName") == "作家" or params.get("title") == "作家" or params.get("keyword") == "作家" else {"items": []}
    stats = run_once(budget=16, client=client)
    assert stats["crawled"] == 1
    with db.session() as s:
        queue = s.get(db.CrawlQueue, oid)
        assert queue.last_crawl_at is not None
        assert queue.next_crawl_at < db.utcnow() + dt.timedelta(hours=2)


def test_shared_gate_and_expiry(test_db):
    key = key_for("ip", "192.0.2.1")
    assert "192.0.2.1" not in key
    assert all(acquire(key, 3, 60) for _ in range(3))
    assert not acquire(key, 3, 60)
    with db.session() as s:
        s.get(db.SearchGate, key).expires_at = db.utcnow() - dt.timedelta(seconds=1)
        s.commit()
    assert acquire(key, 3, 60)
    release(key)
    assert acquire(key, 1, 90)

def test_retry_only_fetches_failed_media(test_db):
    oid, _ = find_or_create_oshi('作家')
    client = MagicMock()
    client.search.side_effect = lambda api, params: None if api == 'kobo' else {'items': []}
    run_once(budget=8, client=client)
    with db.session() as s:
        queue = s.get(db.CrawlQueue, oid)
        assert queue.pending_apis == ['kobo']
        queue.next_crawl_at = db.utcnow() - dt.timedelta(seconds=1)
        s.commit()
    client.reset_mock()
    client.search.side_effect = lambda api, params: {'items': []}
    run_once(budget=8, client=client)
    assert client.search.call_count == 1
    assert client.search.call_args.args[0] == 'kobo'
    with db.session() as s:
        assert s.get(db.CrawlQueue, oid).pending_apis == []


def test_budget_allows_one_large_serverless_entity(monkeypatch, test_db):
    monkeypatch.setenv('OSHI_SYNC_SEARCH', '1')
    oid, _ = find_or_create_oshi('作家', ['別名1', '別名2', '別名3'])
    client = MagicMock()
    client.search.return_value = {'items': []}
    assert run_once(budget=24, client=client)['crawled'] == 1

def test_additive_migration_preserves_existing_items(test_db):
    from sqlalchemy import text, inspect
    oid, _ = find_or_create_oshi('migration')
    with db.session() as s:
        s.add(db.Item(oshi_id=oid, source_api='books_cd', item_code='existing', title='既存', item_url='https://books.rakuten.co.jp/x'))
        s.commit()
    engine = db.get_engine()
    with engine.begin() as conn:
        conn.execute(text('ALTER TABLE items DROP COLUMN quality_excluded'))
        conn.execute(text('ALTER TABLE crawl_queue DROP COLUMN pending_apis_json'))
    db._migrate(engine)
    db._migrate(engine)
    with db.session() as s:
        assert s.query(db.Item).one().quality_excluded == 0
        assert s.get(db.CrawlQueue, oid).pending_apis == []
