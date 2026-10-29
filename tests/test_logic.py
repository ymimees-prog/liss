from datetime import date, timedelta

from bot.db import Database
from bot.logic import (build_positions, journal_stats, next_review, num, parse_numbers, parse_time,
                       position_size, reward_risk, stop_is_valid, trade_pnl, trade_risk)

D = date(2026, 11, 1)


def test_parsing_and_format():
    assert parse_numbers("95 000 93000,5 0.01") == [95000.0, 93000.5, 0.01]
    assert parse_numbers("1000 1 95000 93000") == [1000.0, 1.0, 95000.0, 93000.0]
    assert parse_time("9:05") == "09:05" and parse_time("25:00") is None
    assert num(95000) == "95 000" and num(3200.5) == "3 200,5" and num(97.4) == "97,40"
    assert num(0.0052) == "0,0052" and num(2.1) == "2,1"


def test_positions_average_cost():
    pos = build_positions([("BTC", 1, 100), ("BTC", 1, 200), ("BTC", -1, 300)])["BTC"]
    assert pos.qty == 1 and pos.avg_price == 150 and pos.realized == 150


def test_trade_math():
    assert stop_is_valid("long", 100, 90) and not stop_is_valid("short", 100, 90)
    assert trade_risk(100, 90, 2) == 20
    assert trade_pnl("short", 100, 80, 2) == 40
    assert reward_risk(100, 90, 130) == 3
    r = position_size(1000, 1, 95000, 93000)
    assert r["risk"] == 10 and r["qty"] == 0.005 and r["value"] == 475
    s = journal_stats([(20, 10), (-10, 10), (-10, 10), (40, 10)])
    assert s["winrate"] == 50 and s["avg_r"] == 1 and s["profit_factor"] == 3


def test_spaced_repetition():
    db = Database(":memory:")
    tid = db.add_topic(1, "Риск", "Стоп-лосс", D)
    db.mark_learned(1, tid, D)
    assert db.due_reviews(1, D) == []
    day = D + timedelta(days=1)
    assert [t["id"] for t in db.due_reviews(1, day)] == [tid]
    assert db.review_topic(1, tid, True, day) == day + timedelta(days=3)
    assert db.review_topic(1, tid, False, day) == day + timedelta(days=1)
    for _ in range(6):
        nxt = db.review_topic(1, tid, True, day)
    assert nxt is None and db.get_topic(1, tid)["status"] == "mastered"
    assert next_review(0, D) == D + timedelta(days=1)
