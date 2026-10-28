"""Background loop that sends morning and evening reminders in each user's timezone."""
import asyncio
import logging

from aiogram import Bot

from .common import now_for
from .db import Database
from .handlers.main import today_checklist
from .keyboards import main_menu
from .logic import CHALLENGE_DAYS, challenge_day, parse_iso, random_motivation

log = logging.getLogger(__name__)

MILESTONES = {
    1: "🚀 Первый день! Самое сложное — начать, и ты уже это сделала.",
    7: "🎉 Неделя позади! Привычки начинают формироваться.",
    21: "💪 21 день — говорят, именно столько нужно, чтобы привычка закрепилась.",
    30: "🏅 Месяц! Треть пути. Посмотри в 📊 Прогресс, сколько ты уже сделала.",
    45: "⚡ Экватор! Половина челленджа позади.",
    60: "🔥 60 дней! Ты уже не та, что была 2 месяца назад.",
    80: "🏁 Финишная прямая — 10 дней до конца!",
    CHALLENGE_DAYS: "👑 ДЕНЬ 90! Ты сделала это. Ты изменилась. Гордись собой!",
}


def morning_message(db: Database, user) -> str:
    today = now_for(user).date()
    n = challenge_day(parse_iso(user["start_date"]), today)
    due = len(db.due_reviews(user["user_id"], today))
    lines = [f"☀️ <b>Доброе утро! День {n} из {CHALLENGE_DAYS}</b>"]
    if n in MILESTONES:
        lines.append(MILESTONES[n])
    lines.append("\nОтметь подъём в 🌅 Дневник дня → «⏰ Я проснулась».")
    if due:
        lines.append(f"🔁 Сегодня повторить тем: <b>{due}</b> (📚 Учёба → Повторить сегодня)")
    lines.append(f"\n💬 <i>{random_motivation()}</i>")
    return "\n".join(lines)


def evening_message(db: Database, user) -> str:
    items, _ = today_checklist(db, user)
    missing = [label for done, label in items if not done]
    if not missing:
        return "🌙 Все пункты дня выполнены — идеальный день! Ложись вовремя, завтра снова в бой 💪"
    return ("🌙 <b>Время подвести итоги дня</b>\n\nЕщё не отмечено:\n" +
            "\n".join(f"⬜️ {m}" for m in missing) +
            "\n\nЗаполни, пока помнишь. И запиши все траты за день 💰")


async def reminder_loop(bot: Bot, db: Database) -> None:
    sent: set[tuple[int, str, str]] = set()  # (user_id, kind, date)
    while True:
        try:
            for user in db.all_users():
                now = now_for(user)
                hhmm, today = now.strftime("%H:%M"), now.date().isoformat()
                if today < user["start_date"]:
                    continue
                for kind, at, build in (("m", user["morning_time"], morning_message),
                                        ("e", user["evening_time"], evening_message)):
                    key = (user["user_id"], kind, today)
                    if hhmm == at and key not in sent:
                        sent.add(key)
                        await bot.send_message(user["user_id"], build(db, user), reply_markup=main_menu())
        except Exception:
            log.exception("reminder loop failed")
        await asyncio.sleep(20)
