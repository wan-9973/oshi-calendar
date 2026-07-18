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
    assert r.json()["job_run_id"] > 0
    assert r.json()["started_at"].endswith("Z")
    from src import db
    with db.session() as s:
        run = s.get(db.JobRun, r.json()["job_run_id"])
        assert run.job_name == "crawl"
        assert run.status == "success"


def test_health_uses_job_history_not_item_timestamps(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    before = client.get("/api/health")
    assert before.status_code == 200
    assert before.json()["status"] == "initializing"

    with patch.object(webapp, "crawl_run_once",
                      return_value={"crawled": 0, "requests_used": 0, "new_items": 0}):
        assert client.get("/api/cron/crawl",
                          headers={"Authorization": "Bearer s3cret"}).status_code == 200
    with patch.object(webapp, "retention_run_once",
                      return_value={"price_deleted": 0, "meta_requeued": 0,
                                    "oshi_deleted": 0, "job_runs_deleted": 0}):
        assert client.get("/api/cron/retention",
                          headers={"Authorization": "Bearer s3cret"}).status_code == 200

    after = client.get("/api/health").json()
    assert after["status"] == "healthy"
    assert after["jobs"]["crawl"]["last_result"]["crawled"] == 0
    assert after["crawl_queue"]["status"] == "healthy"


def test_failed_cron_is_recorded(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    from fastapi.testclient import TestClient
    failing_client = TestClient(webapp.app, raise_server_exceptions=False)
    with patch.object(webapp, "crawl_run_once", side_effect=RuntimeError("API timeout")):
        r = failing_client.get("/api/cron/crawl",
                               headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 500
    from src import db
    with db.session() as s:
        run = s.query(db.JobRun).order_by(db.JobRun.id.desc()).first()
        assert run.status == "error"
        assert "API timeout" in run.error


def test_health_detects_stuck_running_job(monkeypatch, tmp_path):
    client, _ = make_app(monkeypatch, tmp_path)
    import datetime as dt
    from src import db
    now = db.utcnow()
    with db.session() as s:
        for name in ("crawl", "retention"):
            s.add(db.JobRun(
                job_name=name,
                started_at=now - dt.timedelta(hours=1),
                finished_at=now - dt.timedelta(minutes=59),
                status="success",
                result_json="{}",
            ))
        s.add(db.JobRun(
            job_name="crawl",
            started_at=now - dt.timedelta(minutes=11),
            status="running",
        ))
        s.commit()
    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    assert health["jobs"]["crawl"]["last_run_status"] == "running"


def test_sync_search_reactivates_hidden_profiled_oshi(monkeypatch, tmp_path):
    """プロファイル整備済みの名前は、非表示中でも再検索で自動再公開される（HANA 404対策）。"""
    client, webapp = make_app(monkeypatch, tmp_path)
    from src import db
    with db.session() as s:
        row = db.Oshi(name="HANA", aliases_json="[]", hidden=1)
        s.add(row)
        s.flush()
        oshi_id = row.id
        s.commit()
    fake = {"records": [{"source_api": "books_cd", "media": "cd",
                         "item_code": "4900000000001", "title": "ROSE",
                         "author_or_artist": "HANA", "caption": "",
                         "sales_date": "2026年08月10日", "sales_date_iso": "2026-08-10",
                         "sales_date_precision": "day",
                         "item_url": "https://hb.afl.rakuten.co.jp/x",
                         "image_url": "", "price": 1500, "availability": 1,
                         "relevance": 1.0}],
            "failed_apis": []}
    with patch.object(webapp, "search_all", return_value=fake):
        r = client.post("/api/search", json={"name": "HANA"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done" and body["oshi_id"] == oshi_id
    # 非表示が解除され、ページが200で開ける
    assert client.get(f"/oshi/{oshi_id}").status_code == 200


def test_sync_search_hidden_unprofiled_returns_404(monkeypatch, tmp_path):
    """プロファイル未整備の非表示推しは、再クロールせず404を返す（API浪費・誤リダイレクト防止）。"""
    client, webapp = make_app(monkeypatch, tmp_path)
    from src import db
    with db.session() as s:
        row = db.Oshi(name="曖昧太郎", aliases_json="[]", hidden=1)
        s.add(row)
        s.commit()
    called = MagicMock()
    with patch.object(webapp, "search_all", side_effect=called):
        r = client.post("/api/search", json={"name": "曖昧太郎"})
    assert r.status_code == 404
    called.assert_not_called()


def test_unavailable_items_are_hidden_and_dates_emphasized(monkeypatch, tmp_path):
    """購入不可（在庫コード1〜6以外）は非表示、在庫不明(NULL)は表示。発売前は強調表示。"""
    import datetime as dt
    client, webapp = make_app(monkeypatch, tmp_path)
    from src import db
    future = (dt.date.today() + dt.timedelta(days=30)).isoformat()
    with db.session() as s:
        o = db.Oshi(name="作家X", aliases_json="[]")
        s.add(o)
        s.flush()
        oid = o.id
        common = dict(oshi_id=oid, source_api="books_book",
                      sales_date_precision="day")
        s.add(db.Item(item_code="a1", title="買える予約商品",
                      item_url="https://hb.afl.rakuten.co.jp/a",
                      sales_date="発売前テスト日", sales_date_iso=future,
                      availability=5, **common))
        s.add(db.Item(item_code="a2", title="入手不可の本",
                      item_url="https://hb.afl.rakuten.co.jp/b",
                      sales_date="2020年01月10日", sales_date_iso="2020-01-10",
                      availability=11, **common))
        s.add(db.Item(item_code="a3", title="在庫状態不明の本",
                      item_url="https://hb.afl.rakuten.co.jp/c",
                      sales_date="2021年01月10日", sales_date_iso="2021-01-10",
                      **common))
        s.commit()
    r = client.get(f"/oshi/{oid}")
    assert r.status_code == 200
    assert "買える予約商品" in r.text
    assert "在庫状態不明の本" in r.text
    assert "入手不可の本" not in r.text
    assert 'class="date upcoming"' in r.text  # 発売前の強調
    assert "発売前" in r.text


def test_save_results_persists_availability(monkeypatch, tmp_path):
    client, webapp = make_app(monkeypatch, tmp_path)
    from src import db
    from src.search_service import find_or_create_oshi, save_results
    oid, _ = find_or_create_oshi("作家Y")
    save_results(oid, [{"source_api": "books_book", "media": "book",
                        "item_code": "b1", "title": "本", "author_or_artist": "作家Y",
                        "caption": "", "sales_date": "2026年08月10日",
                        "sales_date_iso": "2026-08-10", "sales_date_precision": "day",
                        "item_url": "https://hb.afl.rakuten.co.jp/x", "image_url": "",
                        "price": 1000, "availability": 5, "relevance": 1.0}])
    with db.session() as s:
        row = s.query(db.Item).filter(db.Item.item_code == "b1").one()
        assert row.availability == 5
