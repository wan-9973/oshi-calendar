"""アクセス解析（GA4 + Clarity）の出力条件とプライバシーポリシーのテスト。"""
import importlib

import pytest


def make_client(monkeypatch, tmp_path, *, enabled, ga="G-TEST123", clarity="clarity01", contact=""):
    monkeypatch.setenv("OSHI_SYNC_SEARCH", "1")
    monkeypatch.setenv("OSHI_DB_PATH", str(tmp_path / "t.db"))
    from src import config, db
    monkeypatch.setattr(config, "GA_MEASUREMENT_ID", ga)
    monkeypatch.setattr(config, "CLARITY_PROJECT_ID", clarity)
    monkeypatch.setattr(config, "ANALYTICS_ENABLED", enabled)
    monkeypatch.setattr(config, "CONTACT", contact)
    db.get_engine(f"sqlite:///{tmp_path}/t.db")
    import src.web.app as webapp
    importlib.reload(webapp)
    from fastapi.testclient import TestClient
    return TestClient(webapp.app)


@pytest.mark.parametrize("path, page_type", [("/", "home"), ("/my", "my"), ("/privacy", "privacy")])
def test_analytics_script_rendered_in_production(monkeypatch, tmp_path, path, page_type):
    client = make_client(monkeypatch, tmp_path, enabled=True)
    html = client.get(path).text
    assert 'src="/static/analytics.js?v=1"' in html
    assert 'data-ga-measurement-id="G-TEST123"' in html
    assert 'data-clarity-project-id="clarity01"' in html
    assert 'data-analytics-schema-version="1"' in html
    assert f'data-analytics-page-type="{page_type}"' in html


def test_analytics_script_not_rendered_when_disabled(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, enabled=False)
    html = client.get("/").text
    assert "analytics.js" not in html
    assert "G-TEST123" not in html


def test_only_configured_tool_is_passed(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, enabled=True, clarity="")
    html = client.get("/").text
    assert 'data-ga-measurement-id="G-TEST123"' in html
    assert "data-clarity-project-id" not in html


def test_enabled_flag_requires_an_id(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("GA_MEASUREMENT_ID", "")
    monkeypatch.setenv("CLARITY_PROJECT_ID", "")
    monkeypatch.delenv("OSHI_ANALYTICS", raising=False)
    from src import config
    try:
        importlib.reload(config)
        assert config.ANALYTICS_ENABLED is False
        monkeypatch.setenv("GA_MEASUREMENT_ID", "G-X")
        importlib.reload(config)
        assert config.ANALYTICS_ENABLED is True
        monkeypatch.setenv("VERCEL_ENV", "preview")
        importlib.reload(config)
        assert config.ANALYTICS_ENABLED is False
        monkeypatch.setenv("OSHI_ANALYTICS", "1")
        importlib.reload(config)
        assert config.ANALYTICS_ENABLED is True
    finally:
        for key in ("VERCEL_ENV", "GA_MEASUREMENT_ID", "OSHI_ANALYTICS"):
            monkeypatch.delenv(key, raising=False)
        importlib.reload(config)


def test_private_areas_are_masked_for_session_recording(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, enabled=True)
    my_html = client.get("/my").text
    assert my_html.count('data-clarity-mask="True"') == 2
    assert 'id="personalized-section"' in client.get("/").text
    assert 'data-content-section="personalized" data-clarity-mask="True"' in client.get("/").text


def test_privacy_policy_page_and_links(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, enabled=False)
    r = client.get("/privacy")
    assert r.status_code == 200
    for text in ("Google アナリティクス", "Microsoft Clarity", "gaoptout", "localStorage", "外部への情報送信"):
        assert text in r.text
    assert "お問い合わせ" not in r.text  # CONTACT未設定なら非表示
    assert 'href="/privacy"' in client.get("/").text
    assert "/privacy</loc>" in client.get("/sitemap.xml").text


def test_privacy_policy_contact(monkeypatch, tmp_path):
    client = make_client(monkeypatch, tmp_path, enabled=False, contact="info@example.com")
    assert 'href="mailto:info@example.com"' in client.get("/privacy").text
