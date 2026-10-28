from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..common import today_for
from ..db import Database
from ..keyboards import BTN_COLLEGE, attendance_kb
from ..logic import ATTENDANCE, parse_iso

router = Router()

ATT_ICON = {"present": "✅", "late": "⏰", "absent": "❌", "excused": "🤒"}


def college_text(db: Database, user) -> str:
    today = today_for(user)
    status = db.get_attendance(user["user_id"], today)
    mark = ATTENDANCE[status] if status else "ещё не отмечено"
    return (f"<b>🏫 Колледж</b>\n\nСегодня ({today.strftime('%d.%m')}): <b>{mark}</b>\n\n"
            "Отметь посещаемость 👇\n<i>Темы колледжа — в разделе 📚 Учёба.</i>")


@router.message(F.text == BTN_COLLEGE)
async def college_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(college_text(db, user), reply_markup=attendance_kb())


@router.callback_query(F.data.in_({f"att:{k}" for k in ATTENDANCE}))
async def set_attendance(cb: CallbackQuery, db: Database, user):
    status = cb.data.split(":")[1]
    db.set_attendance(user["user_id"], today_for(user), status)
    replies = {
        "present": "Молодец! Ещё один день в копилку знаний 📚",
        "late": "Бывает. Завтра попробуй выйти на 10 минут раньше ⏰",
        "absent": "Окей, записала. Узнай у одногруппников, что проходили, и добавь темы в 📚 Учёба.",
        "excused": "Выздоравливай/береги себя 💛 Уважительная причина — не пропуск.",
    }
    await cb.answer(replies[status], show_alert=True)
    await cb.message.edit_text(college_text(db, user), reply_markup=attendance_kb())


@router.callback_query(F.data == "att:stats")
async def attendance_stats(cb: CallbackQuery, db: Database, user):
    today = today_for(user)
    start = parse_iso(user["start_date"])
    s = db.attendance_stats(user["user_id"], start, today)
    counted = s["present"] + s["late"] + s["absent"]
    pct = (s["present"] + s["late"]) / counted * 100 if counted else 0
    strip = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        st = db.get_attendance(user["user_id"], d)
        strip.append(ATT_ICON.get(st, "▫️"))
    text = (
        "<b>📈 Посещаемость за челлендж</b>\n\n"
        f"✅ Была: {s['present']}\n⏰ Опоздания: {s['late']}\n❌ Пропуски: {s['absent']}\n"
        f"🤒 Уважительные: {s['excused']}\n\n"
        f"Посещаемость: <b>{pct:.0f}%</b> (уважительные не считаются)\n\n"
        f"Последние 14 дней:\n{''.join(strip)}"
    )
    await cb.message.answer(text)
    await cb.answer()
