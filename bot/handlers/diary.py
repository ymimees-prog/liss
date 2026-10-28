from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..common import UserText, h, now_for, today_for
from ..db import Database
from ..keyboards import BTN_DIARY, diary_menu, emotions_kb, meal_kb, mood_kb
from ..logic import EMOTIONS, MEAL_KINDS, MOODS, parse_time, time_to_minutes

router = Router()


class Diary(StatesGroup):
    wake = State()
    meal = State()
    emotions = State()
    note = State()


def day_text(db: Database, user) -> str:
    today = today_for(user)
    uid = user["user_id"]
    day = db.get_day(uid, today)
    meals = db.meals(uid, today)
    lines = [f"<b>🌅 Мой день — {today.strftime('%d.%m.%Y')}</b>\n"]
    lines.append(f"⏰ Подъём: <b>{day['wake_time'] if day and day['wake_time'] else '—'}</b>")
    if meals:
        lines.append("🍽 Еда:")
        lines += [f"  {MEAL_KINDS.get(m['kind'], m['kind'])}: {h(m['text'])}" for m in meals]
    else:
        lines.append("🍽 Еда: —")
    if day and day["mood"]:
        lines.append(f"😊 Настроение: {MOODS[day['mood']]} {day['mood']}/5")
    else:
        lines.append("😊 Настроение: —")
    if day and day["emotions"]:
        lines.append(f"💭 Эмоции: {h(day['emotions'])}")
    if day and day["note"]:
        lines.append(f"📝 Заметка: {h(day['note'])}")
    return "\n".join(lines)


@router.message(F.text == BTN_DIARY)
async def diary_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(day_text(db, user), reply_markup=diary_menu())


def wake_comment(hhmm: str) -> str:
    m = time_to_minutes(hhmm)
    if m < 6 * 60:
        return "Ого, ранняя пташка! Главное — не забудь выспаться 😴"
    if m <= 8 * 60:
        return "Отличный подъём! Утро — твоё лучшее время для учёбы 💪"
    if m <= 10 * 60:
        return "Нормально. Попробуй завтра на 15 минут раньше 😉"
    return "Поздновато... Попробуй сегодня лечь пораньше, чтобы завтра встать бодрой 🌙"


@router.callback_query(F.data == "dy:wake:now")
async def wake_now(cb: CallbackQuery, db: Database, user):
    hhmm = now_for(user).strftime("%H:%M")
    db.set_day(user["user_id"], today_for(user), wake_time=hhmm)
    await cb.message.answer(f"⏰ Доброе утро! Подъём в <b>{hhmm}</b>.\n{wake_comment(hhmm)}\n\n"
                            "Начни день со стакана воды и плана на день ☀️")
    await cb.answer()


@router.callback_query(F.data == "dy:wake:manual")
async def wake_manual(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Diary.wake)
    await cb.message.answer("Во сколько проснулась? Например: <code>7:15</code>")
    await cb.answer()


@router.message(StateFilter(Diary.wake), UserText)
async def wake_save(message: Message, state: FSMContext, db: Database, user):
    hhmm = parse_time(message.text)
    if not hhmm:
        await message.answer("Не поняла время 🤔 Напиши так: 7:15")
        return
    await state.clear()
    db.set_day(user["user_id"], today_for(user), wake_time=hhmm)
    await message.answer(f"⏰ Записала подъём в <b>{hhmm}</b>.\n{wake_comment(hhmm)}")


@router.callback_query(F.data == "dy:meal")
async def meal_start(cb: CallbackQuery):
    await cb.message.answer("Какой приём пищи?", reply_markup=meal_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("dy:mealkind:"))
async def meal_kind(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[2]
    await state.set_state(Diary.meal)
    await state.update_data(kind=kind)
    await cb.message.answer(f"{MEAL_KINDS[kind]} — что ела?")
    await cb.answer()


@router.message(StateFilter(Diary.meal), UserText)
async def meal_save(message: Message, state: FSMContext, db: Database, user):
    kind = (await state.get_data()).get("kind", "snack")
    await state.clear()
    db.add_meal(user["user_id"], today_for(user), kind, message.text.strip())
    count = len(db.meals(user["user_id"], today_for(user)))
    tip = "\n\n💧 Не забывай пить воду!" if count == 1 else ""
    await message.answer(f"🍽 Записала ({MEAL_KINDS[kind]}). Приёмов пищи сегодня: {count}{tip}")


@router.callback_query(F.data == "dy:mood")
async def mood_start(cb: CallbackQuery):
    await cb.message.answer("Как ты сегодня в целом? 1 — ужасно, 5 — супер", reply_markup=mood_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("dy:moodset:"))
async def mood_set(cb: CallbackQuery, state: FSMContext, db: Database, user):
    mood = int(cb.data.split(":")[2])
    db.set_day(user["user_id"], today_for(user), mood=mood)
    await state.set_state(Diary.emotions)
    await state.update_data(emotions=[])
    await cb.message.edit_text(f"Настроение: {MOODS[mood]} {mood}/5\n\nКакие эмоции были сегодня? Выбери все подходящие:",
                               reply_markup=emotions_kb(set()))
    await cb.answer()


@router.callback_query(StateFilter(Diary.emotions), F.data.startswith("dy:emo:"))
async def emotions_toggle(cb: CallbackQuery, state: FSMContext, db: Database, user):
    value = cb.data.split(":")[2]
    selected = set((await state.get_data()).get("emotions", []))
    if value == "done":
        await state.clear()
        names = [EMOTIONS[i] for i in sorted(selected)]
        db.set_day(user["user_id"], today_for(user), emotions=", ".join(names) or None)
        await cb.message.edit_text(
            "💭 Записала!" + (f"\n{', '.join(names)}" if names else "") +
            "\n\nХочешь — добавь пару слов о дне через «📝 Заметка о дне». Это поможет потом понять себя."
        )
        await cb.answer()
        return
    i = int(value)
    selected ^= {i}
    await state.update_data(emotions=sorted(selected))
    await cb.message.edit_reply_markup(reply_markup=emotions_kb(selected))
    await cb.answer()


@router.callback_query(F.data.startswith("dy:emo:"))
async def emotions_stale(cb: CallbackQuery):
    await cb.answer("Начни заново через «😊 Настроение и эмоции»")


@router.callback_query(F.data == "dy:note")
async def note_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Diary.note)
    await cb.message.answer("Напиши, как прошёл день: что получилось, что нет, за что себя похвалишь?")
    await cb.answer()


@router.message(StateFilter(Diary.note), UserText)
async def note_save(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    today = today_for(user)
    day = db.get_day(user["user_id"], today)
    note = message.text.strip()
    if day and day["note"]:
        note = day["note"] + "\n" + note
    db.set_day(user["user_id"], today, note=note)
    await message.answer("📝 Сохранила. Ты молодец, что рефлексируешь 💛")


@router.callback_query(F.data == "dy:show")
async def show_day(cb: CallbackQuery, db: Database, user):
    await cb.message.answer(day_text(db, user))
    await cb.answer()
