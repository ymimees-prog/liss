"""Drives the real dispatcher with fake Telegram updates and records what the bot sends."""
import asyncio
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot import ai
from bot.common import UserMiddleware
from bot.db import Database
from bot.handlers import college, diary, finance, it, main, market, study
from bot.lessons import LESSONS, render_lesson
from bot.logic import ROADMAPS
from bot.reminders import send_due_reminders

UID = 42
real_ai = (ai.enabled, ai.ask)
CHAT = Chat(id=UID, type="private")
TG_USER = User(id=UID, is_bot=False, first_name="Лиса")


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list[str] = []
        self.methods: list[TelegramMethod] = []

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        self.methods.append(method)
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


_dp: Dispatcher | None = None
_middleware = UserMiddleware(None, frozenset(), "Europe/Moscow")


def _dispatcher() -> Dispatcher:
    """Routers are module-level singletons and can be attached only once, so tests share one dispatcher."""
    global _dp
    if _dp is None:
        _dp = Dispatcher(storage=MemoryStorage())
        _dp.message.outer_middleware(_middleware)
        _dp.callback_query.outer_middleware(_middleware)
        _dp.include_routers(main.router, study.router, college.router, it.router, diary.router, finance.router,
                            market.router)
    return _dp


class Harness:
    def __init__(self):
        self.db = Database(":memory:")
        self.session = FakeSession()
        self.bot = Bot("1:TEST", session=self.session)
        self.dp = _dispatcher()
        self.dp["db"] = self.db
        _middleware.db = self.db
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

        # Topic of the day: built-in lesson for roadmap topics, skip, mark as done
        first = h.db.next_todo(UID)
        out = await h.click("st:today")
        assert "Тема дня" in out and "Задание" in out and first["title"] in out
        second = h.db.next_todo(UID, first["id"])
        assert second["title"] in await h.click(f"st:next:{first['id']}")
        await h.click(f"st:done:{first['id']}")
        assert h.db.get_topic(UID, first["id"])["status"] == "review"
        assert "Нейросеть не подключена" in await h.click(f"st:ai:{first['id']}")  # no API key in tests

        # With a key, the lesson gets AI buttons; answers that break Telegram HTML fall back to plain text
        async def fake_ask(question, topic=None):
            return f"<b>Подробно про {topic}</b>"
        ai.enabled, ai.ask = (lambda: True), fake_ask
        try:
            assert "Подробно про" in await h.click(f"st:ai:{second['id']}")
            await h.click(f"st:ask:{second['id']}")
            assert "Подробно про" in await h.text("А зачем это нужно?")
        finally:
            ai.enabled, ai.ask = real_ai

        # Reviews show self-check questions
        due = h.db.due_reviews(UID, date.today() + timedelta(days=1))
        assert due

        # Menu button while a form is open cancels the form
        await h.click("st:addarea:it")
        assert "Финансы" in await h.text("💰 Финансы")
        assert h.db.topic_counts(UID, "it")["todo"] == 54  # one done via topic of the day

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

        # Reminders: morning sends greeting + topic of the day, only once per day
        now = datetime.now(ZoneInfo("Europe/Moscow"))
        h.db.update_user(UID, morning_time=f"{now.hour:02d}:{now.minute:02d}", evening_time="23:59"
                         if now.hour < 23 else "00:00")
        h.session.sent.clear()
        await send_due_reminders(h.bot, h.db)
        sent = "\n".join(h.session.sent)
        assert "Доброе утро" in sent and "Тема дня" in sent
        h.session.sent.clear()
        await send_due_reminders(h.bot, h.db)
        assert not any("Доброе утро" in m for m in h.session.sent)

    run(scenario())


def test_every_roadmap_topic_has_a_lesson():
    for _, _, topics in ROADMAPS.values():
        for subject, title in topics:
            assert title in LESSONS, title
            text = render_lesson(subject, title)
            assert len(text) < 4000, title
    assert "план на 30–40 минут" in render_lesson("История", "Реформы Петра I")


WEB_SCRIPT = """
import json, sys
sys.path.insert(0, {root!r}); sys.path.insert(0, {tests!r})
from io import BytesIO
from test_bot_flow import FakeSession
import bot.web as web
web._bot.session = session = FakeSession()

def call(path, body=b"", method="POST"):
    out = {{}}
    env = {{"PATH_INFO": path, "REQUEST_METHOD": method, "CONTENT_LENGTH": str(len(body)), "wsgi.input": BytesIO(body)}}
    res = web.application(env, lambda status, headers: out.setdefault("status", status))
    return out["status"], b"".join(res).decode()

update = {{"update_id": 1, "message": {{"message_id": 1, "date": 0, "chat": {{"id": 42, "type": "private"}},
          "from": {{"id": 42, "is_bot": False, "first_name": "Лиса"}}, "text": "/start"}}}}
assert call("/tg/wrong", json.dumps(update).encode())[0].startswith("404")
assert session.sent == []
assert call(f"/tg/{{web._secret}}", json.dumps(update).encode())[0] == "200 OK"
assert any("90 тяжёлых дней" in m for m in session.sent), session.sent
assert call(f"/tick/{{web._secret}}", method="GET") == ("200 OK", "ok")
print("WEB OK")
"""


def test_webhook_app(tmp_path):
    root = str(Path(__file__).resolve().parent.parent)
    script = tmp_path / "web_check.py"
    script.write_text(WEB_SCRIPT.format(root=root, tests=str(Path(__file__).resolve().parent)), encoding="utf-8")
    env = {**os.environ, "BOT_TOKEN": "1:TEST", "DB_PATH": str(tmp_path / "t.db"), "ALLOWED_USERS": ""}
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert "WEB OK" in result.stdout, result.stderr[-3000:]
