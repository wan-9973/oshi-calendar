"""サーバーレスモード（同期検索・cron保護）のテスト。"""
import importlib
from unittest.mock import MagicMock, patch


def make_app(monkeypatch, tmp_path, secret="s3cret"):
    monkeypatch.setenv("OSHI_SYNC_SEARCH", "1")
    monkeypatch.setenv("OSHI_DB_PATH", str(tmp_path / "t.db"))
    from src import config, db
    monkeypatch.setattr(config, "CRON_SECRET", secret)
    db.get_engine(f"sqlite:///{tmp_path}/t.db")
    import src.web.app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    return TestClient(webapp.app), webapp


def test_sync_search_returns_done(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    fake = {"records": [{"source_api": "books_book", "media": "book",
                         "item_code": "9784111111111", "title": "新刊",
                         "author_or_artist": "作家", "caption": "",
                         "sales_date": "2026年08月10日", "sales_date_iso": "2026-08-10",
                         "sales_date_precision": "day",
                         "item_url": "https://hb.afl.rakuten.co.jp/x",
                         "image_url": "", "price": 1000, "availability": 1,
                         "relevance": 1.0}],
            "failed_apis": []}
    with patch.object(webapp, "search_all", return_value=fake):
        r = client.post("/api/search", json={"name": "作家"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done" and "oshi_id" in body
    assert client.get(f"/oshi/{body['oshi_id']}").status_code == 200


def test_sync_search_all_failed_returns_503(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    with patch.object(webapp, "search_all",
                      return_value={"records": [], "failed_apis": ["a"] * 8}):
        r = client.post("/api/search", json={"name": "誰か"})
    assert r.status_code == 503


def test_cron_requires_secret(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    assert client.get("/api/cron/retention").status_code == 401
    assert client.get("/api/cron/retention",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = client.get("/api/cron/retention",
                   headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    assert "price_deleted" in r.json()


def test_cron_crawl_uses_budget(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    called = {}

    def fake_crawl(budget=None):
        called["budget"] = budget
        return {"crawled": 0, "requests_used": 0, "new_items": 0}
    with patch.object(webapp, "crawl_run_once", side_effect=fake_crawl):
        r = client.get("/api/cron/crawl", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    from src import config
    assert called["budget"] == config.CRAWL_BUDGET_PER_RUN
