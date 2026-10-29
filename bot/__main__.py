"""Polling mode: run on your own computer with `python -m bot`."""
import asyncio
import logging

from .app import COMMANDS, build
from .config import load_config
from .reminders import reminder_loop


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot, dp, db = build(load_config())
    await bot.delete_webhook()  # in case the bot was switched over from hosting mode
    await bot.set_my_commands(COMMANDS)
    reminders = asyncio.create_task(reminder_loop(bot, db))
    try:
        await dp.start_polling(bot)
    finally:
        reminders.cancel()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
