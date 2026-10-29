import hashlib
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .common import UserMiddleware
from .config import Config
from .db import Database
from .handlers import college, diary, finance, it, main, market, study

COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="week", description="Прогресс и отчёт за неделю"),
    BotCommand(command="help", description="Как пользоваться"),
    BotCommand(command="cancel", description="Отменить ввод"),
]


def build(config: Config) -> tuple[Bot, Dispatcher, Database]:
    db = Database(config.db_path)
    # Free hosting such as PythonAnywhere only allows outgoing traffic through its proxy.
    proxy = os.environ.get("TELEGRAM_PROXY")
    bot = Bot(
        config.bot_token,
        session=AiohttpSession(proxy=proxy) if proxy else None,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    middleware = UserMiddleware(db, config.allowed_users, config.tz)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    dp.include_routers(main.router, study.router, college.router, it.router, diary.router, finance.router,
                       market.router)
    return bot, dp, db


def webhook_secret(config: Config) -> str:
    """Secret part of the webhook URL so nobody else can post fake updates to the bot."""
    return os.environ.get("WEBHOOK_SECRET") or hashlib.sha256(config.bot_token.encode()).hexdigest()[:32]
