import time
from unittest.mock import MagicMock

from src import config
from src.rakuten_client import RakutenClient, RateLimiter


def make_resp(status, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload if payload is not None else {}
    r.text = text
    return r


def make_client(responses):
    session = MagicMock()
    session.get.side_effect = responses
    return RakutenClient(session=session, rate_limiter=RateLimiter(0.0)), session


def test_rate_limiter_enforces_interval():
    rl = RateLimiter(0.10)
    t0 = time.monotonic()
    rl.wait(); rl.wait(); rl.wait()
    assert time.monotonic() - t0 >= 0.19  # 2間隔ぶん以上


def test_retry_on_429_then_success(monkeypatch):
    monkeypatch.setattr(config, "BACKOFF_BASE_SEC", 0.0)
    client, session = make_client([make_resp(429), make_resp(200, {"count": 1})])
    assert client.search("books_book", {"author": "x"}) == {"count": 1}
    assert session.get.call_count == 2


def test_400_returns_none_without_retry():
    client, session = make_client([make_resp(400, text="wrong_parameter")])
    assert client.search("books_book", {}) is None
    assert session.get.call_count == 1


def test_404_treated_as_empty():
    client, _ = make_client([make_resp(404)])
    assert client.search("kobo", {"author": "x"})["count"] == 0


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(config, "BACKOFF_BASE_SEC", 0.0)
    client, session = make_client([make_resp(500)] * 10)
    assert client.search("ichiba", {"keyword": "x"}) is None
    assert session.get.call_count == config.MAX_RETRIES


def test_request_includes_credentials(monkeypatch):
    monkeypatch.setattr(config, "RAKUTEN_APP_ID", "app123")
    monkeypatch.setattr(config, "RAKUTEN_ACCESS_KEY", "ak456")
    monkeypatch.setattr(config, "RAKUTEN_AFFILIATE_ID", "aff789")
    client, session = make_client([make_resp(200, {"count": 0})])
    client.search("books_book", {"author": "x"})
    params = session.get.call_args.kwargs["params"]
    assert params["applicationId"] == "app123"
    assert params["accessKey"] == "ak456"
    assert params["affiliateId"] == "aff789"
    assert params["formatVersion"] == 2
