from datetime import date, datetime
from html import escape
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from aiogram import BaseMiddleware, F
from aiogram.types import TelegramObject, User

from .db import Database
from .keyboards import MENU_BUTTONS
from .logic import ROADMAP

# Free text typed by the user while a form is open (not a menu button, not a command).
UserText = F.text & ~F.text.in_(MENU_BUTTONS) & ~F.text.startswith("/")


def now_for(user) -> datetime:
    return datetime.now(ZoneInfo(user["tz"]))


def today_for(user) -> date:
    return now_for(user).date()


def h(text: str | None) -> str:
    return escape(text or "")


class UserMiddleware(BaseMiddleware):
    """Restricts access to ALLOWED_USERS and injects the `user` row (creating it on first contact)."""

    def __init__(self, db: Database, allowed: frozenset[int], default_tz: str):
        self.db, self.allowed, self.default_tz = db, allowed, default_tz

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: User | None = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)
        if self.allowed and tg_user.id not in self.allowed:
            return None
        if self.db.create_user(tg_user.id, tg_user.first_name or "", self.default_tz):
            today = datetime.now(ZoneInfo(self.default_tz)).date()
            for subject, title in ROADMAP:
                self.db.add_topic(tg_user.id, subject, title, today)
        data["user"] = self.db.get_user(tg_user.id)
        return await handler(event, data)
