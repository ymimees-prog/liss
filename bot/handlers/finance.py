import re

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..common import UserText, h, month_start, today_for
from ..db import Database
from ..keyboards import BTN_MONEY, categories_kb, grid, money_menu
from ..logic import EXPENSE_CATEGORIES, budget_503020, finance_advice, money, parse_amount, progress_bar, random_tip

router = Router()


class Money(StatesGroup):
    expense = State()
    income = State()
    save = State()
    unsave = State()
    goal = State()


def money_text(db: Database, user) -> str:
    uid = user["user_id"]
    today = today_for(user)
    ms = month_start(today)
    income = db.tx_total(uid, "income", ms, today)
    spent = db.tx_total(uid, "expense", ms, today)
    saved_month = db.tx_total(uid, "saving", ms, today)
    savings = db.tx_total(uid, "saving")
    lines = [
        "<b>💰 Финансы</b>\n",
        f"За {today.strftime('%m.%Y')}:",
        f"➕ Доходы: {money(income)}",
        f"➖ Расходы: {money(spent)}",
        f"🐷 Отложено: {money(saved_month)}",
        f"💵 Свободно по записям: {money(income - spent - saved_month)}",
        f"\n🐷 Всего в копилке: <b>{money(savings)}</b>",
    ]
    if user["goal_amount"]:
        lines.append(f"🎯 {h(user['goal_name'])}: {money(savings)} из {money(user['goal_amount'])}")
        lines.append(progress_bar(savings, user["goal_amount"]))
    else:
        lines.append("🎯 Цель не задана — поставь её, так копить легче!")
    lines.append("\n<i>Записывай каждую трату — это главный навык финансовой грамотности.</i>")
    return "\n".join(lines)


@router.message(F.text == BTN_MONEY)
async def money_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    await message.answer(money_text(db, user), reply_markup=money_menu())


PROMPTS = {
    "expense": (Money.expense, "Сколько и на что потратила? Например: <code>350 кофе</code>"),
    "income": (Money.income, "Сколько и откуда пришло? Например: <code>5000 стипендия</code>"),
    "save": (Money.save, "Сколько кладёшь в копилку? Например: <code>1000</code>"),
    "unsave": (Money.unsave, "Сколько берёшь из копилки и зачем? Например: <code>500 подарок маме</code>"),
}


@router.callback_query(F.data.in_({f"fn:{k}" for k in PROMPTS}))
async def ask_amount(cb: CallbackQuery, state: FSMContext):
    st, prompt = PROMPTS[cb.data.split(":")[1]]
    await state.set_state(st)
    await cb.message.answer(prompt)
    await cb.answer()


async def _parse(message: Message) -> tuple[float, str] | None:
    parsed = parse_amount(message.text)
    if parsed is None:
        await message.answer("Не поняла сумму 🤔 Начни с числа: <code>350 кофе</code>")
    return parsed


@router.message(StateFilter(Money.expense), UserText)
async def expense_amount(message: Message, state: FSMContext):
    parsed = await _parse(message)
    if parsed is None:
        return
    await state.update_data(amount=parsed[0], note=parsed[1])
    await message.answer(f"➖ {money(parsed[0])} — какая категория?", reply_markup=categories_kb())


@router.callback_query(StateFilter(Money.expense), F.data.startswith("fn:cat:"))
async def expense_category(cb: CallbackQuery, state: FSMContext, db: Database, user):
    data = await state.get_data()
    if "amount" not in data:
        await cb.answer("Сначала напиши сумму")
        return
    cat = cb.data.split(":")[2]
    await state.clear()
    today = today_for(user)
    db.add_tx(user["user_id"], today, "expense", data["amount"], cat, data["note"] or None)
    today_spent = db.expenses_by_category(user["user_id"], today, today)
    await cb.message.edit_text(
        f"➖ {money(data['amount'])} · {EXPENSE_CATEGORIES[cat]}" + (f" · {h(data['note'])}" if data["note"] else "") +
        f"\n\nПотрачено сегодня: {money(sum(today_spent.values()))}"
    )
    await cb.answer()


@router.message(StateFilter(Money.income), UserText)
async def income_save(message: Message, state: FSMContext, db: Database, user):
    parsed = await _parse(message)
    if parsed is None:
        return
    await state.clear()
    amount, note = parsed
    db.add_tx(user["user_id"], today_for(user), "income", amount, None, note or None)
    plan = budget_503020(amount)
    await message.answer(
        f"➕ Записала доход {money(amount)} 🎉\n\n"
        f"💡 <b>Заплати сначала себе!</b> По правилу 50/30/20 из этой суммы:\n"
        f"• {money(plan['needs'])} — на необходимое\n"
        f"• {money(plan['wants'])} — на желания\n"
        f"• <b>{money(plan['savings'])} — сразу в копилку</b> 🐷",
        reply_markup=grid([(f"🐷 Отложить {money(plan['savings'])}", f"fn:quicksave:{plan['savings']:.2f}")]),
    )


@router.callback_query(F.data.startswith("fn:quicksave:"))
async def quick_save(cb: CallbackQuery, db: Database, user):
    amount = float(cb.data.split(":")[2])
    db.add_tx(user["user_id"], today_for(user), "saving", amount, None, "20% от дохода")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(f"🐷 +{money(amount)} в копилку. Всего: <b>{money(db.tx_total(user['user_id'], 'saving'))}</b>")
    await cb.answer("Умница!")


@router.message(StateFilter(Money.save, Money.unsave), UserText)
async def savings_save(message: Message, state: FSMContext, db: Database, user):
    parsed = await _parse(message)
    if parsed is None:
        return
    taking = await state.get_state() == Money.unsave.state
    await state.clear()
    amount, note = parsed
    uid = user["user_id"]
    if taking and amount > db.tx_total(uid, "saving"):
        await message.answer("В копилке столько нет 🙈")
        return
    db.add_tx(uid, today_for(user), "saving", -amount if taking else amount, None, note or None)
    total = db.tx_total(uid, "saving")
    msg = (f"💸 Взяла {money(amount)} из копилки." if taking else f"🐷 +{money(amount)} в копилку!")
    msg += f"\nВ копилке: <b>{money(total)}</b>"
    if user["goal_amount"]:
        msg += f"\n🎯 {h(user['goal_name'])}: {progress_bar(total, user['goal_amount'])}"
        if not taking and total >= user["goal_amount"]:
            msg += "\n\n🎉🎉🎉 ЦЕЛЬ ДОСТИГНУТА! Ты невероятная! Поставь новую 🎯"
    await message.answer(msg)


@router.callback_query(F.data == "fn:goal")
async def goal_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Money.goal)
    await cb.message.answer("На что копим и сколько нужно? Например: <code>Ноутбук для программирования 60000</code>")
    await cb.answer()


@router.message(StateFilter(Money.goal), UserText)
async def goal_save(message: Message, state: FSMContext, db: Database, user):
    m = re.match(r"^(.*?)\s*(\d+(?:[.,]\d+)?)\s*(?:₽|р\.?|руб\.?)?\s*$", message.text.strip(), re.IGNORECASE)
    if not m or float(m.group(2).replace(",", ".")) <= 0:
        await message.answer("Напиши название и сумму в конце: <code>Подушка безопасности 30000</code>")
        return
    await state.clear()
    name = m.group(1).strip() or "Моя цель"
    amount = float(m.group(2).replace(",", "."))
    db.update_user(user["user_id"], goal_name=name, goal_amount=amount)
    savings = db.tx_total(user["user_id"], "saving")
    per_week = max(amount - savings, 0) / 13  # ~90 days
    await message.answer(
        f"🎯 Цель: <b>{h(name)}</b> — {money(amount)}\n{progress_bar(savings, amount)}\n\n"
        f"Чтобы успеть за 90 дней, откладывай примерно <b>{money(per_week)}</b> в неделю."
    )


@router.callback_query(F.data == "fn:report")
async def report(cb: CallbackQuery, db: Database, user):
    uid = user["user_id"]
    today = today_for(user)
    ms = month_start(today)
    income = db.tx_total(uid, "income", ms, today)
    saved = db.tx_total(uid, "saving", ms, today)
    by_cat = db.expenses_by_category(uid, ms, today)
    spent = sum(by_cat.values())
    lines = [f"<b>📊 Отчёт за {today.strftime('%m.%Y')}</b>\n"]
    if by_cat:
        lines.append("<b>Расходы по категориям:</b>")
        for cat, s in by_cat.items():
            pct = s / spent * 100 if spent else 0
            lines.append(f"{EXPENSE_CATEGORIES.get(cat, cat)}: {money(s)} ({pct:.0f}%)")
        lines.append(f"\nВсего потрачено: <b>{money(spent)}</b>")
        lines.append(f"В среднем в день: {money(spent / today.day)}")
    else:
        lines.append("Расходов пока не записано.")
    advice = finance_advice(income, by_cat, saved)
    if advice:
        lines.append("\n<b>🧠 Что я вижу:</b>")
        lines += [f"• {a}" for a in advice]
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.callback_query(F.data == "fn:last")
async def last_records(cb: CallbackQuery, db: Database, user):
    rows = db.last_tx(user["user_id"])
    if not rows:
        await cb.message.answer("Записей пока нет.")
        await cb.answer()
        return
    icon = {"income": "➕", "expense": "➖", "saving": "🐷"}
    lines = ["<b>🧾 Последние записи</b> (нажми, чтобы удалить ошибочную)\n"]
    buttons = []
    for r in rows:
        label = f"{icon[r['kind']]} {money(r['amount'])} {EXPENSE_CATEGORIES.get(r['category'], '') if r['category'] else ''} {r['note'] or ''}".strip()
        lines.append(f"{r['day'][5:]} {h(label)}")
        buttons.append((f"🗑 {label[:40]}", f"fn:del:{r['id']}"))
    await cb.message.answer("\n".join(lines), reply_markup=grid(buttons, width=1))
    await cb.answer()


@router.callback_query(F.data.startswith("fn:del:"))
async def delete_record(cb: CallbackQuery, db: Database, user):
    db.delete_tx(user["user_id"], int(cb.data.split(":")[2]))
    await cb.answer("Удалено")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer("🗑 Запись удалена.")


@router.callback_query(F.data == "fn:tip")
async def tip(cb: CallbackQuery):
    await cb.message.answer(f"💡 {random_tip()}")
    await cb.answer()
