from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import ai
from ..common import UserText, h, today_for
from ..db import Database
from ..keyboards import BTN_LEARN, grid, inline, learn_menu, lesson_kb
from ..lessons import render_lesson, review_questions

router = Router()


class AddTopic(StatesGroup):
    text = State()


class AskAI(StatesGroup):
    question = State()


def overview(db: Database, user) -> str:
    c = db.topic_counts(user["user_id"])
    due = len(db.due_reviews(user["user_id"], today_for(user)))
    return (
        "<b>🎓 Обучение трейдингу и крипте</b>\n\n"
        f"Изучить: {c['todo']} · на повторении: {c['review']} · выучено: {c['mastered']}\n"
        f"🔁 К повторению сегодня: <b>{due}</b>\n\n"
        "<i>Каждое утро я присылаю тему дня. Отмечаешь «Разобрала» — напомню повторить через "
        "1, 3, 7, 14, 30 и 60 дней, чтобы знания не выветрились.</i>"
    )


@router.message(F.text == BTN_LEARN)
async def learn_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(overview(db, user), reply_markup=learn_menu(ai.enabled()))


def topic_list(db: Database, user) -> tuple[str, object]:
    uid = user["user_id"]
    todo, review, mastered = (db.topics(uid, s) for s in ("todo", "review", "mastered"))
    lines = ["<b>📋 Темы</b>\n"]
    if todo:
        lines.append("📌 <b>Изучить:</b>")
        lines += [f"{i}. <i>{h(t['subject'])}</i> — {h(t['title'])}" for i, t in enumerate(todo[:40], 1)]
    else:
        lines.append("📌 Все темы разобраны! Добавь свою ➕")
    if review:
        lines.append("\n🔁 <b>На повторении:</b>")
        lines += [f"• {h(t['title'])} — {t['next_review']}" for t in review[:30]]
    if mastered:
        lines.append(f"\n🏆 <b>Выучено навсегда:</b> {len(mastered)}")
    buttons = [(f"📖 {i}. {t['title'][:30]}", f"ln:open:{t['id']}") for i, t in enumerate(todo[:20], 1)]
    extra = [("➕ Своя тема", "ln:add")]
    if todo or review:
        extra.append(("🗑 Удалить тему", "ln:delmode"))
    return "\n".join(lines), grid(buttons, width=1, extra=extra)


@router.callback_query(F.data == "ln:list")
async def list_topics(cb: CallbackQuery, db: Database, user):
    text, kb = topic_list(db, user)
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


async def send_lesson(message: Message, topic, title: str = "") -> None:
    await message.answer(title + render_lesson(topic["subject"], topic["title"]),
                         reply_markup=lesson_kb(topic["id"], ai.enabled()), disable_web_page_preview=True)


async def send_topic_of_day(message: Message, db: Database, user, after_id: int = 0) -> None:
    topic = db.next_todo(user["user_id"], after_id)
    if topic is None:
        await message.answer("📭 Все темы разобраны! Добавь свою: 🎓 Обучение → ➕ Своя тема.")
        return
    await send_lesson(message, topic, "🎯 <b>Тема дня</b>\n\n")


@router.callback_query(F.data == "ln:today")
async def topic_of_day(cb: CallbackQuery, db: Database, user):
    await send_topic_of_day(cb.message, db, user)
    await cb.answer()


@router.callback_query(F.data.startswith("ln:next:"))
async def next_topic(cb: CallbackQuery, db: Database, user):
    await send_topic_of_day(cb.message, db, user, after_id=int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("ln:open:"))
async def open_topic(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic:
        await send_lesson(cb.message, topic)
    await cb.answer()


@router.callback_query(F.data.startswith("ln:done:"))
async def lesson_done(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic is None or topic["status"] != "todo":
        await cb.answer("Уже отмечено")
        return
    db.mark_learned(user["user_id"], topic["id"], today_for(user))
    await cb.message.edit_reply_markup(reply_markup=inline([[("⏭ Следующая тема", f"ln:next:{topic['id']}")]]))
    await cb.message.answer(f"✅ «{h(topic['title'])}» разобрана! Напомню повторить завтра 💪")
    await cb.answer()


@router.callback_query(F.data == "ln:due")
async def due(cb: CallbackQuery, db: Database, user):
    topics = db.due_reviews(user["user_id"], today_for(user))
    await cb.answer()
    if not topics:
        await cb.message.answer("🎉 На сегодня повторять нечего.")
        return
    await cb.message.answer(f"🔁 Повторений на сегодня: <b>{len(topics)}</b>. Ответь на вопросы без подсказок, "
                            "потом нажми кнопку.")
    for t in topics[:15]:
        await cb.message.answer(
            f"<b>{h(t['title'])}</b>\n\n{review_questions(t['title'])}",
            reply_markup=inline([[("✅ Помню", f"ln:rev:{t['id']}:1"), ("🤔 Забыла", f"ln:rev:{t['id']}:0")]]),
        )


@router.callback_query(F.data.startswith("ln:rev:"))
async def review(cb: CallbackQuery, db: Database, user):
    _, _, topic_id, remembered = cb.data.split(":")
    topic = db.get_topic(user["user_id"], int(topic_id))
    if topic is None or topic["status"] != "review":
        await cb.answer("Уже отмечено")
        return
    nxt = db.review_topic(user["user_id"], topic["id"], remembered == "1", today_for(user))
    if nxt is None:
        verdict = "🏆 Выучено навсегда! Больше не напомню."
    elif remembered == "1":
        verdict = f"✅ Отлично! Следующее повторение: {nxt.isoformat()}"
    else:
        verdict = f"🤔 Перечитай урок (📋 Все темы). Повторим завтра ({nxt.isoformat()})."
    await cb.message.edit_text(f"<b>{h(topic['title'])}</b>\n{verdict}")
    await cb.answer()


@router.callback_query(F.data == "ln:delmode")
async def delete_mode(cb: CallbackQuery, db: Database, user):
    topics = db.topics(user["user_id"], "todo") + db.topics(user["user_id"], "review")
    buttons = [(f"🗑 {t['title'][:32]}", f"ln:del:{t['id']}") for t in topics[:30]]
    await cb.message.answer("Какую тему удалить?", reply_markup=grid(buttons, width=1))
    await cb.answer()


@router.callback_query(F.data.startswith("ln:del:"))
async def delete_topic(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic:
        db.delete_topic(user["user_id"], topic["id"])
        await cb.message.edit_text(f"Удалила тему «{h(topic['title'])}».")
    await cb.answer()


@router.callback_query(F.data == "ln:add")
async def add_ask_text(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddTopic.text)
    await cb.message.answer(
        "Напиши тему (или несколько — каждую с новой строки). Можно с разделом через двоеточие:\n"
        "<code>Анализ: Фигура «голова и плечи»\nКрипта: Что такое халвинг</code>"
    )
    await cb.answer()


@router.message(StateFilter(AddTopic.text), UserText)
async def add_save(message: Message, state: FSMContext, db: Database, user):
    added = 0
    for line in message.text.splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        subject, sep, title = line.partition(":")
        if not sep or not title.strip():
            subject, title = "Своё", line
        db.add_topic(user["user_id"], subject.strip(), title.strip(), today_for(user))
        added += 1
    await state.clear()
    await message.answer(f"➕ Добавила тем: {added}" if added else "Не нашла ни одной темы 🤷")


async def _answer_ai(message: Message, text: str) -> None:
    try:
        await message.answer(text)
    except TelegramBadRequest:  # the model produced HTML Telegram can't parse
        await message.answer(text, parse_mode=None)


@router.callback_query(F.data.startswith("ln:ai:"))
async def explain_more(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic is None or not ai.enabled():
        await cb.answer("Нейросеть не подключена")
        return
    await cb.answer("Думаю… 🤖")
    await cb.message.answer("🤖 Готовлю подробное объяснение, это займёт до минуты…")
    answer = await ai.ask(
        "Объясни эту тему подробнее, чем короткий урок: простыми словами, с примером на криптовалюте, "
        "типичными ошибками новичков и 3 задачами с ответами в конце.",
        f"{topic['subject']}: {topic['title']}",
    )
    await _answer_ai(cb.message, answer)


@router.callback_query(F.data.startswith("ln:ask:"))
async def ask_start(cb: CallbackQuery, state: FSMContext, db: Database, user):
    if not ai.enabled():
        await cb.answer("Нейросеть не подключена")
        return
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    await state.set_state(AskAI.question)
    await state.update_data(topic=f"{topic['subject']}: {topic['title']}" if topic else None)
    await cb.message.answer("❓ Напиши свой вопрос" + (f" по теме «{h(topic['title'])}»" if topic else "") + ":")
    await cb.answer()


@router.message(StateFilter(AskAI.question), UserText)
async def ask_answer(message: Message, state: FSMContext):
    topic = (await state.get_data()).get("topic")
    await state.clear()
    await message.answer("🤖 Думаю…")
    await _answer_ai(message, await ai.ask(message.text, topic))
