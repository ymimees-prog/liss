from datetime import date, timedelta

from bot.db import Database, streak
from bot.logic import (challenge_day, finance_advice, money, next_review, parse_amount, parse_time,
                       progress_bar, wake_mood_insight)

D = date(2026, 11, 1)


def test_challenge_day():
    assert challenge_day(D, D) == 1
    assert challenge_day(D, D + timedelta(days=89)) == 90
    assert challenge_day(D, D - timedelta(days=1)) == 0


def test_parsers():
    assert parse_amount("350 кофе") == (350.0, "кофе")
    assert parse_amount("99,5р такси") == (99.5, "такси")
    assert parse_amount("кофе") is None
    assert parse_amount("0") is None
    assert parse_time("7:05") == "07:05"
    assert parse_time("25:00") is None


def test_formatting():
    assert money(1200) == "1 200 ₽"
    assert money(99.5) == "99,50 ₽"
    assert progress_bar(5, 10, width=4).endswith("50%")
    assert progress_bar(20, 10, width=4) == "▓▓▓▓ 100%"


def test_spaced_repetition_flow():
    db = Database(":memory:")
    tid = db.add_topic(1, "it", "Python", "Циклы", D)
    db.mark_learned(1, tid, D)
    assert db.due_reviews(1, D) == []
    assert [t["id"] for t in db.due_reviews(1, D + timedelta(days=1))] == [tid]

    day = D + timedelta(days=1)
    assert db.review_topic(1, tid, True, day) == day + timedelta(days=3)
    assert db.review_topic(1, tid, False, day) == day + timedelta(days=1)  # forgot -> back to start
    for _ in range(6):
        nxt = db.review_topic(1, tid, True, day)
    assert nxt is None
    assert db.get_topic(1, tid)["status"] == "mastered"
    assert next_review(0, D) == D + timedelta(days=1)


def test_finance_and_streak():
    db = Database(":memory:")
    db.add_tx(1, D, "income", 10000, None, None)
    db.add_tx(1, D, "expense", 4000, "fun", None)
    db.add_tx(1, D, "saving", 1000, None, None)
    db.add_tx(1, D, "saving", -200, None, None)
    assert db.tx_total(1, "saving") == 800
    advice = finance_advice(10000, db.expenses_by_category(1, D, D), 800)
    assert any("желания" in a for a in advice)
    assert any("20%" in a for a in advice)

    days = {(D + timedelta(days=i)).isoformat() for i in range(3)}
    assert streak(days, D + timedelta(days=2)) == 3
    assert streak(days, D + timedelta(days=3)) == 3  # today not logged yet
    assert streak(days, D + timedelta(days=4)) == 0


def test_wake_mood_insight():
    data = [("06:30", 5), ("07:00", 5), ("10:00", 2), ("11:00", 2)]
    assert "раньше" in wake_mood_insight(data)
    assert wake_mood_insight(data[:2]) is None
