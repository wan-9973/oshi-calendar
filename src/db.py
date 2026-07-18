"""スキーマ（§6.3）。個人データは保存しない（R8）。oshiは共有キャッシュで個人と紐付けない。"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import (Column, DateTime, Float, ForeignKey, Integer, String,
                        Text, create_engine, event, inspect, text)
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

Base = declarative_base()


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class Oshi(Base):
    __tablename__ = "oshi"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    aliases_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=utcnow)
    last_searched_at = Column(DateTime, default=utcnow)   # 90日未使用削除の判定用
    last_viewed_at = Column(DateTime, default=utcnow)
    hidden = Column(Integer, default=0)  # 巡回容量超過時の表示停止フラグ

    @property
    def aliases(self) -> list[str]:
        try:
            return json.loads(self.aliases_json or "[]")[: config.ALIAS_MAX]
        except ValueError:
            return []


class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True)
    oshi_id = Column(Integer, ForeignKey("oshi.id", ondelete="CASCADE"), index=True)
    source_api = Column(String, nullable=False)
    item_code = Column(String, nullable=False, index=True)  # ISBN/JAN/itemCode
    title = Column(Text, nullable=False)
    author_or_artist = Column(Text, default="")
    sales_date = Column(String, default="")        # 原文（表示用）
    sales_date_iso = Column(String, default="")    # ソート用 YYYY-MM-DD（近似）
    sales_date_precision = Column(String, default="")  # year/month/day/""
    item_url = Column(Text, nullable=False)        # affiliateUrl（楽天ドメインのみ。R6）
    image_url = Column(Text, default="")
    relevance = Column(Float, default=0.0)
    media = Column(String, default="")             # book/cd/dvd/magazine/game/ebook/goods
    availability = Column(Integer)                 # 在庫状況（NULL=不明。config.PURCHASABLE_AVAILABILITY参照）
    meta_fetched_at = Column(DateTime, default=utcnow)  # R3: 90日
    first_seen_at = Column(DateTime, default=utcnow)    # 新着判定


class PriceCache(Base):
    __tablename__ = "price_cache"
    item_code = Column(String, primary_key=True)
    price = Column(Integer)
    availability = Column(Integer)
    fetched_at = Column(DateTime, default=utcnow)  # R2: 24h


class RateState(Base):
    """R1をインスタンス横断で直列化するための共有状態（Postgres運用時に行ロックで使用）。"""
    __tablename__ = "rate_state"
    id = Column(Integer, primary_key=True)
    last_at = Column(DateTime, default=dt.datetime(1970, 1, 1))


class CrawlQueue(Base):
    __tablename__ = "crawl_queue"
    oshi_id = Column(Integer, ForeignKey("oshi.id", ondelete="CASCADE"), primary_key=True)
    next_crawl_at = Column(DateTime, default=utcnow, index=True)
    last_crawl_at = Column(DateTime)
    fail_count = Column(Integer, default=0)


class JobRun(Base):
    """Cronの成否を商品カードの更新日時と独立して追跡する実行履歴。"""
    __tablename__ = "job_runs"
    id = Column(Integer, primary_key=True)
    job_name = Column(String, nullable=False, index=True)
    started_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    finished_at = Column(DateTime)
    status = Column(String, nullable=False, default="running", index=True)
    result_json = Column(Text, default="{}")
    error = Column(Text, default="")


_engine = None
_Session = None


def _default_url() -> str:
    if config.DATABASE_URL:
        u = config.DATABASE_URL
        # SQLAlchemy 2.0はpostgres://を受けないため補正（Supabaseの古い接続文字列対策）
        if u.startswith("postgres://"):
            u = "postgresql://" + u[len("postgres://"):]
        return u
    return f"sqlite:///{config.DB_PATH}"


def get_engine(url: str | None = None):
    global _engine, _Session
    if _engine is None or url is not None:
        u = url or _default_url()
        if u.startswith("sqlite"):
            _engine = create_engine(u, connect_args={"check_same_thread": False})

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_con, _):
                dbapi_con.execute("PRAGMA foreign_keys=ON")
        else:
            _engine = create_engine(u, pool_pre_ping=True, pool_size=2, max_overflow=3)
        Base.metadata.create_all(_engine)
        _migrate(_engine)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session():
    get_engine()
    return _Session()


def _migrate(engine) -> None:
    """既存DBへの軽量マイグレーション（create_allは既存テーブルに列を追加しないため）。"""
    cols = {c["name"] for c in inspect(engine).get_columns("items")}
    if "availability" not in cols:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE items ADD COLUMN availability INTEGER"))
