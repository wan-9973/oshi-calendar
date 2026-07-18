"""キャッシュ失効ジョブ（§9）。R2: 価格24h / R3: メタ90d / 90日未使用の推し削除。"""
from __future__ import annotations

import datetime as dt
import logging

from . import config, db

logger = logging.getLogger(__name__)


def run_once(now: dt.datetime | None = None) -> dict:
    now = now or db.utcnow()
    price_deleted = meta_requeued = oshi_deleted = job_runs_deleted = 0

    with db.session() as s:
        # R2: 24時間超の価格キャッシュをDELETE
        cutoff = now - dt.timedelta(hours=config.PRICE_TTL_HOURS)
        price_deleted = s.query(db.PriceCache) \
            .filter(db.PriceCache.fetched_at < cutoff).delete()

        # R3: 90日超のメタデータ → 当該推しを巡回キュー先頭へ（再取得成功時に置換される）
        meta_cutoff = now - dt.timedelta(days=config.META_TTL_DAYS)
        stale_oshi_ids = {r.oshi_id for r in
                          s.query(db.Item.oshi_id)
                           .filter(db.Item.meta_fetched_at < meta_cutoff).distinct()}
        for oid in stale_oshi_ids:
            q = s.get(db.CrawlQueue, oid)
            if q:
                q.next_crawl_at = now - dt.timedelta(days=1)  # キュー先頭
                meta_requeued += 1
        # 巡回不能（失敗が続いた）推しの期限切れitemsは削除
        dead_ids = [q.oshi_id for q in
                    s.query(db.CrawlQueue).filter(db.CrawlQueue.fail_count >= 5)]
        if dead_ids:
            s.query(db.Item).filter(db.Item.oshi_id.in_(dead_ids),
                                    db.Item.meta_fetched_at < meta_cutoff).delete(
                                        synchronize_session=False)

        # 90日以上検索も閲覧もされていない推しはoshiごと削除（キャッシュ最小化）
        unused_cutoff = now - dt.timedelta(days=90)
        unused = s.query(db.Oshi).filter(db.Oshi.last_searched_at < unused_cutoff,
                                         db.Oshi.last_viewed_at < unused_cutoff).all()
        for o in unused:
            s.query(db.Item).filter(db.Item.oshi_id == o.id).delete()
            q = s.get(db.CrawlQueue, o.id)
            if q:
                s.delete(q)
            s.delete(o)
            oshi_deleted += 1

        # Hobbyプランのログ保持期間を補う履歴も、DBを圧迫しないよう期限を設ける。
        job_run_cutoff = now - dt.timedelta(days=config.JOB_RUN_TTL_DAYS)
        job_runs_deleted = s.query(db.JobRun) \
            .filter(db.JobRun.started_at < job_run_cutoff).delete()
        s.commit()

    stats = {"price_deleted": price_deleted, "meta_requeued": meta_requeued,
             "oshi_deleted": oshi_deleted, "job_runs_deleted": job_runs_deleted}
    logger.info("retention done: %s", stats)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
