"""螳壽悄蟾｡蝗橸ｼ按ｧ7・・ 逋ｻ骭ｲ謗ｨ縺励・譁ｰ蝠・刀讀懃衍縲３4: 蜈ｨ謗ｨ縺・譌･莉･蜀・峩譁ｰ繧貞宍螳医・

cron諠ｳ螳・ 譌･谺｡螳溯｡後・蝗槭・螳溯｡後〒CRAWL_DAILY_REQUEST_BUDGET繧定ｶ・∴縺ｪ縺・ｯ・峇縺ｧ
next_crawl_at縺悟商縺・・↓蜃ｦ逅・☆繧九・
"""
from __future__ import annotations

import datetime as dt
import logging

from . import config, db
from .rakuten_client import RakutenClient
from .search_service import requests_per_oshi, save_results, search_all

logger = logging.getLogger(__name__)


def capacity_estimate() -> int:
    """7譌･蜻ｨ譛溘〒謐後￠繧区耳縺玲焚縺ｮ讎らｮ励・""
    return config.CRAWL_DAILY_REQUEST_BUDGET * config.CRAWL_PERIOD_DAYS // requests_per_oshi(config.ALIAS_MAX)


def _next_period_days(oshi_id: int, s) -> int:
    """逶ｴ霑代↓逋ｺ螢ｲ莠亥ｮ壹′縺ゅｋ謗ｨ縺励・3譌･蜻ｨ譛溘√◎繧御ｻ･螟悶・7譌･蜻ｨ譛滂ｼ井ｸ企剞7譌･蜴ｳ螳茨ｼ峨・""
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
                    logger.warning("螳ｹ驥剰ｶ・℃縺ｮ縺溘ａ陦ｨ遉ｺ蛛懈ｭ｢: oshi_id=%d name=%s (capacity=%d)",
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
                # 髱櫁｡ｨ遉ｺ縺ｮ謗ｨ縺励・縲∬ｪ､讀懃ｴ｢縺ｮ髫秘屬繧・ｮｹ驥剰ｪｿ謨ｴ縺ｮ蟇ｾ雎｡縲・PI譫繧呈ｶ郁ｲｻ縺帙★縲・                # 蜀崎｡ｨ遉ｺ縺輔ｌ繧九∪縺ｧ繧ｭ繝･繝ｼ繧貞ｯ昴°縺帙ｋ・亥・陦ｨ遉ｺ譎ゅ・邂｡逅・PI縺悟叉譎ょ・髢九☆繧具ｼ峨・                q.next_crawl_at = now + dt.timedelta(days=config.CRAWL_PERIOD_DAYS)
                s.commit()
                continue
            cost = requests_per_oshi(len(oshi.aliases))
            if used + cost > budget:
                logger.info("譛ｬ譌･縺ｮ莠育ｮ嶺ｸ企剞縺ｫ蛻ｰ驕・used=%d", used)
                break
            result = search_all(oshi.name, oshi.aliases, client=client)
            used += cost
            crawled += 1
            if len(result["failed_apis"]) >= 8:  # 蜈ｨ貊・凾縺ｮ縺ｿ螟ｱ謨玲桶縺・ｼ按ｧ12・・
                q.fail_count += 1
                q.next_crawl_at = now + dt.timedelta(hours=6 * min(q.fail_count, 4))
                logger.error("蟾｡蝗槫・貊・ oshi=%s fail_count=%d", oshi.name, q.fail_count)
            else:
                new_items = save_results(oshi.id, result["records"])
                new_items_total += new_items
                q.fail_count = 0
                q.last_crawl_at = db.utcnow()
                q.next_crawl_at = db.utcnow() + dt.timedelta(days=_next_period_days(oshi.id, s))
                if new_items:
                    logger.info("譁ｰ逹 %d莉ｶ: %s", new_items, oshi.name)
            s.commit()

    return {"crawled": crawled, "requests_used": used, "new_items": new_items_total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    stats = run_once()
    logger.info("crawler done: %s", stats)

