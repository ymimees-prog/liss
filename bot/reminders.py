"""Timer jobs: the morning digest with the topic of the day, and price alerts."""
import asyncio
import logging

from aiogram import Bot

from . import ai
from .common import now_for
from .db import Database
from .digest import build_digest
from .keyboards import lesson_kb, main_menu
from .lessons import render_lesson
from .logic import time_to_minutes

log = logging.getLogger(__name__)

# The digest goes out at the first check after its time, but not if more than this late
# (e.g. the bot was off all morning — no "good morning" at 3 pm).
LATE_LIMIT_MINUTES = 180


async def send_due_digests(bot: Bot, db: Database) -> None:
    for user in db.all_users():
        if user["digest_time"] == "off":
            continue
        now = now_for(user)
        delay = now.hour * 60 + now.minute - time_to_minutes(user["digest_time"])
        if not 0 <= delay <= LATE_LIMIT_MINUTES or not db.claim_reminder(user["user_id"], "digest", now.date()):
            continue
        await bot.send_message(user["user_id"], await build_digest(db, user), reply_markup=main_menu())
        topic = db.next_todo(user["user_id"])
        if topic:
            await bot.send_message(
                user["user_id"], "🎯 <b>Тема дня</b>\n\n" + render_lesson(topic["subject"], topic["title"]),
                reply_markup=lesson_kb(topic["id"], ai.enabled()), disable_web_page_preview=True,
            )


async def periodic(bot: Bot, db: Database) -> None:
    """Everything that runs on a timer."""
    from .handlers.market import check_alerts
    from .market import MarketError

    await send_due_digests(bot, db)
    try:
        await check_alerts(bot, db)
    except MarketError as e:
        log.warning("price alerts skipped: %s", e)


async def reminder_loop(bot: Bot, db: Database) -> None:
    while True:
        try:
            await periodic(bot, db)
        except Exception:
            log.exception("timer loop failed")
        await asyncio.sleep(30)
