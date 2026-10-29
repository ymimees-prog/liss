"""Background loop that sends morning and evening reminders in each user's timezone."""
import asyncio
import logging

from aiogram import Bot

from . import ai
from .common import now_for
from .db import Database
from .handlers.main import today_checklist
from .keyboards import lesson_kb, main_menu
from .lessons import render_lesson
from .logic import CHALLENGE_DAYS, challenge_day, parse_iso, random_motivation, time_to_minutes

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
    if db.next_todo(user["user_id"]):
        lines.append("Ниже — твоя тема дня 👇")
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


# Reminders are sent at the first check after their time, but not if more than this late
# (e.g. the bot was off all morning — no "good morning" at 3 pm).
LATE_LIMIT_MINUTES = 180


async def send_due_reminders(bot: Bot, db: Database) -> None:
    for user in db.all_users():
        now = now_for(user)
        today = now.date()
        if today.isoformat() < user["start_date"]:
            continue
        minutes_now = now.hour * 60 + now.minute
        for kind, at in (("m", user["morning_time"]), ("e", user["evening_time"])):
            delay = minutes_now - time_to_minutes(at)
            if not 0 <= delay <= LATE_LIMIT_MINUTES or not db.claim_reminder(user["user_id"], kind, today):
                continue
            build = morning_message if kind == "m" else evening_message
            await bot.send_message(user["user_id"], build(db, user), reply_markup=main_menu())
            if kind == "m":
                topic = db.next_todo(user["user_id"])
                if topic:
                    await bot.send_message(
                        user["user_id"], "🎯 <b>Тема дня</b>\n\n" + render_lesson(topic["subject"], topic["title"]),
                        reply_markup=lesson_kb(topic["id"], ai.enabled()), disable_web_page_preview=True,
                    )


async def reminder_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            await send_due_reminders(bot, db)
        except Exception:
            log.exception("reminder loop failed")
        await asyncio.sleep(30)
