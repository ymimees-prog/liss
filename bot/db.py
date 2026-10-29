"""SQLite storage. Dates are stored as ISO strings in the user's local timezone."""
import sqlite3
from datetime import date, timedelta

from .logic import next_review

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id       INTEGER PRIMARY KEY,
    name          TEXT,
    start_date    TEXT NOT NULL,
    tz            TEXT NOT NULL,
    morning_time  TEXT NOT NULL DEFAULT '07:30',
    evening_time  TEXT NOT NULL DEFAULT '21:30',
    goal_name     TEXT,
    goal_amount   REAL
);
CREATE TABLE IF NOT EXISTS topics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    area          TEXT NOT NULL,              -- 'college' | 'it'
    subject       TEXT NOT NULL,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'todo', -- 'todo' | 'review' | 'mastered'
    created_on    TEXT NOT NULL,
    learned_on    TEXT,
    review_stage  INTEGER NOT NULL DEFAULT 0,
    next_review   TEXT,
    reviews_done  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS attendance (
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    status   TEXT NOT NULL,                   -- 'present' | 'late' | 'absent' | 'excused'
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS it_sessions (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    skill    TEXT NOT NULL,
    minutes  INTEGER NOT NULL,
    note     TEXT
);
CREATE TABLE IF NOT EXISTS days (
    user_id    INTEGER NOT NULL,
    day        TEXT NOT NULL,
    wake_time  TEXT,
    mood       INTEGER,
    emotions   TEXT,
    note       TEXT,
    PRIMARY KEY (user_id, day)
);
CREATE TABLE IF NOT EXISTS meals (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    day      TEXT NOT NULL,
    kind     TEXT NOT NULL,
    text     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    day       TEXT NOT NULL,
    kind      TEXT NOT NULL,                  -- 'income' | 'expense' | 'saving'
    amount    REAL NOT NULL,                  -- 'saving' may be negative (taken from savings)
    category  TEXT,
    note      TEXT
);
CREATE TABLE IF NOT EXISTS reminders_sent (
    user_id  INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    day      TEXT NOT NULL,
    PRIMARY KEY (user_id, kind, day)
);
CREATE INDEX IF NOT EXISTS idx_topics_user ON topics(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tx_user_day ON transactions(user_id, day);
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

    def create_user(self, user_id: int, name: str, start: date, tz: str) -> None:
        self._exec(
            "INSERT OR IGNORE INTO users (user_id, name, start_date, tz) VALUES (?, ?, ?, ?)",
            (user_id, name, start.isoformat(), tz),
        )

    def update_user(self, user_id: int, **fields) -> None:
        allowed = {"name", "start_date", "tz", "morning_time", "evening_time", "goal_name", "goal_amount"}
        assert fields.keys() <= allowed, fields.keys() - allowed
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE users SET {cols} WHERE user_id = ?", (*fields.values(), user_id))

    def claim_reminder(self, user_id: int, kind: str, day: date) -> bool:
        """Marks a reminder as sent; False if it was already sent that day."""
        cur = self._exec("INSERT OR IGNORE INTO reminders_sent (user_id, kind, day) VALUES (?, ?, ?)",
                         (user_id, kind, day.isoformat()))
        return cur.rowcount == 1

    # ---------- topics ----------
    def add_topic(self, user_id: int, area: str, subject: str, title: str, today: date) -> int:
        cur = self._exec(
            "INSERT INTO topics (user_id, area, subject, title, created_on) VALUES (?, ?, ?, ?, ?)",
            (user_id, area, subject, title, today.isoformat()),
        )
        return cur.lastrowid

    def get_topic(self, user_id: int, topic_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM topics WHERE user_id = ? AND id = ?", (user_id, topic_id))

    def topics(self, user_id: int, area: str, status: str) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM topics WHERE user_id = ? AND area = ? AND status = ? ORDER BY id",
            (user_id, area, status),
        )

    def topic_counts(self, user_id: int, area: str | None = None) -> dict[str, int]:
        sql = "SELECT status, COUNT(*) c FROM topics WHERE user_id = ?"
        params: tuple = (user_id,)
        if area:
            sql += " AND area = ?"
            params += (area,)
        rows = self._all(sql + " GROUP BY status", params)
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

    # ---------- attendance ----------
    def set_attendance(self, user_id: int, day: date, status: str) -> None:
        self._exec(
            "INSERT INTO attendance (user_id, day, status) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, day) DO UPDATE SET status = excluded.status",
            (user_id, day.isoformat(), status),
        )

    def get_attendance(self, user_id: int, day: date) -> str | None:
        row = self._one("SELECT status FROM attendance WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))
        return row["status"] if row else None

    def attendance_stats(self, user_id: int, since: date, until: date) -> dict[str, int]:
        rows = self._all(
            "SELECT status, COUNT(*) c FROM attendance WHERE user_id = ? AND day BETWEEN ? AND ? GROUP BY status",
            (user_id, since.isoformat(), until.isoformat()),
        )
        stats = {"present": 0, "late": 0, "absent": 0, "excused": 0}
        stats.update({r["status"]: r["c"] for r in rows})
        return stats

    # ---------- IT sessions ----------
    def add_session(self, user_id: int, day: date, skill: str, minutes: int, note: str | None) -> None:
        self._exec(
            "INSERT INTO it_sessions (user_id, day, skill, minutes, note) VALUES (?, ?, ?, ?, ?)",
            (user_id, day.isoformat(), skill, minutes, note),
        )

    def minutes_by_skill(self, user_id: int, since: date, until: date) -> dict[str, int]:
        rows = self._all(
            "SELECT skill, SUM(minutes) m FROM it_sessions WHERE user_id = ? AND day BETWEEN ? AND ? "
            "GROUP BY skill ORDER BY m DESC",
            (user_id, since.isoformat(), until.isoformat()),
        )
        return {r["skill"]: r["m"] for r in rows}

    def study_days(self, user_id: int) -> set[str]:
        return {r["day"] for r in self._all("SELECT DISTINCT day FROM it_sessions WHERE user_id = ?", (user_id,))}

    # ---------- diary ----------
    def _ensure_day(self, user_id: int, day: date) -> None:
        self._exec("INSERT OR IGNORE INTO days (user_id, day) VALUES (?, ?)", (user_id, day.isoformat()))

    def set_day(self, user_id: int, day: date, **fields) -> None:
        assert fields.keys() <= {"wake_time", "mood", "emotions", "note"}
        self._ensure_day(user_id, day)
        cols = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE days SET {cols} WHERE user_id = ? AND day = ?", (*fields.values(), user_id, day.isoformat()))

    def get_day(self, user_id: int, day: date) -> sqlite3.Row | None:
        return self._one("SELECT * FROM days WHERE user_id = ? AND day = ?", (user_id, day.isoformat()))

    def days_between(self, user_id: int, since: date, until: date) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM days WHERE user_id = ? AND day BETWEEN ? AND ? ORDER BY day",
            (user_id, since.isoformat(), until.isoformat()),
        )

    def add_meal(self, user_id: int, day: date, kind: str, text: str) -> None:
        self._exec("INSERT INTO meals (user_id, day, kind, text) VALUES (?, ?, ?, ?)", (user_id, day.isoformat(), kind, text))

    def meals(self, user_id: int, day: date) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM meals WHERE user_id = ? AND day = ? ORDER BY id", (user_id, day.isoformat()))

    def logged_days(self, user_id: int) -> set[str]:
        """Days where the diary was filled (mood set) — used for the streak."""
        return {r["day"] for r in self._all("SELECT day FROM days WHERE user_id = ? AND mood IS NOT NULL", (user_id,))}

    # ---------- finance ----------
    def add_tx(self, user_id: int, day: date, kind: str, amount: float, category: str | None, note: str | None) -> None:
        self._exec(
            "INSERT INTO transactions (user_id, day, kind, amount, category, note) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, day.isoformat(), kind, amount, category, note),
        )

    def last_tx(self, user_id: int, limit: int = 10) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))

    def delete_tx(self, user_id: int, tx_id: int) -> None:
        self._exec("DELETE FROM transactions WHERE user_id = ? AND id = ?", (user_id, tx_id))

    def tx_total(self, user_id: int, kind: str, since: date | None = None, until: date | None = None) -> float:
        sql = "SELECT COALESCE(SUM(amount), 0) s FROM transactions WHERE user_id = ? AND kind = ?"
        params: tuple = (user_id, kind)
        if since and until:
            sql += " AND day BETWEEN ? AND ?"
            params += (since.isoformat(), until.isoformat())
        return self._one(sql, params)["s"]

    def expenses_by_category(self, user_id: int, since: date, until: date) -> dict[str, float]:
        rows = self._all(
            "SELECT category, SUM(amount) s FROM transactions WHERE user_id = ? AND kind = 'expense' "
            "AND day BETWEEN ? AND ? GROUP BY category ORDER BY s DESC",
            (user_id, since.isoformat(), until.isoformat()),
        )
        return {r["category"]: r["s"] for r in rows}

    def finance_days(self, user_id: int) -> set[str]:
        return {r["day"] for r in self._all("SELECT DISTINCT day FROM transactions WHERE user_id = ?", (user_id,))}


def streak(days: set[str], today: date) -> int:
    """Consecutive days ending today (or yesterday, if today isn't logged yet)."""
    d = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n
