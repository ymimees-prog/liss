"""Drives the real dispatcher with fake Telegram updates and records what the bot sends."""
import asyncio
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot.common import UserMiddleware
from bot.db import Database
from bot.handlers import college, diary, finance, it, main, study

UID = 42
CHAT = Chat(id=UID, type="private")
TG_USER = User(id=UID, is_bot=False, first_name="Лиса")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[str] = []

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        if isinstance(method, SendMessage):
            self.sent.append(method.text)
            return Message(message_id=len(self.sent), date=datetime.now(), chat=CHAT, text=method.text)
        if getattr(method, "text", None):
            self.sent.append(method.text)
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""


class Harness:
    def __init__(self):
        self.db = Database(":memory:")
        self.session = FakeSession()
        self.bot = Bot("1:TEST", session=self.session)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp["db"] = self.db
        mw = UserMiddleware(self.db, frozenset(), "Europe/Moscow")
        self.dp.message.outer_middleware(mw)
        self.dp.callback_query.outer_middleware(mw)
        self.dp.include_routers(main.router, study.router, college.router, it.router, diary.router, finance.router)
        self.n = 0

    def _id(self):
        self.n += 1
        return self.n

    async def text(self, text: str) -> str:
        self.session.sent.clear()
        msg = Message(message_id=self._id(), date=datetime.now(), chat=CHAT, from_user=TG_USER, text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self._id(), message=msg))
        return "\n---\n".join(self.session.sent)

    async def click(self, data: str) -> str:
        self.session.sent.clear()
        msg = Message(message_id=self._id(), date=datetime.now(), chat=CHAT, text="x")
        cb = CallbackQuery(id=str(self._id()), from_user=TG_USER, chat_instance="c", message=msg, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=self._id(), callback_query=cb))
        return "\n---\n".join(self.session.sent)


def run(coro):
    return asyncio.run(coro)


def test_full_day_flow():
    # Routers are module-level singletons, so everything runs in one harness/event loop.
    async def scenario():
        h = Harness()
        assert "90 тяжёлых дней" in await h.text("/start")

        # IT: starter plan, log a session through the form
        assert "OSINT" in await h.click("it:starter")
        assert "добавила 22 тем" in await h.click("it:plan:python")
        for plan in ("ai", "osint", "trading"):
            assert "добавила" in await h.click(f"it:plan:{plan}")
        assert "уже загружен" in await h.click("it:plan:trading")
        await h.click("it:skill:python")
        await h.click("it:min:60")
        out = await h.click("it:nonote")
        assert "Норма в час выполнена" in out

        # Study: add topics, learn one
        await h.click("st:addarea:college")
        out = await h.text("Математика: Производные\nИнтегралы")
        assert "Добавила тем: 2" in out
        topic = h.db.topics(UID, "college", "todo")[0]
        await h.click(f"st:learn:{topic['id']}")
        assert h.db.get_topic(UID, topic["id"])["status"] == "review"

        # Menu button while a form is open cancels the form
        await h.click("st:addarea:it")
        assert "Финансы" in await h.text("💰 Финансы")
        assert h.db.topic_counts(UID, "it")["todo"] == 55

        # College
        await h.click("att:present")
        assert "100%" in await h.click("att:stats")

        # Diary
        await h.click("dy:wake:manual")
        assert "07:15" in await h.text("7:15")
        await h.click("dy:mealkind:breakfast")
        await h.text("овсянка с бананом")
        await h.click("dy:moodset:4")
        await h.click("dy:emo:0")
        await h.click("dy:emo:4")
        await h.click("dy:emo:done")
        out = await h.click("dy:show")
        assert "овсянка" in out and "радость" in out and "благодарность" in out

        # Finance
        await h.click("fn:income")
        out = await h.text("10000 стипендия")
        assert "2 000 ₽" in out
        await h.click("fn:quicksave:2000.00")
        await h.click("fn:expense")
        await h.text("350 кофе")
        await h.click("fn:cat:cafe")
        await h.click("fn:goal")
        assert "Ноутбук" in await h.text("Ноутбук 60000")
        out = await h.click("fn:report")
        assert "Кафе" in out and "Отложено" not in out  # 20% saved -> praise
        assert h.db.tx_total(UID, "saving") == 2000

        # Bad input keeps the form open
        await h.click("fn:expense")
        assert "Не поняла сумму" in await h.text("кофе")
        await h.text("/cancel")

        out = await h.text("📅 Сегодня")
        assert "День 1 из 90" in out
        out = await h.text("📊 Прогресс")
        assert "Прогресс челленджа" in out and "Последние 7 дней" in out

    run(scenario())
