"""SQLite storage. Dates are stored as ISO strings in the user's local timezone."""
import sqlite3
from datetime import date

from .logic import next_review

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    name         TEXT,
    tz           TEXT NOT NULL,
    digest_time  TEXT NOT NULL DEFAULT '09:00'   -- morning market digest; 'off' disables it
);
CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    subject       TEXT NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'todo', -- 'todo' | 'review' | 'mastered'
    created_on    TEXT NOT NULL,
    learned_on    TEXT,
    review_stage  INTEGER NOT NULL DEFAULT 0,
    next_review   TEXT,
    reviews_done  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    user_id  INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    day      TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, day)
);
CREATE TABLE IF NOT EXISTS price_alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    asset      TEXT NOT NULL,
    direction  TEXT NOT NULL,                 -- 'above' | 'below'
    price      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS portfolio_tx (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    asset    TEXT NOT NULL,
    qty      REAL NOT NULL,                   -- + bought, - sold
    price    REAL NOT NULL                    -- in USD per coin
);
CREATE TABLE IF NOT EXISTS trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    asset      TEXT NOT NULL,
    side       TEXT NOT NULL,                 -- 'long' | 'short'
    demo       INTEGER NOT NULL DEFAULT 1,
    entry      REAL NOT NULL,
    stop       REAL NOT NULL,
    take       REAL,
    qty        REAL NOT NULL,
    reason     TEXT,
    opened_on  TEXT NOT NULL,
    exit       REAL,                          -- NULL while the trade is open
    closed_on  TEXT,
    lesson     TEXT                           -- what the trader learned / felt after closing
);
CREATE INDEX IF NOT EXISTS idx_topics_user ON topics(user_id, status);
CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id, exit);
"""


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    # ---------- users ----------
    def get_user(self, user_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM users WHERE user_id = ?", (user_id,))

    def all_users(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM users")

    def create_user(self, user_id: int, name: str, tz: str) -> bool:
        """Returns True if the user is new."""
        cur = self._exec("INSERT OR IGNORE INTO users (user_id, name, tz) VALUES (?, ?, ?)", (user_id, name, tz))
        return cur.rowcount == 1

    def update_user(self, user_id: int, **fields) -> None:
        allowed = {"name", "tz", "digest_time"}
        assert fields.keys() <= allowed, fields.keys() - allowed
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE users SET {cols} WHERE user_id = ?", (*fields.values(), user_id))

    def claim_reminder(self, user_id: int, kind: str, day: date) -> bool:
        """Marks a reminder as sent; False if it was already sent that day."""
        cur = self._exec("INSERT OR IGNORE INTO reminders_sent (user_id, kind, day) VALUES (?, ?, ?)",
                         (user_id, kind, day.isoformat()))
        return cur.rowcount == 1

    # ---------- learning topics ----------
    def add_topic(self, user_id: int, subject: str, title: str, today: date) -> int:
        cur = self._exec("INSERT INTO topics (user_id, subject, title, created_on) VALUES (?, ?, ?, ?)",
                         (user_id, subject, title, today.isoformat()))
        return cur.lastrowid

    def get_topic(self, user_id: int, topic_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM topics WHERE user_id = ? AND id = ?", (user_id, topic_id))

    def topics(self, user_id: int, status: str) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM topics WHERE user_id = ? AND status = ? ORDER BY id", (user_id, status))

    def topic_counts(self, user_id: int) -> dict[str, int]:
        rows = self._all("SELECT status, COUNT(*) c FROM topics WHERE user_id = ? GROUP BY status", (user_id,))
        counts = {"todo": 0, "review": 0, "mastered": 0}
        counts.update({r["status"]: r["c"] for r in rows})
        return counts

    def mark_learned(self, user_id: int, topic_id: int, today: date) -> None:
        self._exec(
            "UPDATE topics SET status = 'review', learned_on = ?, review_stage = 0, next_review = ? "
            "WHERE user_id = ? AND id = ?",
            (today.isoformat(), next_review(0, today).isoformat(), user_id, topic_id),
        )

    def review_topic(self, user_id: int, topic_id: int, remembered: bool, today: date) -> date | None:
        """Records a review. Returns the next review date, or None if the topic is now mastered."""
        topic = self.get_topic(user_id, topic_id)
        if topic is None:
            return None
        stage = topic["review_stage"] + 1 if remembered else 0
        nxt = next_review(stage, today)
        status = "review" if nxt else "mastered"
        self._exec(
            "UPDATE topics SET review_stage = ?, next_review = ?, status = ?, reviews_done = reviews_done + 1 "
            "WHERE user_id = ? AND id = ?",
            (stage, nxt.isoformat() if nxt else None, status, user_id, topic_id),
        )
        return nxt

    def due_reviews(self, user_id: int, today: date) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM topics WHERE user_id = ? AND status = 'review' AND next_review <= ? "
            "ORDER BY next_review, id",
            (user_id, today.isoformat()),
        )

    def next_todo(self, user_id: int, after_id: int = 0) -> sqlite3.Row | None:
        """Oldest topic to study after `after_id`, wrapping around to the start of the list."""
        sql = "SELECT * FROM topics WHERE user_id = ? AND status = 'todo' AND id > ? ORDER BY id LIMIT 1"
        return self._one(sql, (user_id, after_id)) or self._one(sql, (user_id, 0))

    def delete_topic(self, user_id: int, topic_id: int) -> None:
        self._exec("DELETE FROM topics WHERE user_id = ? AND id = ?", (user_id, topic_id))

    # ---------- price alerts ----------
    def add_alert(self, user_id: int, asset: str, direction: str, price: float) -> None:
        self._exec("INSERT INTO price_alerts (user_id, asset, direction, price) VALUES (?, ?, ?, ?)",
                   (user_id, asset, direction, price))

    def alerts(self, user_id: int | None = None) -> list[sqlite3.Row]:
        if user_id is None:
            return self._all("SELECT * FROM price_alerts ORDER BY id")
        return self._all("SELECT * FROM price_alerts WHERE user_id = ? ORDER BY id", (user_id,))

    def delete_alert(self, user_id: int, alert_id: int) -> None:
        self._exec("DELETE FROM price_alerts WHERE user_id = ? AND id = ?", (user_id, alert_id))

    # ---------- portfolio ----------
    def add_portfolio_tx(self, user_id: int, day: date, asset: str, qty: float, price: float) -> None:
        self._exec("INSERT INTO portfolio_tx (user_id, day, asset, qty, price) VALUES (?, ?, ?, ?, ?)",
                   (user_id, day.isoformat(), asset, qty, price))

    def portfolio_txs(self, user_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM portfolio_tx WHERE user_id = ? ORDER BY id", (user_id,))

    def delete_portfolio_tx(self, user_id: int, tx_id: int) -> None:
        self._exec("DELETE FROM portfolio_tx WHERE user_id = ? AND id = ?", (user_id, tx_id))

    # ---------- trade journal ----------
    def open_trade(self, user_id: int, day: date, asset: str, side: str, demo: bool, entry: float,
                   stop: float, take: float | None, qty: float, reason: str | None) -> int:
        cur = self._exec(
            "INSERT INTO trades (user_id, asset, side, demo, entry, stop, take, qty, reason, opened_on) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, asset, side, int(demo), entry, stop, take, qty, reason, day.isoformat()),
        )
        return cur.lastrowid

    def get_trade(self, user_id: int, trade_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM trades WHERE user_id = ? AND id = ?", (user_id, trade_id))

    def open_trades(self, user_id: int) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM trades WHERE user_id = ? AND exit IS NULL ORDER BY id", (user_id,))

    def closed_trades(self, user_id: int, demo: bool | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM trades WHERE user_id = ? AND exit IS NOT NULL"
        params: tuple = (user_id,)
        if demo is not None:
            sql += " AND demo = ?"
            params += (int(demo),)
        return self._all(sql + " ORDER BY closed_on, id", params)

    def close_trade(self, user_id: int, trade_id: int, exit_price: float, day: date) -> None:
        self._exec("UPDATE trades SET exit = ?, closed_on = ? WHERE user_id = ? AND id = ? AND exit IS NULL",
                   (exit_price, day.isoformat(), user_id, trade_id))

    def set_trade_lesson(self, user_id: int, trade_id: int, lesson: str) -> None:
        self._exec("UPDATE trades SET lesson = ? WHERE user_id = ? AND id = ?", (lesson, user_id, trade_id))

    def delete_trade(self, user_id: int, trade_id: int) -> None:
        self._exec("DELETE FROM trades WHERE user_id = ? AND id = ?", (user_id, trade_id))
