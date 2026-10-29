from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

BTN_DIGEST = "☀️ Сводка"
BTN_MARKET = "📈 Рынок"
BTN_PORTFOLIO = "💼 Портфель"
BTN_TRADES = "📓 Сделки"
BTN_CALC = "🧮 Калькулятор"
BTN_LEARN = "🎓 Обучение"

MENU_BUTTONS = (BTN_DIGEST, BTN_MARKET, BTN_PORTFOLIO, BTN_TRADES, BTN_CALC, BTN_LEARN)


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for text in MENU_BUTTONS:
        kb.button(text=text)
    kb.adjust(2, 2, 2)
    return kb.as_markup(resize_keyboard=True)


def inline(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """rows of (text, callback_data)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows]
    )


def grid(items: list[tuple[str, str]], width: int = 2, extra: list[tuple[str, str]] | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, data in items:
        kb.button(text=text, callback_data=data)
    kb.adjust(width)
    for text, data in extra or []:
        kb.row(InlineKeyboardButton(text=text, callback_data=data))
    return kb.as_markup()


def learn_menu(ai_enabled: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [("🎯 Тема дня", "ln:today"), ("🔁 Повторить", "ln:due")],
        [("📋 Все темы", "ln:list"), ("➕ Своя тема", "ln:add")],
    ]
    if ai_enabled:
        rows.append([("🤖 Спросить нейросеть", "ln:ask:0")])
    return inline(rows)


def lesson_kb(topic_id: int, ai_enabled: bool) -> InlineKeyboardMarkup:
    rows = [[("✅ Разобрала", f"ln:done:{topic_id}"), ("⏭ Другую тему", f"ln:next:{topic_id}")]]
    if ai_enabled:
        rows.append([("🤖 Объясни подробнее", f"ln:ai:{topic_id}"), ("❓ Задать вопрос", f"ln:ask:{topic_id}")])
    return inline(rows)


def skip_kb(data: str) -> InlineKeyboardMarkup:
    return inline([[("⏭ Пропустить", data)]])
