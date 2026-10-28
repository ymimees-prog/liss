from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from .logic import ATTENDANCE, EMOTIONS, EXPENSE_CATEGORIES, IT_SKILLS, MEAL_KINDS, MOODS

BTN_TODAY = "📅 Сегодня"
BTN_STUDY = "📚 Учёба"
BTN_COLLEGE = "🏫 Колледж"
BTN_IT = "💻 IT-развитие"
BTN_DIARY = "🌅 Дневник дня"
BTN_MONEY = "💰 Финансы"
BTN_PROGRESS = "📊 Прогресс"


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    for text in (BTN_TODAY, BTN_PROGRESS, BTN_STUDY, BTN_COLLEGE, BTN_IT, BTN_DIARY, BTN_MONEY):
        kb.button(text=text)
    kb.adjust(2, 2, 2, 1)
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


def study_menu() -> InlineKeyboardMarkup:
    return inline([
        [("🔁 Повторить сегодня", "st:due")],
        [("🏫 Темы колледжа", "st:list:college"), ("💻 IT-темы", "st:list:it")],
        [("➕ Добавить тему", "st:add")],
    ])


def area_choice() -> InlineKeyboardMarkup:
    return inline([[("🏫 Колледж", "st:addarea:college"), ("💻 IT", "st:addarea:it")]])


def attendance_kb() -> InlineKeyboardMarkup:
    return grid([(v, f"att:{k}") for k, v in ATTENDANCE.items()], extra=[("📈 Статистика посещаемости", "att:stats")])


def it_menu() -> InlineKeyboardMarkup:
    return inline([
        [("⏱ Записать занятие", "it:log")],
        [("🗺 Мой роадмап", "st:list:it"), ("📈 Статистика", "it:stats")],
        [("🚀 Загрузить стартовый план Python + GitHub", "it:starter")],
    ])


def skills_kb() -> InlineKeyboardMarkup:
    return grid([(v, f"it:skill:{k}") for k, v in IT_SKILLS.items()])


def minutes_kb() -> InlineKeyboardMarkup:
    return grid([(f"{m} мин", f"it:min:{m}") for m in (15, 30, 45, 60, 90, 120)], width=3)


def diary_menu() -> InlineKeyboardMarkup:
    return inline([
        [("⏰ Я проснулась (сейчас)", "dy:wake:now"), ("✏️ Время подъёма", "dy:wake:manual")],
        [("🍽 Что я ела", "dy:meal")],
        [("😊 Настроение и эмоции", "dy:mood")],
        [("📝 Заметка о дне", "dy:note"), ("👀 Мой день", "dy:show")],
    ])


def meal_kb() -> InlineKeyboardMarkup:
    return grid([(v, f"dy:mealkind:{k}") for k, v in MEAL_KINDS.items()])


def mood_kb() -> InlineKeyboardMarkup:
    return grid([(f"{e} {n}", f"dy:moodset:{n}") for n, e in MOODS.items()], width=5)


def emotions_kb(selected: set[int]) -> InlineKeyboardMarkup:
    items = [(("✔️ " if i in selected else "") + e, f"dy:emo:{i}") for i, e in enumerate(EMOTIONS)]
    return grid(items, width=2, extra=[("✅ Готово", "dy:emo:done")])


def money_menu() -> InlineKeyboardMarkup:
    return inline([
        [("➖ Расход", "fn:expense"), ("➕ Доход", "fn:income")],
        [("🐷 В копилку", "fn:save"), ("💸 Взять из копилки", "fn:unsave")],
        [("📊 Отчёт за месяц", "fn:report"), ("🎯 Цель накоплений", "fn:goal")],
        [("🧾 Последние записи", "fn:last"), ("💡 Совет", "fn:tip")],
    ])


def categories_kb() -> InlineKeyboardMarkup:
    return grid([(v, f"fn:cat:{k}") for k, v in EXPENSE_CATEGORIES.items()])


def skip_kb(data: str) -> InlineKeyboardMarkup:
    return inline([[("⏭ Пропустить", data)]])
