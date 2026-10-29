from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..common import UserText, today_for, week_start
from ..db import Database, streak
from ..keyboards import BTN_IT, grid, it_menu, minutes_kb, skills_kb, skip_kb
from ..logic import IT_SKILLS, ROADMAPS, parse_iso

router = Router()


class LogSession(StatesGroup):
    minutes = State()
    note = State()


def fmt_minutes(m: int) -> str:
    return f"{m // 60} ч {m % 60} мин" if m >= 60 else f"{m} мин"


def it_text(db: Database, user) -> str:
    today = today_for(user)
    uid = user["user_id"]
    week = sum(db.minutes_by_skill(uid, week_start(today), today).values())
    today_m = sum(db.minutes_by_skill(uid, today, today).values())
    c = db.topic_counts(uid, "it")
    return (
        "<b>💻 IT-развитие</b>\n\n"
        f"Сегодня: <b>{fmt_minutes(today_m)}</b>\nЭта неделя: <b>{fmt_minutes(week)}</b>\n"
        f"🔥 Серия дней с учёбой: <b>{streak(db.study_days(uid), today)}</b>\n\n"
        f"Роадмап: изучить {c['todo']} · повторяю {c['review']} · выучено {c['mastered']}\n\n"
        "<i>Цель-минимум: 1 час кода каждый день. Даже 15 минут лучше, чем ноль.</i>"
    )


@router.message(F.text == BTN_IT)
async def it_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(it_text(db, user), reply_markup=it_menu())


@router.callback_query(F.data == "it:log")
async def log_start(cb: CallbackQuery):
    await cb.message.answer("Чем занималась?", reply_markup=skills_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("it:skill:"))
async def log_skill(cb: CallbackQuery, state: FSMContext):
    skill = cb.data.split(":")[2]
    await state.set_state(LogSession.minutes)
    await state.update_data(skill=skill)
    await cb.message.answer(f"{IT_SKILLS[skill]} — сколько минут? Выбери или напиши число.", reply_markup=minutes_kb())
    await cb.answer()


async def _ask_note(message: Message, state: FSMContext, minutes: int):
    await state.update_data(minutes=minutes)
    await state.set_state(LogSession.note)
    await message.answer("Что конкретно сделала/узнала? (одной строкой — потом приятно перечитывать)",
                         reply_markup=skip_kb("it:nonote"))


@router.callback_query(StateFilter(LogSession.minutes), F.data.startswith("it:min:"))
async def log_minutes_button(cb: CallbackQuery, state: FSMContext):
    await _ask_note(cb.message, state, int(cb.data.split(":")[2]))
    await cb.answer()


@router.message(StateFilter(LogSession.minutes), UserText)
async def log_minutes_text(message: Message, state: FSMContext):
    if not message.text.strip().isdigit() or not 0 < int(message.text) <= 960:
        await message.answer("Напиши число минут, например 40")
        return
    await _ask_note(message, state, int(message.text))


async def _save(message: Message, state: FSMContext, db: Database, user, note: str | None):
    data = await state.get_data()
    await state.clear()
    if "skill" not in data or "minutes" not in data:
        return
    today = today_for(user)
    db.add_session(user["user_id"], today, data["skill"], data["minutes"], note)
    total = sum(db.minutes_by_skill(user["user_id"], today, today).values())
    msg = f"💾 Записала: {IT_SKILLS[data['skill']]}, {fmt_minutes(data['minutes'])}.\nСегодня всего: <b>{fmt_minutes(total)}</b>"
    if total >= 60:
        msg += "\n\n🔥 Норма в час выполнена! Ты становишься программистом прямо сейчас."
    await message.answer(msg)


@router.message(StateFilter(LogSession.note), UserText)
async def log_note(message: Message, state: FSMContext, db: Database, user):
    await _save(message, state, db, user, message.text.strip())


@router.callback_query(F.data == "it:nonote")
async def log_no_note(cb: CallbackQuery, state: FSMContext, db: Database, user):
    await _save(cb.message, state, db, user, None)
    await cb.answer()


@router.callback_query(F.data == "it:stats")
async def it_stats(cb: CallbackQuery, db: Database, user):
    today = today_for(user)
    uid = user["user_id"]
    total = db.minutes_by_skill(uid, parse_iso(user["start_date"]), today)
    week = db.minutes_by_skill(uid, week_start(today), today)
    lines = ["<b>📈 IT-статистика за челлендж</b>\n"]
    if not total:
        lines.append("Пока нет записей. Нажми «⏱ Записать занятие» после первой учёбы!")
    for skill, m in total.items():
        lines.append(f"{IT_SKILLS.get(skill, skill)}: {fmt_minutes(m)}")
    if total:
        lines.append(f"\nВсего: <b>{fmt_minutes(sum(total.values()))}</b>")
        lines.append(f"За эту неделю: <b>{fmt_minutes(sum(week.values()))}</b>")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.callback_query(F.data == "it:starter")
async def choose_plan(cb: CallbackQuery):
    lines = ["<b>🚀 Стартовые планы</b>\n"]
    lines += [f"{label} — {desc} ({len(topics)} тем)" for label, desc, topics in ROADMAPS.values()]
    lines.append("\nМожно загрузить несколько. Совет: Python — основа для всего остального, начни с него.")
    await cb.message.answer("\n".join(lines),
                            reply_markup=grid([(label, f"it:plan:{key}") for key, (label, _, _) in ROADMAPS.items()]))
    await cb.answer()


@router.callback_query(F.data.startswith("it:plan:"))
async def load_plan(cb: CallbackQuery, db: Database, user):
    label, desc, topics = ROADMAPS[cb.data.split(":")[2]]
    uid = user["user_id"]
    existing = {t["title"] for st in ("todo", "review", "mastered") for t in db.topics(uid, "it", st)}
    added = 0
    for subject, title in topics:
        if title not in existing:
            db.add_topic(uid, "it", subject, title, today_for(user))
            added += 1
    if added:
        await cb.message.answer(
            f"{label}: добавила {added} тем в твой роадмап — {desc}.\n"
            "Смотри: 💻 IT-развитие → 🗺 Мой роадмап. Иди по порядку, по теме в 1–3 дня."
        )
    else:
        await cb.message.answer(f"{label}: план уже загружен 👌")
    await cb.answer()
