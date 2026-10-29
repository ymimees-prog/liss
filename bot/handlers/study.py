from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import ai
from ..common import UserText, h, today_for
from ..db import Database
from ..keyboards import BTN_STUDY, area_choice, grid, inline, lesson_kb, study_menu
from ..lessons import render_lesson, review_questions

router = Router()

AREA_NAMES = {"college": "🏫 Колледж", "it": "💻 IT"}
DEFAULT_SUBJECT = {"college": "Общее", "it": "IT"}


class AddTopic(StatesGroup):
    text = State()


class AskAI(StatesGroup):
    question = State()


def study_overview(db: Database, user) -> str:
    today = today_for(user)
    lines = ["<b>📚 Учёба</b>\n"]
    for area, name in AREA_NAMES.items():
        c = db.topic_counts(user["user_id"], area)
        lines.append(f"{name}: изучить — {c['todo']}, на повторении — {c['review']}, выучено — {c['mastered']}")
    due = len(db.due_reviews(user["user_id"], today))
    lines.append(f"\n🔁 На сегодня к повторению: <b>{due}</b>")
    lines.append("\n<i>Как это работает: отмечаешь тему изученной — я напомню повторить её через 1, 3, 7, 14, 30 и 60 дней. "
                 "Так знания уходят в долгую память.</i>")
    return "\n".join(lines)


@router.message(F.text == BTN_STUDY)
async def study_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(study_overview(db, user), reply_markup=study_menu(ai.enabled()))


def topic_list(db: Database, user, area: str) -> tuple[str, object]:
    uid = user["user_id"]
    todo = db.topics(uid, area, "todo")
    review = db.topics(uid, area, "review")
    mastered = db.topics(uid, area, "mastered")
    lines = [f"<b>{AREA_NAMES[area]} — темы</b>\n"]
    if todo:
        lines.append("📌 <b>Надо изучить:</b>")
        lines += [f"{i}. <i>{h(t['subject'])}</i> — {h(t['title'])}" for i, t in enumerate(todo[:40], 1)]
        if len(todo) > 40:
            lines.append(f"…и ещё {len(todo) - 40}")
    else:
        lines.append("📌 Список «надо изучить» пуст. Добавь темы ➕")
    if review:
        lines.append("\n🔁 <b>На повторении:</b>")
        lines += [f"• {h(t['title'])} — следующее повторение {t['next_review']}" for t in review[:30]]
        if len(review) > 30:
            lines.append(f"…и ещё {len(review) - 30}")
    if mastered:
        lines.append(f"\n🏆 <b>Выучено навсегда:</b> {len(mastered)}")
    buttons = [(f"✅ {i}. {t['title'][:28]}", f"st:learn:{t['id']}") for i, t in enumerate(todo[:20], 1)]
    extra = [("➕ Добавить тему", f"st:addarea:{area}")]
    if todo or review:
        extra.append(("🗑 Удалить тему", f"st:delmode:{area}"))
    if buttons:
        lines.append("\nНажми на тему, когда изучишь её 👇")
    return "\n".join(lines), grid(buttons, width=1, extra=extra)


@router.callback_query(F.data.startswith("st:list:"))
async def list_topics(cb: CallbackQuery, db: Database, user):
    area = cb.data.split(":")[2]
    text, kb = topic_list(db, user, area)
    await cb.message.answer(text, reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data.startswith("st:learn:"))
async def learn_topic(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic is None or topic["status"] != "todo":
        await cb.answer("Уже отмечено")
        return
    db.mark_learned(user["user_id"], topic["id"], today_for(user))
    await cb.answer("Супер! Напомню повторить завтра 💪", show_alert=False)
    text, kb = topic_list(db, user, topic["area"])
    await cb.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("st:delmode:"))
async def delete_mode(cb: CallbackQuery, db: Database, user):
    area = cb.data.split(":")[2]
    topics = db.topics(user["user_id"], area, "todo") + db.topics(user["user_id"], area, "review")
    buttons = [(f"🗑 {t['title'][:32]}", f"st:del:{t['id']}") for t in topics[:30]]
    await cb.message.answer("Какую тему удалить?", reply_markup=grid(buttons, width=1))
    await cb.answer()


@router.callback_query(F.data.startswith("st:del:"))
async def delete_topic(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic:
        db.delete_topic(user["user_id"], topic["id"])
        await cb.message.edit_text(f"Удалила тему «{h(topic['title'])}».")
    await cb.answer()


@router.callback_query(F.data == "st:due")
async def due(cb: CallbackQuery, db: Database, user):
    topics = db.due_reviews(user["user_id"], today_for(user))
    await cb.answer()
    if not topics:
        await cb.message.answer("🎉 На сегодня повторять нечего. Можно изучить что-то новое!")
        return
    await cb.message.answer(
        f"🔁 Повторений на сегодня: <b>{len(topics)}</b>.\n"
        "Вспомни тему без подсказок (объясни вслух, напиши конспект или реши задачу), потом нажми кнопку."
    )
    for t in topics[:15]:
        await cb.message.answer(
            f"<i>{h(t['subject'])}</i>\n<b>{h(t['title'])}</b>\n\n{review_questions(t['title'])}",
            reply_markup=inline([[("✅ Помню", f"st:rev:{t['id']}:1"), ("🤔 Забыла", f"st:rev:{t['id']}:0")]]),
        )


@router.callback_query(F.data.startswith("st:rev:"))
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
        verdict = f"🤔 Ничего страшного — перечитай тему. Повторим завтра ({nxt.isoformat()})."
    await cb.message.edit_text(f"<b>{h(topic['title'])}</b>\n{verdict}")
    await cb.answer()


@router.callback_query(F.data == "st:add")
async def add_choose_area(cb: CallbackQuery):
    await cb.message.answer("Куда добавить тему?", reply_markup=area_choice())
    await cb.answer()


@router.callback_query(F.data.startswith("st:addarea:"))
async def add_ask_text(cb: CallbackQuery, state: FSMContext):
    area = cb.data.split(":")[2]
    await state.set_state(AddTopic.text)
    await state.update_data(area=area)
    example = "Математика: Производные\nИстория: Реформы Петра I" if area == "college" else "Python: Циклы for\nGit: Ветки и merge"
    await cb.message.answer(
        f"Напиши тему (или сразу несколько — каждую с новой строки).\n"
        f"Формат: <code>Предмет: тема</code>\n\nНапример:\n<code>{example}</code>"
    )
    await cb.answer()


@router.message(StateFilter(AddTopic.text), UserText)
async def add_save(message: Message, state: FSMContext, db: Database, user):
    area = (await state.get_data())["area"]
    added = []
    for line in message.text.splitlines():
        line = line.strip(" -•\t")
        if not line:
            continue
        subject, sep, title = line.partition(":")
        if not sep or not title.strip():
            subject, title = DEFAULT_SUBJECT[area], line
        db.add_topic(user["user_id"], area, subject.strip(), title.strip(), today_for(user))
        added.append(title.strip())
    await state.clear()
    if not added:
        await message.answer("Не нашла ни одной темы 🤷")
        return
    text, kb = topic_list(db, user, area)
    await message.answer(f"➕ Добавила тем: {len(added)}")
    await message.answer(text, reply_markup=kb)


async def send_topic_of_day(message: Message, db: Database, user, after_id: int = 0) -> None:
    topic = db.next_todo(user["user_id"], after_id)
    if topic is None:
        await message.answer(
            "📭 Темы для изучения закончились. Добавь новые (📚 Учёба → ➕) "
            "или загрузи стартовый план (💻 IT-развитие → 🚀)."
        )
        return
    await message.answer("🎯 <b>Тема дня</b>\n\n" + render_lesson(topic["subject"], topic["title"]),
                         reply_markup=lesson_kb(topic["id"], ai.enabled()), disable_web_page_preview=True)


@router.callback_query(F.data == "st:today")
async def topic_of_day(cb: CallbackQuery, db: Database, user):
    await send_topic_of_day(cb.message, db, user)
    await cb.answer()


@router.callback_query(F.data.startswith("st:next:"))
async def next_topic(cb: CallbackQuery, db: Database, user):
    await send_topic_of_day(cb.message, db, user, after_id=int(cb.data.split(":")[2]))
    await cb.answer()


@router.callback_query(F.data.startswith("st:done:"))
async def lesson_done(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic is None or topic["status"] != "todo":
        await cb.answer("Уже отмечено")
        return
    db.mark_learned(user["user_id"], topic["id"], today_for(user))
    await cb.message.edit_reply_markup(reply_markup=inline([[("⏭ Следующая тема", f"st:next:{topic['id']}")]]))
    await cb.message.answer(f"✅ «{h(topic['title'])}» разобрана! Напомню повторить завтра 💪")
    await cb.answer()


async def _answer_ai(message: Message, text: str) -> None:
    try:
        await message.answer(text)
    except TelegramBadRequest:  # the model produced HTML Telegram can't parse
        await message.answer(text, parse_mode=None)


@router.callback_query(F.data.startswith("st:ai:"))
async def explain_more(cb: CallbackQuery, db: Database, user):
    topic = db.get_topic(user["user_id"], int(cb.data.split(":")[2]))
    if topic is None or not ai.enabled():
        await cb.answer("Нейросеть не подключена")
        return
    await cb.answer("Думаю… 🤖")
    await cb.message.answer("🤖 Готовлю подробное объяснение, это займёт до минуты…")
    answer = await ai.ask(
        "Объясни эту тему подробнее, чем короткий урок: простыми словами, с примером, "
        "типичными ошибками новичков и 3 задачами с ответами в конце.",
        f"{topic['subject']}: {topic['title']}",
    )
    await _answer_ai(cb.message, answer)


@router.callback_query(F.data.startswith("st:ask:"))
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
