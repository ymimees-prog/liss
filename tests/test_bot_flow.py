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
from bot.handlers import learn, main, market, portfolio, trades
from bot.lessons import LESSONS, render_lesson
from bot.logic import ROADMAP
from bot.reminders import send_due_digests

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
        _dp.include_routers(main.router, market.router, portfolio.router, trades.router, learn.router)
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


def test_learning(fake_api):
    async def scenario():
        h = Harness()
        assert "крипте и трейдинге" in await h.text("/start")
        assert f"Твой ID: <code>{UID}</code>" in await h.text("/id")
        assert h.db.topic_counts(UID)["todo"] == len(ROADMAP)  # roadmap is loaded for a new user

        out = await h.text("🎓 Обучение")
        assert f"Изучить: {len(ROADMAP)}" in out
        first = h.db.next_todo(UID)
        out = await h.click("ln:today")
        assert "Тема дня" in out and "Задание" in out and first["title"] in out
        second = h.db.next_todo(UID, first["id"])
        assert second["title"] in await h.click(f"ln:next:{first['id']}")
        await h.click(f"ln:done:{first['id']}")
        assert h.db.get_topic(UID, first["id"])["status"] == "review"
        assert "Нейросеть не подключена" in await h.click(f"ln:ai:{first['id']}")

        # Own topics without a built-in lesson get a generic study plan
        await h.click("ln:add")
        assert "Добавила тем: 2" in await h.text("Анализ: Фигура голова и плечи\nЧто такое халвинг")
        own = h.db.topics(UID, "todo")[-1]
        assert own["subject"] == "Своё" and "план на 30–40 минут" in await h.click(f"ln:open:{own['id']}")

        # With a key, lessons get AI buttons; the answer is sent to the chat
        async def fake_ask(question, topic=None):
            return f"<b>Подробно про {topic}</b>"
        ai.enabled, ai.ask = (lambda: True), fake_ask
        try:
            assert "Подробно про" in await h.click(f"ln:ai:{second['id']}")
            await h.click(f"ln:ask:{second['id']}")
            assert "Подробно про" in await h.text("А зачем это нужно?")
        finally:
            ai.enabled, ai.ask = real_ai

        assert h.db.due_reviews(UID, date.today() + timedelta(days=1))

    run(scenario())


def test_portfolio(fake_api):
    async def scenario():
        h = Harness()
        assert "Портфель пуст" in await h.text("💼 Портфель")
        await h.click("pf:buy:BTC")
        out = await h.text("0.01 90 000")
        assert "Купила 0,01 BTC по 90 000 $" in out
        # BTC is 95 000 $ in the sample data: value 950 $, +50 $
        assert "950,00 $" in out and "+50,00 $" in out
        await h.click("pf:buy:ETH")
        assert "по 3 200,5 $" in await h.text("1")  # no price -> current price
        await h.click("pf:sell:BTC")
        assert "только 0,01" in await h.text("1 100000")
        await h.click("pf:sell:BTC")
        assert "Зафиксированный результат по BTC: +50,00 $" in await h.text("0.005 100000")
        assert len(h.db.portfolio_txs(UID)) == 3

    run(scenario())


def test_trades_and_calculator(fake_api):
    async def scenario():
        h = Harness()
        assert "Открытых сделок нет" in await h.text("📓 Сделки")
        await h.click("tr:new")
        await h.click("tr:a:BTC")
        await h.click("tr:s:long")
        await h.click("tr:d:1")
        assert "стоп должен быть ниже" in await h.text("95000 96000 99000 0.01")
        assert "Почему входишь" in await h.text("95000 93000 99000 0.01")
        out = await h.text("Отскок от поддержки")
        assert "Риск до стопа: <b>20,00 $</b>" in out and "1:2" in out

        out = await h.text("📓 Сделки")
        assert "#1 BTC 🟢 лонг (демо)" in out and "сейчас 95 000 $" in out
        trade = h.db.open_trades(UID)[0]
        await h.click(f"tr:c:{trade['id']}")
        out = await h.click(f"tr:cp:{trade['take']}")
        assert "+40,00 $" in out and "+2,0R" in out
        await h.text("Держала по плану, не трогала стоп")
        assert h.db.get_trade(UID, trade["id"])["lesson"].startswith("Держала")

        # A losing short, closed by typed price beyond the stop
        await h.click("tr:new")
        await h.click("tr:a:ETH")
        await h.click("tr:s:short")
        await h.click("tr:d:1")
        await h.text("3200 3300 0.1")
        await h.click("tr:noreason")
        t2 = h.db.open_trades(UID)[0]
        await h.click(f"tr:c:{t2['id']}")
        assert "Убыток больше запланированного" in await h.text("3400")
        await h.click("tr:nolesson")

        out = await h.click("tr:stats")
        assert "🎮 Демо</b>: 2 сделок" in out and "Прибыльных: 50%" in out and "Реальные</b>: сделок пока нет" in out
        assert "Держала по плану" in await h.click("tr:closed")

        out = await h.text("🧮 Калькулятор")
        assert "депозит риск% вход стоп" in out
        out = await h.text("1000 1 95000 93000")
        assert "= <b>10,00</b>" in out and "Купить: <b>0,005</b>" in out and "плечо не нужно" in out
        assert "нужно плечо" in await h.text("1000 1 95000 94900")

    run(scenario())


def test_digest_and_morning(fake_api):
    async def scenario():
        h = Harness()
        await h.text("/start")
        out = await h.text("☀️ Сводка")
        assert "USDT" in out and "Биткоин" in out and "дороже официального" in out

        now = datetime.now(ZoneInfo("Europe/Moscow"))
        h.db.update_user(UID, digest_time=f"{now.hour:02d}:{now.minute:02d}")
        h.session.sent.clear()
        await send_due_digests(h.bot, h.db)
        assert any("Сводка" in m for m in h.session.sent) and any("Тема дня" in m for m in h.session.sent)
        h.session.sent.clear()
        await send_due_digests(h.bot, h.db)  # only once per day
        assert h.session.sent == []

        assert "выключена" in await h.text("/digest off")
        assert h.db.get_user(UID)["digest_time"] == "off"

    run(scenario())


def test_every_roadmap_topic_has_a_lesson():
    for subject, title in ROADMAP:
        assert title in LESSONS, title
        assert len(render_lesson(subject, title)) < 4000, title


WEB_SCRIPT = """
import json, sys
sys.path.insert(0, {root!r})
from io import BytesIO
from tests.test_bot_flow import FakeSession
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
assert any("крипте и трейдинге" in m for m in session.sent), session.sent
assert call(f"/tick/{{web._secret}}", method="GET") == ("200 OK", "ok")
print("WEB OK")
"""


def test_webhook_app(tmp_path):
    root = str(Path(__file__).resolve().parent.parent)
    script = tmp_path / "web_check.py"
    script.write_text(WEB_SCRIPT.format(root=root), encoding="utf-8")
    env = {**os.environ, "BOT_TOKEN": "1:TEST", "DB_PATH": str(tmp_path / "t.db"), "ALLOWED_USERS": ""}
    result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60)
    assert "WEB OK" in result.stdout, result.stderr[-3000:]


def test_private_bot_tells_stranger_their_id():
    async def scenario():
        h = Harness()
        _middleware.allowed = frozenset({1})
        try:
            out = await h.text("/start")
        finally:
            _middleware.allowed = frozenset()
        assert out == f"🔒 Это личный бот. Твой Telegram ID: <code>{UID}</code>"
        assert h.db.get_user(UID) is None

    run(scenario())
