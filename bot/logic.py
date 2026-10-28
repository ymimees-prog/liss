"""Pure helpers: challenge math, spaced repetition, finance advice. No Telegram, no DB."""
import random
import re
from datetime import date, timedelta

CHALLENGE_DAYS = 90

# Spaced repetition: days until the next review after each successful recall.
REVIEW_INTERVALS = [1, 3, 7, 14, 30, 60]

EXPENSE_CATEGORIES = {
    "food": "🍔 Еда",
    "transport": "🚌 Транспорт",
    "study": "📚 Учёба",
    "phone": "📱 Связь/подписки",
    "health": "💊 Здоровье",
    "home": "🏠 Дом/быт",
    "fun": "🎉 Развлечения",
    "clothes": "👗 Одежда/красота",
    "cafe": "☕ Кафе/доставка",
    "other": "📦 Другое",
}
# For the 50/30/20 rule: what counts as a necessity. Everything else is a "want".
NEEDS = {"food", "transport", "study", "phone", "health", "home"}

IT_SKILLS = {
    "python": "🐍 Python",
    "git": "🐙 Git/GitHub",
    "algo": "🧠 Алгоритмы",
    "sql": "🗄 SQL/БД",
    "linux": "🐧 Linux/терминал",
    "web": "🌐 Веб/HTML/CSS",
    "english": "🇬🇧 Английский",
    "project": "🛠 Свой проект",
    "other": "📦 Другое",
}

EMOTIONS = [
    "😊 радость", "😌 спокойствие", "💪 уверенность", "🔥 азарт", "🙏 благодарность",
    "😴 усталость", "😰 тревога", "😤 злость", "😢 грусть", "😐 апатия", "🤯 перегруз", "🥰 любовь",
]

MOODS = {1: "😞", 2: "😕", 3: "😐", 4: "🙂", 5: "🤩"}

MEAL_KINDS = {"breakfast": "🍳 Завтрак", "lunch": "🍲 Обед", "dinner": "🍝 Ужин", "snack": "🍎 Перекус"}

ATTENDANCE = {"present": "✅ Была", "late": "⏰ Опоздала", "absent": "❌ Пропустила", "excused": "🤒 Уважительная"}

STARTER_ROADMAP = [
    ("Python", "Установка Python, VS Code/PyCharm, первый скрипт"),
    ("Python", "Переменные и типы данных: int, float, str, bool"),
    ("Python", "Ввод/вывод, f-строки"),
    ("Python", "Условия if/elif/else"),
    ("Python", "Циклы for и while"),
    ("Python", "Списки, кортежи"),
    ("Python", "Словари и множества"),
    ("Python", "Функции, аргументы, return"),
    ("Python", "Работа со строками и методами"),
    ("Python", "Исключения try/except"),
    ("Python", "Файлы: чтение и запись"),
    ("Python", "Модули, pip, виртуальное окружение venv"),
    ("Python", "ООП: классы и объекты"),
    ("Python", "ООП: наследование, инкапсуляция"),
    ("Python", "List/dict comprehensions"),
    ("Git", "Что такое Git, установка, git config"),
    ("Git", "git init, add, commit, status, log"),
    ("Git", "Ветки: branch, checkout/switch, merge"),
    ("GitHub", "Аккаунт, репозиторий, git clone/push/pull"),
    ("GitHub", "Pull Request и code review"),
    ("GitHub", "README.md и оформление профиля"),
    ("Проект", "Свой мини-проект на Python и выложить на GitHub"),
]

FINANCE_TIPS = [
    "Сначала заплати себе: как только пришли деньги — сразу отложи 10–20% в копилку, а не «что останется».",
    "Правило 50/30/20: 50% дохода — на необходимое, 30% — на желания, 20% — в накопления.",
    "Правило 24 часов: хочешь купить что-то не из списка — подожди сутки. Половина желаний пройдёт.",
    "Финансовая подушка — это 3–6 месяцев твоих расходов. Это первая цель перед любыми инвестициями.",
    "Маленькие траты съедают больше всего: кофе за 200 ₽ каждый день — это 6000 ₽ в месяц.",
    "Держи накопления на отдельном накопительном счёте/вкладе — с процентом и подальше от карты для трат.",
    "Проверь подписки: часто мы платим за то, чем не пользуемся.",
    "Не бери кредиты и рассрочки на желания. Долг — это деньги из твоего будущего.",
    "Ставь цель с суммой и датой: «30 000 ₽ на ноутбук к марту» мотивирует сильнее, чем «накопить».",
    "Записывай ВСЕ траты хотя бы месяц — без этого невозможно понять, куда утекают деньги.",
    "Лучшая инвестиция сейчас — в себя: навыки программиста потом вырастят твой доход в разы.",
    "Покупай по списку и не ходи в магазин голодной — это реально экономит.",
    "Если доход вырос — не увеличивай траты сразу. Увеличь процент накоплений.",
]

MOTIVATION = [
    "Дисциплина — это выбирать между тем, чего хочешь сейчас, и тем, чего хочешь больше всего.",
    "Не нужно быть идеальной. Нужно просто не пропускать два дня подряд.",
    "Каждый закоммиченный день — это кирпич в твоё будущее.",
    "Через 90 дней ты будешь рада, что начала сегодня.",
    "Маленькие шаги каждый день лучше, чем большие рывки раз в месяц.",
    "Ты не соревнуешься ни с кем, кроме себя вчерашней.",
    "Программист — это человек, который не сдался на ошибке.",
]


def challenge_day(start: date, today: date) -> int:
    """1-based day of the challenge (can exceed 90 once it's over, 0 if not started)."""
    if today < start:
        return 0
    return (today - start).days + 1


def progress_bar(value: float, total: float, width: int = 10) -> str:
    ratio = 0 if total <= 0 else max(0.0, min(1.0, value / total))
    filled = round(ratio * width)
    return "▓" * filled + "░" * (width - filled) + f" {ratio * 100:.0f}%"


def next_review(stage: int, today: date) -> date | None:
    """Date of the next review after a successful recall at `stage`, or None when mastered."""
    if stage >= len(REVIEW_INTERVALS):
        return None
    return today + timedelta(days=REVIEW_INTERVALS[stage])


_AMOUNT_RE = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*(?:₽|р\.?|руб\.?)?\s*(.*)$", re.IGNORECASE)


def parse_amount(text: str) -> tuple[float, str] | None:
    """'350 кофе' -> (350.0, 'кофе'); '1 200,50' is not supported, keep it simple."""
    m = _AMOUNT_RE.match(text or "")
    if not m:
        return None
    amount = float(m.group(1).replace(",", "."))
    if amount <= 0:
        return None
    return amount, m.group(2).strip()


_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_time(text: str) -> str | None:
    """'7:05' / '07.05' -> '07:05'."""
    m = _TIME_RE.match(text or "")
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2))
    if h > 23 or mnt > 59:
        return None
    return f"{h:02d}:{mnt:02d}"


def time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def minutes_to_time(total: float) -> str:
    total = round(total)
    return f"{total // 60:02d}:{total % 60:02d}"


def money(x: float) -> str:
    s = f"{x:,.2f}".replace(",", " ").replace(".00", "")
    return s.replace(".", ",") + " ₽"


def budget_503020(income: float) -> dict[str, float]:
    return {"needs": income * 0.5, "wants": income * 0.3, "savings": income * 0.2}


def finance_advice(income: float, expenses_by_cat: dict[str, float], saved: float) -> list[str]:
    """Plain-language observations about a month of money."""
    advice = []
    spent = sum(expenses_by_cat.values())
    if income <= 0:
        if spent:
            advice.append("Доходов в этом месяце не записано — добавь их, чтобы я смогла посчитать бюджет 50/30/20.")
        return advice
    plan = budget_503020(income)
    needs = sum(v for k, v in expenses_by_cat.items() if k in NEEDS)
    wants = spent - needs
    if wants > plan["wants"]:
        advice.append(f"На желания ушло {money(wants)} — это больше 30% дохода ({money(plan['wants'])}). Попробуй правило 24 часов.")
    if saved < plan["savings"]:
        advice.append(f"Отложено {money(saved)} из рекомендуемых {money(plan['savings'])} (20%). Осталось {money(plan['savings'] - saved)}.")
    else:
        advice.append(f"Ты отложила {money(saved)} — это {saved / income * 100:.0f}% дохода. Отличная работа! 🎉")
    if spent + saved > income:
        advice.append("⚠️ Расходы и накопления больше дохода — ты тратишь больше, чем зарабатываешь.")
    if expenses_by_cat:
        top = max(expenses_by_cat, key=expenses_by_cat.get)
        advice.append(f"Самая большая статья расходов — {EXPENSE_CATEGORIES.get(top, top)}: {money(expenses_by_cat[top])}.")
    return advice


def wake_mood_insight(days: list[tuple[str, int]]) -> str | None:
    """days = [(wake 'HH:MM', mood 1..5)]. Compares mood on early vs late wake-ups."""
    if len(days) < 4:
        return None
    mins = sorted(time_to_minutes(w) for w, _ in days)
    median = mins[len(mins) // 2]
    early = [m for w, m in days if time_to_minutes(w) < median]
    late = [m for w, m in days if time_to_minutes(w) >= median]
    if not early or not late:
        return None
    e, l_ = sum(early) / len(early), sum(late) / len(late)
    if abs(e - l_) < 0.5:
        return "Время подъёма пока почти не влияет на твоё настроение."
    when = "раньше" if e > l_ else "позже"
    return (f"Когда ты встаёшь {when} {minutes_to_time(median)}, настроение в среднем выше "
            f"({max(e, l_):.1f} против {min(e, l_):.1f}). Интересно, правда?")


def random_tip() -> str:
    return random.choice(FINANCE_TIPS)


def random_motivation() -> str:
    return random.choice(MOTIVATION)


def parse_iso(d: str) -> date:
    return date.fromisoformat(d)
