"""定期巡回（§7）: 登録推しの新商品検知。R4: 全推し7日以内更新を厳守。

cron想定: 日次実行。1回の実行でCRAWL_DAILY_REQUEST_BUDGETを超えない範囲で
next_crawl_atが古い順に処理する。
"""
from __future__ import annotations

import datetime as dt
import logging

from . import config, db
from .entity_profiles import profile_for
from .rakuten_client import RakutenClient
from .search_service import requests_per_oshi, save_results, search_all

logger = logging.getLogger(__name__)


def capacity_estimate() -> int:
    """7日周期で捌ける推し数の概算。"""
    return config.CRAWL_DAILY_REQUEST_BUDGET * config.CRAWL_PERIOD_DAYS // requests_per_oshi(config.ALIAS_MAX)


def _next_period_days(oshi_id: int, s) -> int:
    """直近に発売予定がある推しは3日周期、それ以外は7日周期（上限7日厳守）。"""
    horizon = (dt.date.today() + dt.timedelta(days=config.HOT_WINDOW_DAYS)).isoformat()
    today = dt.date.today().isoformat()
    hot = s.query(db.Item).filter(
        db.Item.oshi_id == oshi_id,
        db.Item.sales_date_iso >= today,
        db.Item.sales_date_iso <= horizon,
    ).first()
    return config.CRAWL_PERIOD_HOT_DAYS if hot else config.CRAWL_PERIOD_DAYS


def run_once(budget: int | None = None, client: RakutenClient | None = None) -> dict:
    budget = budget or config.CRAWL_DAILY_REQUEST_BUDGET
    client = client or RakutenClient()
    used = 0
    crawled = 0
    new_items_total = 0
    now = db.utcnow()

    with db.session() as s:
        total_oshi = s.query(db.Oshi).count()
        cap = capacity_estimate()
        if total_oshi > cap:
            over = s.query(db.Oshi).order_by(db.Oshi.last_viewed_at.asc()) \
                    .limit(total_oshi - cap).all()
            for o in over:
                if not o.hidden:
                    o.hidden = 1
                    logger.warning("容量超過のため表示停止: oshi_id=%d name=%s (capacity=%d)",
                                   o.id, o.name, cap)
            s.commit()

        due = s.query(db.CrawlQueue).filter(db.CrawlQueue.next_crawl_at <= now) \
               .order_by(db.CrawlQueue.next_crawl_at.asc()).all()
        for q in due:
            oshi = s.get(db.Oshi, q.oshi_id)
            if oshi is None:
                s.delete(q)
                s.commit()
                continue
            if oshi.hidden:
                # Hidden entries do not consume crawl capacity.
                q.next_crawl_at = now + dt.timedelta(days=config.CRAWL_PERIOD_DAYS)
                s.commit()
                continue
            cost = requests_per_oshi(len(oshi.aliases))
            if used + cost > budget:
                logger.info("本日の予算上限に到達 used=%d", used)
                break
            profile = profile_for(oshi.name)  # 曖昧名は巡回でも共有プロファイルで絞り込む
            aliases = profile["aliases"] if profile else oshi.aliases
            anchors = profile["anchors"] if profile else []
            result = search_all(oshi.name, aliases, anchors, client=client)
            used += cost
            crawled += 1
            if len(result["failed_apis"]) >= 8:  # 全滅時のみ失敗扱い（§12）
                q.fail_count += 1
                q.next_crawl_at = now + dt.timedelta(hours=6 * min(q.fail_count, 4))
                logger.error("巡回全滅: oshi=%s fail_count=%d", oshi.name, q.fail_count)
            else:
                new_items = save_results(oshi.id, result["records"])
                new_items_total += new_items
                q.fail_count = 0
                q.last_crawl_at = db.utcnow()
                q.next_crawl_at = db.utcnow() + dt.timedelta(days=_next_period_days(oshi.id, s))
                if new_items:
                    logger.info("新着 %d件: %s", new_items, oshi.name)
            s.commit()

    return {"crawled": crawled, "requests_used": used, "new_items": new_items_total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stats = run_once()
    logger.info("crawler done: %s", stats)
