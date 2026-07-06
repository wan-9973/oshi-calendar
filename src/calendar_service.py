"""発売日パースとカレンダー生成。

salesDate形式（ドキュメント確認済み）: 「YYYY年」「YYYY年MM月」「YYYY年MM月DD日」
未確定の場合「上旬/中旬/下旬」「頃」「以降」等が付加される。
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import re
from collections import defaultdict

_RE = re.compile(r"(\d{4})年(?:\s*(\d{1,2})月)?(?:\s*(\d{1,2})日)?")
_APPROX_DAY = {"上旬": 5, "中旬": 15, "下旬": 25}


def parse_sales_date(raw: str) -> tuple[str, str]:
    """(ISO近似日付 'YYYY-MM-DD', 精度 'day'|'month'|'year'|'') を返す。"""
    if not raw:
        return "", ""
    m = _RE.search(raw)
    if not m:
        return "", ""
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None
    if month is None:
        return f"{year:04d}-12-31", "year"
    if day is None:
        for word, d in _APPROX_DAY.items():
            if word in raw:
                return f"{year:04d}-{month:02d}-{d:02d}", "month"
        last = _cal.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{last:02d}", "month"
    try:
        dt.date(year, month, day)
    except ValueError:
        return f"{year:04d}-{month:02d}-01", "month"
    return f"{year:04d}-{month:02d}-{day:02d}", "day"


def month_calendar(items: list[dict], year: int, month: int) -> dict[int, list[dict]]:
    """発売日ベースの月カレンダー。dayキー→商品リスト。精度dayのみ日枠、他は0キー（月内未確定）。"""
    out: dict[int, list[dict]] = defaultdict(list)
    prefix = f"{year:04d}-{month:02d}"
    for it in items:
        iso = it.get("sales_date_iso") or ""
        if not iso.startswith(prefix):
            continue
        if it.get("sales_date_precision") == "day":
            out[int(iso[8:10])].append(it)
        else:
            out[0].append(it)
    return dict(out)


def upcoming(items: list[dict], days: int = 60, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    end = today + dt.timedelta(days=days)
    res = []
    for it in items:
        iso = it.get("sales_date_iso") or ""
        if not iso:
            continue
        try:
            d = dt.date.fromisoformat(iso)
        except ValueError:
            continue
        if today <= d <= end:
            res.append(it)
    return sorted(res, key=lambda x: x["sales_date_iso"])
