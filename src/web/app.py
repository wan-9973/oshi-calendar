"""FastAPI Web層（§8）。

- ログイン不要の公開Webアプリ（R8）。個人化はブラウザlocalStorageのみ。
- 商品リンクは楽天のみ（R6）。外部リンクは置かない（規約8条4項）。
- 新規推し検索は非同期ジョブ+ポーリングで段階表示（§8.4）。
- 同一IPの新規検索は1分3件に制限（§8.4）。
"""
from __future__ import annotations

import datetime as dt
import os
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from sqlalchemy import or_
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import config, db
from ..entity_profiles import profile_for
from ..calendar_service import month_calendar, upcoming
from ..crawler import run_once as crawl_run_once
from ..monitoring import health_snapshot, run_job
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
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

_VARIATION_MARKERS = (
    "限定", "特典", "初回", "通常", "盤", "版", "セット", "楽天", "先着", "仕様", "ジャケット",
    "DVD", "Blu-ray", "ブルーレイ", "アナログ", "店舗",
)
_BRACKETED = re.compile(r"【([^】]+)】|\[([^\]]+)\]|（([^）]+)）|\(([^)]+)\)|＜([^＞]+)＞")
_VARIATION_SUFFIX = re.compile(
    r"(?:\s*[-／/]\s*)?(?:初回限定盤?|通常盤|完全生産限定盤?|限定版|通常版|特装版|豪華版)\s*$"
)


def _purchasable():
    """購入不可（品切れ・販売終了・入手不可等）の商品を表示から除外する条件。NULL=不明は表示。"""
    return or_(db.Item.availability.is_(None),
               db.Item.availability.in_(config.PURCHASABLE_AVAILABILITY))

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
    card = {
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
        "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else "",
        "oshi_id": item.oshi_id,
        "is_upcoming": bool(item.sales_date_iso) and
                       item.sales_date_iso >= dt.date.today().isoformat(),
        "is_new": (item.sales_date_precision == "day" and
                   (dt.date.today() - dt.timedelta(days=7)).isoformat()
                   <= item.sales_date_iso <= dt.date.today().isoformat()),
    }
    card["variation_key"] = _variation_key(item.title)
    card["sales_month"] = (item.sales_date_iso or "")[:7]
    return card


def _display_author(author: str, oshi_name: str, aliases: list[str]) -> str:
    """推し名と同一人物だと確実に分かる完全一致だけ、見出し表記へ寄せる。"""
    normalized = (author or "").strip().casefold()
    same_person = {oshi_name.strip().casefold(), *(alias.strip().casefold() for alias in aliases)}
    return oshi_name if normalized and normalized in same_person else author


def _cards_for(s, items: list[db.Item], oshi: db.Oshi | None = None) -> list[dict]:
    codes = [i.item_code for i in items]
    prices = {p.item_code: p for p in
              s.query(db.PriceCache).filter(db.PriceCache.item_code.in_(codes)).all()} if codes else {}
    cards = [_card(i, prices.get(i.item_code)) for i in items]
    if oshi is not None:
        for card in cards:
            card["author"] = _display_author(card["author"], oshi.name, oshi.aliases)
            card["oshi_name"] = oshi.name
    return cards


def _variation_key(title: str) -> str:
    """特典・盤違いだけを保守的に除いた、カレンダー内グルーピング用のキー。"""
    def keep_or_remove(match: re.Match) -> str:
        label = next((part for part in match.groups() if part is not None), "")
        return "" if any(marker in label for marker in _VARIATION_MARKERS) else match.group(0)

    normalized = _BRACKETED.sub(keep_or_remove, title)
    normalized = _VARIATION_SUFFIX.sub("", normalized)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def _group_variations(cards: list[dict]) -> list[dict]:
    """正規化タイトルと発売年月が一致する商品だけを、表示順を保ってまとめる。"""
    groups: list[dict] = []
    by_key: dict[tuple[str, str], dict] = {}
    for card in cards:
        title_key = card.get("variation_key") or _variation_key(card["title"])
        month_key = card.get("sales_month") or (card.get("sales_date_iso") or "")[:7]
        key = (title_key, month_key)
        # 「パプリカ」等の完全同名はまとめつつ、極端に短い名称は誤判定を避ける。
        if len(title_key) < 4 or not month_key:
            groups.append({"representative": card, "variations": []})
            continue
        group = by_key.get(key)
        if group is None:
            group = {"representative": card, "variations": []}
            by_key[key] = group
            groups.append(group)
        else:
            group["variations"].append(card)
    return groups


def _month_key(value: str) -> str | None:
    """有効なYYYY-MM日付からYYYY-MMだけを返す。"""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _select_initial_month(date_values: list[str], today: dt.date) -> tuple[int, int, bool]:
    """今月→未来の直近月→過去の直近月の順で初期表示月を決める。"""
    months = sorted({month for value in date_values if (month := _month_key(value))})
    current = f"{today.year:04d}-{today.month:02d}"
    if current in months:
        selected = current
        showing_history = False
    else:
        future = [month for month in months if month > current]
        if future:
            selected = future[0]
            showing_history = False
        else:
            past = [month for month in months if month < current]
            selected = past[-1] if past else current
            showing_history = bool(past)
    year, month = (int(part) for part in selected.split("-"))
    return year, month, showing_history


def _supply_month_neighbors(months: list[str], year: int, month: int) -> tuple[dict | None, dict | None]:
    """空月を飛ばし、商品が存在する直前・直後の月を返す。"""
    current = f"{year:04d}-{month:02d}"
    before = [value for value in months if value < current]
    after = [value for value in months if value > current]

    def payload(value: str | None) -> dict | None:
        if not value:
            return None
        y, m = (int(part) for part in value.split("-"))
        return {"y": y, "m": m}

    return payload(before[-1] if before else None), payload(after[0] if after else None)


def _calendar_days(calendar: dict[int, list[dict]], year: int, month: int) -> list[dict]:
    """テンプレート向けに日付ラベルとバリエーション群を付与する。"""
    days = []
    for day, cards in sorted(calendar.items()):
        if day == 0:
            label = f"{month}月中（日付未確定）"
        else:
            weekday = WEEKDAY_LABELS[dt.date(year, month, day).weekday()]
            label = f"{month}月{day}日（{weekday}）"
        days.append({"day": day, "label": label, "groups": _group_variations(cards)})
    return days


def _next_release(cards: list[dict], year: int, month: int, today: dt.date) -> dict | None:
    """空状態から移動できる、表示月以降かつ未来の直近発売日を返す。"""
    try:
        month_start = dt.date(year, month, 1)
    except ValueError:
        return None
    threshold = max(today, month_start)
    candidates: list[tuple[dt.date, dict]] = []
    for card in cards:
        try:
            release = dt.date.fromisoformat(card.get("sales_date_iso") or "")
        except ValueError:
            continue
        if release >= threshold:
            candidates.append((release, card))
    if not candidates:
        return None
    release, card = min(candidates, key=lambda pair: pair[0])
    return {
        "date": f"{release.year}年{release.month}月{release.day}日",
        "days": (release - today).days,
        "y": release.year,
        "m": release.month,
        "title": card["title"],
    }


# --- ページ -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def top(request: Request):
    with db.session() as s:
        week_ago = (dt.date.today() - dt.timedelta(days=7)).isoformat()
        today = dt.date.today().isoformat()
        new_rows = s.query(db.Item).join(db.Oshi, db.Oshi.id == db.Item.oshi_id) \
            .filter(db.Item.sales_date_precision == "day",
                    db.Item.sales_date_iso >= week_ago,
                    db.Item.sales_date_iso <= today,
                    db.Oshi.hidden == 0, _purchasable()) \
            .order_by(db.Item.sales_date_iso.desc()).limit(30).all()
        horizon = (dt.date.today() + dt.timedelta(days=60)).isoformat()
        up_rows = s.query(db.Item).join(db.Oshi, db.Oshi.id == db.Item.oshi_id) \
            .filter(db.Item.sales_date_iso >= today, db.Item.sales_date_iso <= horizon,
                    db.Oshi.hidden == 0, _purchasable()) \
            .order_by(db.Item.sales_date_iso.asc()).limit(60).all()
        return templates.TemplateResponse(request, "index.html", {
            "new_items": _cards_for(s, new_rows),
            "upcoming": _cards_for(s, up_rows),
        })


@app.get("/oshi/{oshi_id}", response_class=HTMLResponse)
def oshi_page(request: Request, oshi_id: int, y: int | None = None, m: int | None = None):
    today = dt.date.today()
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        oshi.last_viewed_at = db.utcnow()
        s.commit()

        date_values = [value for (value,) in s.query(db.Item.sales_date_iso).filter(
            db.Item.oshi_id == oshi_id, _purchasable(), db.Item.sales_date_iso != ""
        ).all()]
        available_months = sorted({month for value in date_values if (month := _month_key(value))})
        showing_history = False
        if y is None and m is None:
            y, m, showing_history = _select_initial_month(date_values, today)
        elif y is None or m is None or not (1 <= m <= 12 and 1900 <= y <= 2200):
            raise HTTPException(400, "表示月が不正です")

        month_prefix = f"{y:04d}-{m:02d}"
        month_rows = s.query(db.Item).filter(
            db.Item.oshi_id == oshi_id,
            _purchasable(),
            db.Item.sales_date_iso.like(f"{month_prefix}%"),
        ).order_by(db.Item.sales_date_iso.asc(), db.Item.id.asc()).all()
        month_cards = _cards_for(s, month_rows, oshi)
        cal = month_calendar(month_cards, y, m)
        month_cards = [card for day_cards in cal.values() for card in day_cards]
        tab_counts = {
            key: sum(1 for card in month_cards if card["media_key"] == key)
            for key, _ in MEDIA_TABS
        }

        newest_query = s.query(db.Item).filter(db.Item.oshi_id == oshi_id, _purchasable())
        newest_total = newest_query.count()
        newest_rows = newest_query.order_by(
            db.Item.first_seen_at.desc(), db.Item.id.desc()
        ).limit(24).all()
        newest = _cards_for(s, newest_rows, oshi)
        prev_month, next_month = _supply_month_neighbors(available_months, y, m)

        next_row = s.query(db.Item).filter(
            db.Item.oshi_id == oshi_id,
            _purchasable(),
            db.Item.sales_date_iso >= max(today.isoformat(), f"{y:04d}-{m:02d}-01"),
        ).order_by(db.Item.sales_date_iso.asc()).first()
        next_release = _next_release(_cards_for(s, [next_row], oshi) if next_row else [], y, m, today)
        return templates.TemplateResponse(request, "oshi.html", {
            "oshi": {"id": oshi.id, "name": oshi.name},
            "tabs": [
                {"key": key, "label": label, "count": tab_counts[key]}
                for key, label in MEDIA_TABS
            ],
            "calendar": cal,
            "calendar_days": _calendar_days(cal, y, m),
            "calendar_total": len(month_cards),
            "year": y, "month": m,
            "prev": prev_month, "next": next_month,
            "next_release": next_release,
            "showing_history": showing_history,
            "newest_groups": _group_variations(newest),
            "newest_total": newest_total,
            "newest_loaded": len(newest),
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
        if row and row.hidden and profile_for(name) is None:
            # 品質問題で非表示中（検索プロファイル未整備）。APIを浪費せず404を返す。
            raise HTTPException(404, "この推しページは現在調整中です。時間をおいてお試しください。")
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
        if profile:
            _activate_profiled_oshi(oshi_id)  # 非表示解除+旧キャッシュ破棄（非同期経路と同一の再公開処理）
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
def api_oshi_summary(oshi_id: int, limit: int = Query(8, ge=1, le=12)):
    """個人化表示用サマリ。1件の公開推しIDだけを受け取り、リストは受け取らない。"""
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        today = dt.date.today().isoformat()
        base = s.query(db.Item).filter(db.Item.oshi_id == oshi_id, _purchasable())
        future_rows = base.filter(db.Item.sales_date_iso >= today) \
            .order_by(db.Item.sales_date_iso.asc(), db.Item.id.asc()).limit(limit).all()
        recent_rows = base.order_by(db.Item.first_seen_at.desc(), db.Item.id.desc()).limit(limit).all()
        latest_row = base.filter(db.Item.sales_date_iso < today, db.Item.sales_date_iso != "") \
            .order_by(db.Item.sales_date_iso.desc(), db.Item.id.desc()).first()
        date_values = [value for (value,) in s.query(db.Item.sales_date_iso).filter(
            db.Item.oshi_id == oshi_id, _purchasable(), db.Item.sales_date_iso != ""
        ).all()]
        future_cards = _cards_for(s, future_rows, oshi)
        recent_cards = _cards_for(s, recent_rows, oshi)
        latest_cards = _cards_for(s, [latest_row], oshi) if latest_row else []
        return JSONResponse({
            "id": oshi.id, "name": oshi.name,
            "upcoming": future_cards,
            "recent": recent_cards,
            "new_items": recent_cards,  # 旧クライアント互換
            "latest_supply": latest_cards[0] if latest_cards else (recent_cards[0] if recent_cards else None),
            "available_months": sorted({
                month for value in date_values if (month := _month_key(value))
            }),
        })


@app.get("/api/oshi/{oshi_id}/calendar")
def api_oshi_calendar(
    oshi_id: int,
    y: int = Query(..., ge=1900, le=2200),
    m: int = Query(..., ge=1, le=12),
    limit: int = Query(48, ge=1, le=60),
):
    """統合カレンダー用の月別読取API。localStorageの内容は保存・収集しない。"""
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        query = s.query(db.Item).filter(
            db.Item.oshi_id == oshi_id,
            _purchasable(),
            db.Item.sales_date_iso.like(f"{y:04d}-{m:02d}%"),
        )
        total = query.count()
        rows = query.order_by(db.Item.sales_date_iso.asc(), db.Item.id.asc()).limit(limit).all()
        cards = _cards_for(s, rows, oshi)
        return JSONResponse({
            "id": oshi.id,
            "name": oshi.name,
            "year": y,
            "month": m,
            "items": cards,
            "total": total,
            "truncated": total > len(cards),
        })


@app.get("/api/oshi/{oshi_id}/items")
def api_oshi_items(
    oshi_id: int,
    offset: int = Query(0, ge=0, le=10000),
    limit: int = Query(24, ge=1, le=24),
):
    """新着順を24件ずつ取得する読み取り専用API。マイ推しリストは受け取らない。"""
    with db.session() as s:
        oshi = s.get(db.Oshi, oshi_id)
        if oshi is None or oshi.hidden:
            raise HTTPException(404)
        query = s.query(db.Item).filter(db.Item.oshi_id == oshi_id, _purchasable())
        total = query.count()
        rows = query.order_by(db.Item.first_seen_at.desc(), db.Item.id.desc()) \
            .offset(offset).limit(limit).all()
        cards = _cards_for(s, rows, oshi)
        return JSONResponse({
            "items": cards,
            "groups": _group_variations(cards),
            "offset": offset,
            "next_offset": offset + len(cards),
            "total": total,
            "has_more": offset + len(cards) < total,
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
    return run_job(
        "crawl",
        lambda: crawl_run_once(
            budget=config.CRAWL_BUDGET_PER_RUN if SERVERLESS else None
        ),
        request.headers.get("x-vercel-id", ""),
    )


@app.get("/api/cron/retention")
def cron_retention(request: Request):
    _check_cron(request)
    return run_job(
        "retention",
        retention_run_once,
        request.headers.get("x-vercel-id", ""),
    )


@app.get("/api/health")
def api_health():
    """日次監視用。商品カードの取得日時ではなくジョブとキューを判定する。"""
    return health_snapshot()

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
