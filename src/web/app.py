"""FastAPI Web層（§8）。

- ログイン不要の公開Webアプリ（R8）。個人化はブラウザlocalStorageのみ。
- 商品リンクは楽天のみ（R6）。外部リンクは置かない（規約8条4項）。
- 新規推し検索は非同期ジョブ+ポーリングで段階表示（§8.4）。
- 同一IPの新規検索は1分3件に制限（§8.4）。
"""
from __future__ import annotations

import datetime as dt
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config, db
from ..entity_profiles import profile_for
from ..calendar_service import month_calendar, upcoming
from ..crawler import run_once as crawl_run_once
from ..retention import run_once as retention_run_once
from ..search_service import find_or_create_oshi, save_results, search_all

# Vercel等のサーバーレスではレスポンス後にスレッドが生存しないため同期検索に切り替える
SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("OSHI_SYNC_SEARCH"))

app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None)
_here = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(_here / "static")), name="static")
templates = Jinja2Templates(directory=str(_here / "templates"))
templates.env.globals.update(
    site_name=config.SITE_NAME,
    operator_name=config.OPERATOR_NAME,
    credit_snippet=config.CREDIT_SNIPPET,
    disclaimer=config.disclaimer(),
)

MEDIA_TABS = [("book", "書籍"), ("cd", "CD"), ("dvd", "映像"), ("magazine", "雑誌"),
              ("game", "ゲーム"), ("ebook", "電子"), ("goods", "グッズ"), ("mixed", "その他")]
MEDIA_LABEL = dict(MEDIA_TABS)

# --- 検索ジョブ（インメモリ） -------------------------------------------------
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_ip_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    q = _ip_hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= config.NEW_SEARCH_PER_IP_PER_MIN:
        return True
    q.append(now)
    return False


def _run_search_job(job_id: str, name: str) -> None:
    def progress(msg: str, i: int, total: int) -> None:
        with _jobs_lock:
            _jobs[job_id].update(message=msg, step=i, total=total)
    try:
        profile = profile_for(name)
        canonical = profile["canonical_name"] if profile else name
        aliases = profile["aliases"] if profile else []
        anchors = profile["anchors"] if profile else []
        result = search_all(canonical, aliases, anchors, progress=progress)
        oshi_id, _ = find_or_create_oshi(canonical, aliases)
        if profile:
            _activate_profiled_oshi(oshi_id)
        save_results(oshi_id, result["records"])
        with _jobs_lock:
            _jobs[job_id].update(status="done", oshi_id=oshi_id,
                                 failed_apis=result["failed_apis"])
    except Exception as exc:  # noqa: BLE001 - ジョブは落とさず失敗を記録
        with _jobs_lock:
            _jobs[job_id].update(status="error", message=str(exc))


def _activate_profiled_oshi(oshi_id: int) -> None:
    """Replace stale cache before making a shared ambiguous-name profile public."""
    with db.session() as s:
        row = s.get(db.Oshi, oshi_id)
        if row is None:
            return
        s.query(db.Item).filter(db.Item.oshi_id == oshi_id).delete()
        row.hidden = 0
        queue = s.get(db.CrawlQueue, oshi_id)
        if queue is not None:
            queue.next_crawl_at = db.utcnow()
        s.commit()


# --- 表示用ヘルパ -------------------------------------------------------------
def _card(item: db.Item, price_row: db.PriceCache | None) -> dict:
    """商品カード必須要素（§8.2）: 画像/タイトル/媒体/発売日/価格(24h内)/楽天リンク/取得日時"""
    price = None
    if price_row is not None:
        age = db.utcnow() - price_row.fetched_at
        if age <= dt.timedelta(hours=config.PRICE_TTL_HOURS):
            price = price_row.price
    return {
        "title": item.title,
        "media": MEDIA_LABEL.get(item.media, item.media),
        "media_key": item.media,
        "author": item.author_or_artist,
        "sales_date": item.sales_date,
        "sales_date_iso": item.sales_date_iso,
        "sales_date_precision": item.sales_date_precision,
        "price": price,  # Noneなら「最新価格は楽天でご確認ください」
        "url": item.item_url,   # 楽天ドメインのみ（R6）
        "image": item.image_url,
        "fetched_at": item.meta_fetched_at.strftime("%Y-%m-%d %H:%M") + " UTC",
        "is_new": (db.utcnow() - item.first_seen_at) <= dt.timedelta(days=7),
    }


def _cards_for(s, items: list[db.Item]) -> list[dict]:
    codes = [i.item_code for i in items]
    prices = {p.item_code: p for p in
              s.query(db.PriceCache).filter(db.PriceCache.item_code.in_(codes)).all()} if codes else {}
    return [_card(i, prices.get(i.item_code)) for i in items]


# --- ページ -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def top(request: Request):
    with db.session() as s:
        week_ago = db.utcnow() - dt.timedelta(days=7)
        new_rows = s.query(db.Item).join(db.Oshi, db.Oshi.id == db.Item.oshi_id) \
            .filter(db.Item.first_seen_at >= week_ago, db.Oshi.hidden == 0) \
            .order_by(db.Item.first_seen_at.desc()).limit(30).all()
        today = dt.date.today().isoformat()
        horizon = (dt.date.today() + dt.timedelta(days=60)).isoformat()
        up_rows = s.query(db.Item).join(db.Oshi, db.Oshi.id == db.Item.oshi_id) \
            .filter(db.Item.sales_date_iso >= today, db.Item.sales_date_iso <= horizon,
                    db.Oshi.hidden == 0) \
            .order_by(db.Item.sales_date_iso.asc()).limit(60).all()
        return templates.TemplateResponse(request, "index.html", {
            "new_items": _cards_for(s, new_rows),
            "upcoming": _cards_for(s, up_rows),
        })


@app.get("/oshi/{oshi_id}", response_class=HTMLResponse)
def oshi_page(request: Request, oshi_id: int, y: int | None = None, m: int | None = None):
    today = dt.date.today()
    y, m = y or today.year, m or today.month
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        oshi.last_viewed_at = db.utcnow()
        s.commit()
        rows = s.query(db.Item).filter(db.Item.oshi_id == oshi_id) \
                .order_by(db.Item.sales_date_iso.desc()).all()
        cards = _cards_for(s, rows)
        cal = month_calendar(cards, y, m)
        newest = sorted(cards, key=lambda c: c["fetched_at"], reverse=False)
        newest = [c for c in cards if c["is_new"]] + [c for c in cards if not c["is_new"]]
        prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
        next_y, next_m = (y + 1, 1) if m == 12 else (y, m + 1)
        return templates.TemplateResponse(request, "oshi.html", {
            "oshi": {"id": oshi.id, "name": oshi.name},
            "tabs": MEDIA_TABS, "cards": cards, "calendar": cal,
            "year": y, "month": m,
            "prev": {"y": prev_y, "m": prev_m}, "next": {"y": next_y, "m": next_m},
            "newest": newest[:50],
        })


@app.get("/my", response_class=HTMLResponse)
def my_page(request: Request):
    """URLを知っていれば誰でも開ける公開ページ。中身はブラウザのlocalStorage依存（R8）。"""
    return templates.TemplateResponse(request, "my.html", {})


# --- API ----------------------------------------------------------------------
@app.post("/api/search")
def api_search(request: Request, payload: dict):
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise HTTPException(400, "推し名を入力してください")
    with db.session() as s:
        row = s.query(db.Oshi).filter(db.Oshi.name == name).one_or_none()
        if row and not row.hidden:  # 既知の推しはキャッシュから即時表示（§8.4）
            row.last_searched_at = db.utcnow()
            s.commit()
            return {"status": "cached", "oshi_id": row.id}
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "検索が混み合っています。1分ほど待ってからお試しください。")
    if SERVERLESS:  # 同期実行（8リクエスト×1.2秒≒10秒。maxDuration内）
        profile = profile_for(name)
        canonical = profile["canonical_name"] if profile else name
        aliases = profile["aliases"] if profile else []
        anchors = profile["anchors"] if profile else []
        result = search_all(canonical, aliases, anchors)
        if len(result["failed_apis"]) >= 8:
            raise HTTPException(503, "一時的に取得できません")
        oshi_id, _ = find_or_create_oshi(canonical, aliases)
        save_results(oshi_id, result["records"])
        return {"status": "done", "oshi_id": oshi_id}
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "message": "検索を開始しています",
                         "step": 0, "total": 8, "created": time.monotonic()}
        # 古いジョブを掃除
        for k in [k for k, v in _jobs.items() if time.monotonic() - v["created"] > 3600]:
            _jobs.pop(k, None)
    threading.Thread(target=_run_search_job, args=(job_id, name), daemon=True).start()
    return {"status": "started", "job_id": job_id}


@app.get("/api/search/{job_id}")
def api_search_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404)
    return {k: v for k, v in job.items() if k != "created"}


@app.get("/api/oshi/{oshi_id}/summary")
def api_oshi_summary(oshi_id: int):
    """マイページ用サマリ（localStorageの推しIDから呼ばれる）。"""
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        rows = s.query(db.Item).filter(db.Item.oshi_id == oshi_id) \
                .order_by(db.Item.sales_date_iso.desc()).limit(200).all()
        cards = _cards_for(s, rows)
        return JSONResponse({
            "id": oshi.id, "name": oshi.name,
            "upcoming": upcoming(cards, days=60)[:5],
            "new_items": [c for c in cards if c["is_new"]][:5],
        })


@app.get("/search")
def search_redirect(q: str = ""):
    with db.session() as s:
        row = s.query(db.Oshi).filter(db.Oshi.name == q.strip()).one_or_none()
        if row:
            return RedirectResponse(f"/oshi/{row.id}")
    return RedirectResponse(f"/?q={q}")


# --- Cron（Vercel Cron / GitHub Actions等から呼び出し） -------------------------
def _check_cron(request: Request) -> None:
    if config.CRON_SECRET:
        if request.headers.get("authorization") != f"Bearer {config.CRON_SECRET}":
            raise HTTPException(401)
    elif SERVERLESS:  # 本番でシークレット未設定なら安全側で拒否
        raise HTTPException(401, "CRON_SECRET を設定してください")


@app.get("/api/cron/crawl")
def cron_crawl(request: Request):
    """巡回を小分け実行。1回あたりの予算はCRAWL_BUDGET_PER_RUN（既定40リクエスト≒48秒）。"""
    _check_cron(request)
    return crawl_run_once(budget=config.CRAWL_BUDGET_PER_RUN if SERVERLESS else None)


@app.get("/api/cron/retention")
def cron_retention(request: Request):
    _check_cron(request)
    return retention_run_once()

# Authenticated cache maintenance.
@app.get("/api/admin/oshi")
def admin_list_oshi(request: Request):
    _check_cron(request)
    with db.session() as s:
        rows = s.query(db.Oshi).order_by(db.Oshi.id.asc()).all()
        return {
            "oshi": [
                {
                    "id": row.id,
                    "name": row.name,
                    "hidden": bool(row.hidden),
                    "item_count": s.query(db.Item).filter(db.Item.oshi_id == row.id).count(),
                    "new_item_count": s.query(db.Item).filter(
                        db.Item.oshi_id == row.id,
                        db.Item.first_seen_at >= db.utcnow() - dt.timedelta(days=7),
                    ).count(),
                }
                for row in rows
            ]
        }


@app.post("/api/admin/oshi/{oshi_id}/visibility")
def admin_set_oshi_visibility(oshi_id: int, request: Request, payload: dict):
    _check_cron(request)
    hidden = payload.get("hidden")
    if not isinstance(hidden, bool):
        raise HTTPException(400, "hidden must be true or false")
    with db.session() as s:
        row = s.get(db.Oshi, oshi_id)
        if row is None:
            raise HTTPException(404, "oshi not found")
        row.hidden = int(hidden)
        s.commit()
        return {"id": row.id, "name": row.name, "hidden": bool(row.hidden)}
