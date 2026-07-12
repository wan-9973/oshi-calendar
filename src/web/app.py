"""FastAPI Web螻､・按ｧ8・峨・

- 繝ｭ繧ｰ繧､繝ｳ荳崎ｦ√・蜈ｬ髢妓eb繧｢繝励Μ・・8・峨ょ倶ｺｺ蛹悶・繝悶Λ繧ｦ繧ｶlocalStorage縺ｮ縺ｿ縲・
- 蝠・刀繝ｪ繝ｳ繧ｯ縺ｯ讌ｽ螟ｩ縺ｮ縺ｿ・・6・峨ょ､夜Κ繝ｪ繝ｳ繧ｯ縺ｯ鄂ｮ縺九↑縺・ｼ郁ｦ冗ｴ・譚｡4鬆・ｼ峨・
- 譁ｰ隕乗耳縺玲､懃ｴ｢縺ｯ髱槫酔譛溘ず繝ｧ繝・繝昴・繝ｪ繝ｳ繧ｰ縺ｧ谿ｵ髫手｡ｨ遉ｺ・按ｧ8.4・峨・
- 蜷御ｸIP縺ｮ譁ｰ隕乗､懃ｴ｢縺ｯ1蛻・莉ｶ縺ｫ蛻ｶ髯撰ｼ按ｧ8.4・峨・
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
from ..calendar_service import month_calendar, upcoming
from ..crawler import run_once as crawl_run_once
from ..retention import run_once as retention_run_once
from ..search_service import find_or_create_oshi, save_results, search_all

# Vercel遲峨・繧ｵ繝ｼ繝舌・繝ｬ繧ｹ縺ｧ縺ｯ繝ｬ繧ｹ繝昴Φ繧ｹ蠕後↓繧ｹ繝ｬ繝・ラ縺檎函蟄倥＠縺ｪ縺・◆繧∝酔譛滓､懃ｴ｢縺ｫ蛻・ｊ譖ｿ縺医ｋ
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

MEDIA_TABS = [("book", "譖ｸ邀・), ("cd", "CD"), ("dvd", "譏蜒・), ("magazine", "髮題ｪ・),
              ("game", "繧ｲ繝ｼ繝"), ("ebook", "髮ｻ蟄・), ("goods", "繧ｰ繝・ぜ"), ("mixed", "縺昴・莉・)]
MEDIA_LABEL = dict(MEDIA_TABS)

# --- 讀懃ｴ｢繧ｸ繝ｧ繝厄ｼ医う繝ｳ繝｡繝｢繝ｪ・・-------------------------------------------------
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
        result = search_all(name, progress=progress)
        oshi_id, _ = find_or_create_oshi(name)
        save_results(oshi_id, result["records"])
        with _jobs_lock:
            _jobs[job_id].update(status="done", oshi_id=oshi_id,
                                 failed_apis=result["failed_apis"])
    except Exception as exc:  # noqa: BLE001 - 繧ｸ繝ｧ繝悶・關ｽ縺ｨ縺輔★螟ｱ謨励ｒ險倬鹸
        with _jobs_lock:
            _jobs[job_id].update(status="error", message=str(exc))


# --- 陦ｨ遉ｺ逕ｨ繝倥Ν繝・-------------------------------------------------------------
def _card(item: db.Item, price_row: db.PriceCache | None) -> dict:
    """蝠・刀繧ｫ繝ｼ繝牙ｿ・郁ｦ∫ｴ・按ｧ8.2・・ 逕ｻ蜒・繧ｿ繧､繝医Ν/蟐剃ｽ・逋ｺ螢ｲ譌･/萓｡譬ｼ(24h蜀・/讌ｽ螟ｩ繝ｪ繝ｳ繧ｯ/蜿門ｾ玲律譎・""
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
        "price": price,  # None縺ｪ繧峨梧怙譁ｰ萓｡譬ｼ縺ｯ讌ｽ螟ｩ縺ｧ縺皮｢ｺ隱阪￥縺縺輔＞縲・
        "url": item.item_url,   # 讌ｽ螟ｩ繝峨Γ繧､繝ｳ縺ｮ縺ｿ・・6・・
        "image": item.image_url,
        "fetched_at": item.meta_fetched_at.strftime("%Y-%m-%d %H:%M") + " UTC",
        "is_new": (db.utcnow() - item.first_seen_at) <= dt.timedelta(days=7),
    }


def _cards_for(s, items: list[db.Item]) -> list[dict]:
    codes = [i.item_code for i in items]
    prices = {p.item_code: p for p in
              s.query(db.PriceCache).filter(db.PriceCache.item_code.in_(codes)).all()} if codes else {}
    return [_card(i, prices.get(i.item_code)) for i in items]


# --- 繝壹・繧ｸ -------------------------------------------------------------------
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
    """URL繧堤衍縺｣縺ｦ縺・ｌ縺ｰ隱ｰ縺ｧ繧る幕縺代ｋ蜈ｬ髢九・繝ｼ繧ｸ縲ゆｸｭ霄ｫ縺ｯ繝悶Λ繧ｦ繧ｶ縺ｮlocalStorage萓晏ｭ假ｼ・8・峨・""
    return templates.TemplateResponse(request, "my.html", {})


# --- API ----------------------------------------------------------------------
@app.post("/api/search")
def api_search(request: Request, payload: dict):
    name = (payload.get("name") or "").strip()
    if not name or len(name) > 100:
        raise HTTPException(400, "謗ｨ縺怜錐繧貞・蜉帙＠縺ｦ縺上□縺輔＞")
    with db.session() as s:
        row = s.query(db.Oshi).filter(db.Oshi.name == name).one_or_none()
        if row and not row.hidden:  # 譌｢遏･縺ｮ謗ｨ縺励・繧ｭ繝｣繝・す繝･縺九ｉ蜊ｳ譎り｡ｨ遉ｺ・按ｧ8.4・・
            row.last_searched_at = db.utcnow()
            s.commit()
            return {"status": "cached", "oshi_id": row.id}
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(429, "讀懃ｴ｢縺梧ｷｷ縺ｿ蜷医▲縺ｦ縺・∪縺吶・蛻・⊇縺ｩ蠕・▲縺ｦ縺九ｉ縺願ｩｦ縺励￥縺縺輔＞縲・)
    if SERVERLESS:  # 蜷梧悄螳溯｡鯉ｼ・繝ｪ繧ｯ繧ｨ繧ｹ繝暗・.2遘停薗10遘偵ＮaxDuration蜀・ｼ・
        result = search_all(name)
        if len(result["failed_apis"]) >= 8:
            raise HTTPException(503, "荳譎ら噪縺ｫ蜿門ｾ励〒縺阪∪縺帙ｓ")
        oshi_id, _ = find_or_create_oshi(name)
        save_results(oshi_id, result["records"])
        return {"status": "done", "oshi_id": oshi_id}
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "message": "讀懃ｴ｢繧帝幕蟋九＠縺ｦ縺・∪縺・,
                         "step": 0, "total": 8, "created": time.monotonic()}
        # 蜿､縺・ず繝ｧ繝悶ｒ謗・勁
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
    """繝槭う繝壹・繧ｸ逕ｨ繧ｵ繝槭Μ・・ocalStorage縺ｮ謗ｨ縺悠D縺九ｉ蜻ｼ縺ｰ繧後ｋ・峨・""
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


# --- Cron・・ercel Cron / GitHub Actions遲峨°繧牙他縺ｳ蜃ｺ縺暦ｼ・-------------------------
def _check_cron(request: Request) -> None:
    if config.CRON_SECRET:
        if request.headers.get("authorization") != f"Bearer {config.CRON_SECRET}":
            raise HTTPException(401)
    elif SERVERLESS:  # 譛ｬ逡ｪ縺ｧ繧ｷ繝ｼ繧ｯ繝ｬ繝・ヨ譛ｪ險ｭ螳壹↑繧牙ｮ牙・蛛ｴ縺ｧ諡貞凄
        raise HTTPException(401, "CRON_SECRET 繧定ｨｭ螳壹＠縺ｦ縺上□縺輔＞")


@app.get("/api/cron/crawl")
def cron_crawl(request: Request):
    """蟾｡蝗槭ｒ蟆丞・縺大ｮ溯｡後・蝗槭≠縺溘ｊ縺ｮ莠育ｮ励・CRAWL_BUDGET_PER_RUN・域里螳・0繝ｪ繧ｯ繧ｨ繧ｹ繝遺薗48遘抵ｼ峨・""
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
        if not hidden:
            queue = s.get(db.CrawlQueue, row.id)
            if queue is not None:
                queue.next_crawl_at = db.utcnow()
        s.commit()
        return {"id": row.id, "name": row.name, "hidden": bool(row.hidden)}

