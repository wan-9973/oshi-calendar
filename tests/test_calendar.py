from src.calendar_service import month_calendar, parse_sales_date, upcoming


def test_parse_full_date():
    assert parse_sales_date("2026年08月15日") == ("2026-08-15", "day")


def test_parse_month_only_defaults_to_month_end():
    assert parse_sales_date("2026年02月") == ("2026-02-28", "month")


def test_parse_joujun_chuujun_gejun():
    assert parse_sales_date("2026年09月上旬") == ("2026-09-05", "month")
    assert parse_sales_date("2026年09月中旬") == ("2026-09-15", "month")
    assert parse_sales_date("2026年09月下旬頃") == ("2026-09-25", "month")


def test_parse_year_only_and_invalid():
    assert parse_sales_date("2027年以降") == ("2027-12-31", "year")
    assert parse_sales_date("") == ("", "")
    assert parse_sales_date("未定") == ("", "")


def test_parse_invalid_day_falls_back():
    assert parse_sales_date("2026年02月30日") == ("2026-02-01", "month")


def test_month_calendar_buckets():
    items = [
        {"sales_date_iso": "2026-08-15", "sales_date_precision": "day", "t": 1},
        {"sales_date_iso": "2026-08-25", "sales_date_precision": "month", "t": 2},
        {"sales_date_iso": "2026-09-01", "sales_date_precision": "day", "t": 3},
    ]
    cal = month_calendar(items, 2026, 8)
    assert [i["t"] for i in cal[15]] == [1]
    assert [i["t"] for i in cal[0]] == [2]
    assert 1 not in cal


def test_upcoming_window():
    import datetime as dt
    today = dt.date(2026, 7, 6)
    items = [
        {"sales_date_iso": "2026-07-10"},
        {"sales_date_iso": "2026-12-01"},
        {"sales_date_iso": "2026-07-01"},
    ]
    got = upcoming(items, days=60, today=today)
    assert [i["sales_date_iso"] for i in got] == ["2026-07-10"]
