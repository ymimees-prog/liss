from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..common import h, month_start, today_for
from ..db import Database, streak
from ..keyboards import BTN_PROGRESS, BTN_TODAY, main_menu
from ..logic import (ATTENDANCE, CHALLENGE_DAYS, MOODS, challenge_day, minutes_to_time, money, parse_iso,
                     parse_time, progress_bar, random_motivation, time_to_minutes, wake_mood_insight)

router = Router()

HELP = """<b>Как пользоваться</b>

📅 <b>Сегодня</b> — чек-лист дня: что уже отмечено, а что нет
📊 <b>Прогресс</b> — день челленджа, серии, отчёт за неделю
📚 <b>Учёба</b> — темы колледжа и IT: изучить → повторять → выучено
🏫 <b>Колледж</b> — посещаемость
💻 <b>IT-развитие</b> — время на Python/Git/…, стартовый роадмап
🌅 <b>Дневник дня</b> — подъём, еда, настроение, эмоции, заметка
💰 <b>Финансы</b> — доходы, расходы, копилка, цель, советы

<b>Команды</b>
/morning 07:00 — время утреннего напоминания
/evening 21:30 — время вечернего напоминания
/tz Europe/Moscow — часовой пояс
/startday 2026-11-01 — дата начала челленджа
/cancel — отменить ввод"""


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, user):
    await state.clear()
    await message.answer(
        f"Привет, {h(user['name']) or 'бро'}! 👋\n\n"
        f"Я твой напарник на <b>{CHALLENGE_DAYS} тяжёлых дней</b>. Буду следить за учёбой, колледжем, "
        "IT-развитием, режимом дня и деньгами. Каждый день — маленький шаг к тому, чтобы стать "
        "сильнее, умнее и богаче 💪💰\n\n"
        f"Челлендж стартовал: <b>{parse_iso(user['start_date']).strftime('%d.%m.%Y')}</b>\n"
        f"Утром в {user['morning_time']} и вечером в {user['evening_time']} я буду напоминать о себе.\n\n"
        "С чего начать:\n"
        "1. 💻 IT-развитие → 🚀 Стартовые планы (Python, нейросети, OSINT, трейдинг)\n"
        "2. 📚 Учёба → ➕ добавь темы колледжа\n"
        "3. 💰 Финансы → 🎯 поставь цель накоплений\n\n" + HELP,
        reply_markup=main_menu(),
    )


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Окей, отменила.", reply_markup=main_menu())


@router.message(Command("morning", "evening"))
async def set_reminder(message: Message, command: CommandObject, db: Database, user):
    hhmm = parse_time(command.args or "")
    if not hhmm:
        await message.answer(f"Напиши время: <code>/{command.command} 07:30</code>")
        return
    db.update_user(user["user_id"], **{f"{command.command}_time": hhmm})
    await message.answer(f"⏰ Готово, напоминание в {hhmm}.")


@router.message(Command("tz"))
async def set_tz(message: Message, command: CommandObject, db: Database, user):
    try:
        ZoneInfo((command.args or "").strip())
    except (ZoneInfoNotFoundError, ValueError):
        await message.answer("Напиши часовой пояс, например: <code>/tz Europe/Moscow</code> или <code>/tz Asia/Almaty</code>")
        return
    db.update_user(user["user_id"], tz=command.args.strip())
    await message.answer(f"🌍 Часовой пояс: {h(command.args.strip())}")


@router.message(Command("startday"))
async def set_start(message: Message, command: CommandObject, db: Database, user):
    try:
        start = parse_iso((command.args or "").strip())
    except ValueError:
        await message.answer("Напиши дату так: <code>/startday 2026-11-01</code>")
        return
    db.update_user(user["user_id"], start_date=start.isoformat())
    await message.answer(f"🚀 Челлендж начинается {start.strftime('%d.%m.%Y')}. Погнали!")


def today_checklist(db: Database, user) -> tuple[list[tuple[bool, str]], int]:
    """Returns ([(done, label)], due_reviews) for today."""
    uid = user["user_id"]
    today = today_for(user)
    day = db.get_day(uid, today)
    meals = db.meals(uid, today)
    it_min = sum(db.minutes_by_skill(uid, today, today).values())
    due = len(db.due_reviews(uid, today))
    items = [
        (bool(day and day["wake_time"]), f"⏰ Подъём{': ' + day['wake_time'] if day and day['wake_time'] else ''}"),
        (len(meals) > 0, f"🍽 Еда ({len(meals)} записей)"),
        (bool(day and day["mood"]), "😊 Настроение и эмоции"),
        (it_min >= 60, f"💻 IT ≥ 1 часа ({it_min} мин)"),
        (due == 0, f"🔁 Повторения ({due} осталось)"),
        (today.isoformat() in db.finance_days(uid), "💰 Финансы записаны"),
    ]
    if today.weekday() < 5:
        att = db.get_attendance(uid, today)
        items.insert(1, (att is not None, f"🏫 Колледж: {ATTENDANCE[att] if att else 'не отмечено'}"))
    return items, due


@router.message(F.text == BTN_TODAY)
async def today_view(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    today = today_for(user)
    n = challenge_day(parse_iso(user["start_date"]), today)
    items, _ = today_checklist(db, user)
    done = sum(d for d, _ in items)
    lines = [f"<b>📅 День {n} из {CHALLENGE_DAYS}</b> · {today.strftime('%d.%m')}",
             progress_bar(min(n, CHALLENGE_DAYS), CHALLENGE_DAYS), ""]
    lines += [f"{'✅' if d else '⬜️'} {label}" for d, label in items]
    lines.append(f"\nВыполнено: <b>{done}/{len(items)}</b>")
    if done == len(items):
        lines.append("🏆 Идеальный день! Ты машина.")
    lines.append(f"\n💬 <i>{random_motivation()}</i>")
    await message.answer("\n".join(lines))


def week_report(db: Database, user) -> str:
    uid = user["user_id"]
    today = today_for(user)
    since = today - timedelta(days=6)
    days = db.days_between(uid, since, today)
    wakes = [d["wake_time"] for d in days if d["wake_time"]]
    moods = [d["mood"] for d in days if d["mood"]]
    it_min = sum(db.minutes_by_skill(uid, since, today).values())
    att = db.attendance_stats(uid, since, today)
    spent = db.tx_total(uid, "expense", since, today)
    saved = db.tx_total(uid, "saving", since, today)
    lines = ["<b>🗓 Последние 7 дней</b>"]
    if wakes:
        avg = sum(time_to_minutes(w) for w in wakes) / len(wakes)
        lines.append(f"⏰ Средний подъём: {minutes_to_time(avg)}")
    if moods:
        avg_mood = sum(moods) / len(moods)
        lines.append(f"😊 Среднее настроение: {MOODS[round(avg_mood)]} {avg_mood:.1f}/5")
    lines.append(f"💻 IT: {it_min // 60} ч {it_min % 60} мин")
    if any(att.values()):
        lines.append(f"🏫 Колледж: была {att['present'] + att['late']}, пропуски {att['absent']}")
    lines.append(f"💰 Потрачено {money(spent)}, отложено {money(saved)}")
    insight = wake_mood_insight([(d["wake_time"], d["mood"]) for d in db.days_between(uid, today - timedelta(days=29), today)
                                 if d["wake_time"] and d["mood"]])
    if insight:
        lines.append(f"\n🧠 <i>{insight}</i>")
    return "\n".join(lines)


@router.message(F.text == BTN_PROGRESS)
@router.message(Command("week"))
async def progress(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    uid = user["user_id"]
    today = today_for(user)
    start = parse_iso(user["start_date"])
    n = challenge_day(start, today)
    topics = db.topic_counts(uid)
    it_total = sum(db.minutes_by_skill(uid, start, today).values())
    att = db.attendance_stats(uid, start, today)
    counted = att["present"] + att["late"] + att["absent"]
    savings = db.tx_total(uid, "saving")
    lines = [
        "<b>📊 Прогресс челленджа</b>\n",
        f"День <b>{n}</b> из {CHALLENGE_DAYS}",
        progress_bar(min(n, CHALLENGE_DAYS), CHALLENGE_DAYS),
        "",
        f"🔥 Серия дневника: {streak(db.logged_days(uid), today)} дн.",
        f"🔥 Серия IT-учёбы: {streak(db.study_days(uid), today)} дн.",
        "",
        f"📚 Темы: изучено {topics['review'] + topics['mastered']}, выучено навсегда {topics['mastered']}, "
        f"в очереди {topics['todo']}",
        f"💻 Всего на IT: {it_total // 60} ч {it_total % 60} мин",
    ]
    if counted:
        lines.append(f"🏫 Посещаемость: {(att['present'] + att['late']) / counted * 100:.0f}%")
    lines.append(f"🐷 В копилке: {money(savings)}")
    if user["goal_amount"]:
        lines.append(f"🎯 {h(user['goal_name'])}: {progress_bar(savings, user['goal_amount'])}")
    month_spent = db.tx_total(uid, "expense", month_start(today), today)
    lines.append(f"💸 Потрачено в этом месяце: {money(month_spent)}")
    lines.append("")
    lines.append(week_report(db, user))
    await message.answer("\n".join(lines))
