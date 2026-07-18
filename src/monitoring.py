"""日次ジョブの永続実行履歴とヘルススナップショット。"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from collections.abc import Callable

from . import config, db

logger = logging.getLogger(__name__)


def _iso(value: dt.datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_result(value: dict) -> dict:
    """JSONに保存できるプリミティブだけを正規化する。"""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def run_job(job_name: str, operation: Callable[[], dict], request_id: str = "") -> dict:
    """ジョブを実行し、成功・失敗をDBと構造化ログの両方に残す。"""
    started_at = db.utcnow()
    started_monotonic = time.monotonic()
    with db.session() as s:
        row = db.JobRun(job_name=job_name, started_at=started_at, status="running")
        s.add(row)
        s.commit()
        run_id = row.id

    logger.info(json.dumps({
        "level": "info", "message": "cron_started", "job": job_name,
        "job_run_id": run_id, "request_id": request_id,
    }, ensure_ascii=False))

    try:
        result = _safe_result(operation())
    except Exception as exc:
        finished_at = db.utcnow()
        duration_ms = round((time.monotonic() - started_monotonic) * 1000)
        with db.session() as s:
            row = s.get(db.JobRun, run_id)
            if row is not None:
                row.status = "error"
                row.finished_at = finished_at
                row.error = str(exc)[:2000]
                s.commit()
        logger.exception(json.dumps({
            "level": "error", "message": "cron_failed", "job": job_name,
            "job_run_id": run_id, "request_id": request_id,
            "duration_ms": duration_ms, "error": str(exc),
        }, ensure_ascii=False))
        raise

    finished_at = db.utcnow()
    duration_ms = round((time.monotonic() - started_monotonic) * 1000)
    with db.session() as s:
        row = s.get(db.JobRun, run_id)
        if row is not None:
            row.status = "success"
            row.finished_at = finished_at
            row.result_json = json.dumps(result, ensure_ascii=False)
            s.commit()
    logger.info(json.dumps({
        "level": "info", "message": "cron_completed", "job": job_name,
        "job_run_id": run_id, "request_id": request_id,
        "duration_ms": duration_ms, "result": result,
    }, ensure_ascii=False))
    return {
        **result,
        "job_run_id": run_id,
        "started_at": _iso(started_at),
        "finished_at": _iso(finished_at),
    }


def _job_health(s, job_name: str, now: dt.datetime) -> dict:
    latest = s.query(db.JobRun).filter(db.JobRun.job_name == job_name) \
        .order_by(db.JobRun.started_at.desc()).first()
    success = s.query(db.JobRun).filter(
        db.JobRun.job_name == job_name,
        db.JobRun.status == "success",
    ).order_by(db.JobRun.finished_at.desc()).first()

    if success is None:
        return {
            "status": "initializing",
            "last_run_status": latest.status if latest else None,
            "last_started_at": _iso(latest.started_at) if latest else None,
            "last_success_at": None,
            "success_age_hours": None,
        }

    completed_at = success.finished_at or success.started_at
    age_hours = max(0.0, (now - completed_at).total_seconds() / 3600)
    failed_after_success = bool(
        latest and latest.status == "error" and latest.started_at > completed_at
    )
    stuck_running = bool(
        latest and latest.status == "running"
        and now - latest.started_at > dt.timedelta(minutes=config.CRON_JOB_STUCK_MINUTES)
    )
    status = "degraded" if (
        age_hours > config.CRON_HEALTH_MAX_AGE_HOURS
        or failed_after_success
        or stuck_running
    ) else "healthy"
    try:
        result = json.loads(success.result_json or "{}")
    except ValueError:
        result = {}
    return {
        "status": status,
        "last_run_status": latest.status if latest else None,
        "last_started_at": _iso(latest.started_at) if latest else None,
        "last_success_at": _iso(completed_at),
        "success_age_hours": round(age_hours, 2),
        "last_result": result,
    }


def health_snapshot(now: dt.datetime | None = None) -> dict:
    """商品表示とは独立した、DB・Cron・巡回キューの状態を返す。"""
    now = now or db.utcnow()
    with db.session() as s:
        jobs = {
            "crawl": _job_health(s, "crawl", now),
            "retention": _job_health(s, "retention", now),
        }
        due = s.query(db.CrawlQueue).join(
            db.Oshi, db.Oshi.id == db.CrawlQueue.oshi_id
        ).filter(
            db.Oshi.hidden == 0,
            db.CrawlQueue.next_crawl_at <= now,
        )
        due_count = due.count()
        oldest = due.order_by(db.CrawlQueue.next_crawl_at.asc()).first()
        oldest_due_at = oldest.next_crawl_at if oldest else None
        overdue_hours = (
            max(0.0, (now - oldest_due_at).total_seconds() / 3600)
            if oldest_due_at else 0.0
        )

    states = [value["status"] for value in jobs.values()]
    if "degraded" in states or overdue_hours > config.CRON_HEALTH_MAX_AGE_HOURS:
        status = "degraded"
    elif "initializing" in states:
        status = "initializing"
    else:
        status = "healthy"
    return {
        "status": status,
        "checked_at": _iso(now),
        "database": {"status": "healthy"},
        "jobs": jobs,
        "crawl_queue": {
            "status": "degraded" if overdue_hours > config.CRON_HEALTH_MAX_AGE_HOURS else "healthy",
            "due_count": due_count,
            "oldest_due_at": _iso(oldest_due_at),
            "oldest_overdue_hours": round(overdue_hours, 2),
        },
        "thresholds": {
            "cron_success_max_age_hours": config.CRON_HEALTH_MAX_AGE_HOURS,
            "cron_running_max_age_minutes": config.CRON_JOB_STUCK_MINUTES,
            "queue_overdue_max_age_hours": config.CRON_HEALTH_MAX_AGE_HOURS,
        },
    }
