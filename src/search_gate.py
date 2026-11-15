"""Atomic database gates shared by all serverless instances."""
import datetime as dt
import hashlib
import unicodedata

from sqlalchemy.exc import IntegrityError
from . import db


def key_for(kind: str, value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return kind + ":" + hashlib.sha256(value.encode()).hexdigest()


def acquire(key: str, limit: int, seconds: int) -> bool:
    now = db.utcnow()
    with db.session() as s:
        # Cleanup bounds storage for rotating request-window keys.
        s.query(db.SearchGate).filter(db.SearchGate.expires_at < now - dt.timedelta(hours=1)).delete()
        changed = s.query(db.SearchGate).filter(
            db.SearchGate.key == key, db.SearchGate.expires_at <= now
        ).update({"count": 0, "expires_at": now + dt.timedelta(seconds=seconds)})
        if not changed:
            try:
                with s.begin_nested():
                    s.add(db.SearchGate(key=key, count=0, expires_at=now + dt.timedelta(seconds=seconds)))
                    s.flush()
            except IntegrityError:
                pass  # Another instance owns the same window.
        changed = s.query(db.SearchGate).filter(
            db.SearchGate.key == key, db.SearchGate.count < limit
        ).update({"count": db.SearchGate.count + 1})
        s.commit()
        return bool(changed)


def release(key: str) -> None:
    with db.session() as s:
        s.query(db.SearchGate).filter(db.SearchGate.key == key).delete()
        s.commit()
