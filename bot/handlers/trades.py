from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import market
from ..common import UserText, h, today_for
from ..db import Database
from ..keyboards import BTN_CALC, BTN_TRADES, grid, inline, skip_kb
from ..logic import (journal_stats, num, parse_numbers, pct, position_size, reward_risk, signed, stop_is_valid,
                     trade_pnl, trade_risk)
from ..market import ASSETS, MarketError

router = Router()

CRYPTO = [code for code, a in ASSETS.items() if a.source == "cg"]
SIDE = {"long": "🟢 Лонг (на рост)", "short": "🔴 Шорт (на падение)"}


class NewTrade(StatesGroup):
    numbers = State()
    reason = State()


class CloseTrade(StatesGroup):
    price = State()
    lesson = State()


class Calc(StatesGroup):
    numbers = State()


def fmt_r(r: float) -> str:
    return f"{r:+.1f}R".replace(".", ",")


def unit(code: str) -> str:
    return ASSETS[code].unit


def trade_line(t, price: float | None = None) -> str:
    u = unit(t["asset"])
    tag = "демо" if t["demo"] else "реал"
    line = (f"#{t['id']} {t['asset']} {'🟢 лонг' if t['side'] == 'long' else '🔴 шорт'} ({tag}): "
            f"вход {num(t['entry'])}, стоп {num(t['stop'])}" + (f", цель {num(t['take'])}" if t["take"] else ""))
    if price is not None:
        pnl = trade_pnl(t["side"], t["entry"], price, t["qty"])
        risk = trade_risk(t["entry"], t["stop"], t["qty"])
        r = f" ({fmt_r(pnl / risk)})" if risk else ""
        line += f"\n   сейчас {num(price)} {u} → {signed(pnl, u)}{r}"
    return line


async def open_trades_text(db: Database, user) -> str | None:
    trades = db.open_trades(user["user_id"])
    if not trades:
        return None
    try:
        q = await market.quotes()
    except MarketError:
        q = {}
    return "\n".join(trade_line(t, q[t["asset"]].price if t["asset"] in q else None) for t in trades)


def trades_kb(has_open: bool):
    rows = [[("➕ Новая сделка", "tr:new")]]
    if has_open:
        rows[0].append(("✅ Закрыть", "tr:close"))
    rows.append([("📊 Статистика", "tr:stats"), ("🧾 Закрытые", "tr:closed")])
    return inline(rows)


@router.message(F.text == BTN_TRADES)
async def trades_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    text = await open_trades_text(db, user)
    body = f"<b>Открытые сделки:</b>\n{text}" if text else (
        "Открытых сделок нет.\n\n<i>Записывай каждую сделку — и демо, и реальную: вход, стоп, цель и причину. "
        "Через 20–30 сделок статистика покажет, работает ли твоя система.</i>")
    await message.answer("<b>📓 Дневник сделок</b>\n\n" + body, reply_markup=trades_kb(bool(text)))


@router.callback_query(F.data == "tr:new")
async def new_asset(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.answer("Какая монета?", reply_markup=grid([(ASSETS[c].name, f"tr:a:{c}") for c in CRYPTO]))
    await cb.answer()


@router.callback_query(F.data.startswith("tr:a:"))
async def new_side(cb: CallbackQuery, state: FSMContext):
    await state.update_data(asset=cb.data.split(":")[2])
    await cb.message.answer("Направление?", reply_markup=inline([[(v, f"tr:s:{k}")] for k, v in SIDE.items()]))
    await cb.answer()


@router.callback_query(F.data.startswith("tr:s:"))
async def new_demo(cb: CallbackQuery, state: FSMContext):
    await state.update_data(side=cb.data.split(":")[2])
    await cb.message.answer("Это демо или реальные деньги?",
                            reply_markup=inline([[("🎮 Демо", "tr:d:1"), ("💵 Реальная", "tr:d:0")]]))
    await cb.answer()


@router.callback_query(F.data.startswith("tr:d:"))
async def new_numbers(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "asset" not in data or "side" not in data:
        await cb.answer("Начни заново: 📓 Сделки → ➕ Новая сделка")
        return
    await state.update_data(demo=cb.data.endswith("1"))
    await state.set_state(NewTrade.numbers)
    u = unit(data["asset"])
    await cb.message.answer(
        f"Напиши через пробел (цены в {u}):\n<b>вход стоп цель количество</b>\n"
        "Например: <code>95000 93000 99000 0.01</code>\n"
        "<i>Без цели — три числа: вход стоп количество.</i>"
    )
    await cb.answer()


@router.message(StateFilter(NewTrade.numbers), UserText)
async def new_validate(message: Message, state: FSMContext):
    data = await state.get_data()
    nums = parse_numbers(message.text)
    if len(nums) == 3:
        entry, stop, qty = nums
        take = None
    elif len(nums) == 4:
        entry, stop, take, qty = nums
    else:
        await message.answer("Нужно 3 или 4 числа: <code>вход стоп цель количество</code>")
        return
    if min(entry, stop, qty) <= 0:
        await message.answer("Числа должны быть больше нуля.")
        return
    if not stop_is_valid(data["side"], entry, stop):
        where = "ниже" if data["side"] == "long" else "выше"
        await message.answer(f"Для {'лонга' if data['side'] == 'long' else 'шорта'} стоп должен быть {where} входа. "
                             "Проверь числа 🙂")
        return
    await state.update_data(entry=entry, stop=stop, take=take, qty=qty)
    await state.set_state(NewTrade.reason)
    await message.answer("Почему входишь? Одной фразой: какой сигнал, какой план.\n"
                         "<i>Потом это лучший учитель.</i>", reply_markup=skip_kb("tr:noreason"))


async def _open(message: Message, state: FSMContext, db: Database, user, reason: str | None):
    d = await state.get_data()
    await state.clear()
    if "entry" not in d:
        return
    tid = db.open_trade(user["user_id"], today_for(user), d["asset"], d["side"], d["demo"],
                        d["entry"], d["stop"], d["take"], d["qty"], reason)
    u = unit(d["asset"])
    risk = trade_risk(d["entry"], d["stop"], d["qty"])
    lines = [f"📓 Сделка #{tid} записана: {d['asset']} {SIDE[d['side']]}, {'демо' if d['demo'] else 'реал'}",
             f"Позиция: {num(d['qty'])} × {num(d['entry'])} = {num(d['qty'] * d['entry'])} {u}",
             f"Риск до стопа: <b>{num(risk)} {u}</b> ({pct(abs(d['entry'] - d['stop']) / d['entry'] * 100)} от цены)"]
    if d["take"]:
        rr = reward_risk(d["entry"], d["stop"], d["take"])
        lines.append(f"Цель даст: {num(trade_pnl(d['side'], d['entry'], d['take'], d['qty']))} {u} · "
                     f"соотношение прибыль/риск 1:{num(rr)}")
        if rr < 1.5:
            lines.append("⚠️ Прибыль меньше чем в 1,5 раза больше риска — такие сделки трудно сделать прибыльными.")
    lines.append("\n💡 Проверь в 🧮 Калькуляторе, что риск не больше 1–2% депозита.")
    await message.answer("\n".join(lines))


@router.message(StateFilter(NewTrade.reason), UserText)
async def new_reason(message: Message, state: FSMContext, db: Database, user):
    await _open(message, state, db, user, message.text.strip())


@router.callback_query(F.data == "tr:noreason")
async def new_no_reason(cb: CallbackQuery, state: FSMContext, db: Database, user):
    await _open(cb.message, state, db, user, None)
    await cb.answer()


@router.callback_query(F.data == "tr:close")
async def close_choose(cb: CallbackQuery, db: Database, user):
    trades = db.open_trades(user["user_id"])
    await cb.message.answer("Какую сделку закрываешь?", reply_markup=grid(
        [(f"#{t['id']} {t['asset']} {'лонг' if t['side'] == 'long' else 'шорт'} от {num(t['entry'])}", f"tr:c:{t['id']}")
         for t in trades], width=1))
    await cb.answer()


@router.callback_query(F.data.startswith("tr:c:"))
async def close_ask_price(cb: CallbackQuery, state: FSMContext, db: Database, user):
    t = db.get_trade(user["user_id"], int(cb.data.split(":")[2]))
    if t is None or t["exit"] is not None:
        await cb.answer("Уже закрыта")
        return
    await state.set_state(CloseTrade.price)
    await state.update_data(trade_id=t["id"])
    buttons = [[("🎯 По цели", f"tr:cp:{t['take']}")]] if t["take"] else []
    buttons.append([("🛑 По стопу", f"tr:cp:{t['stop']}"), ("📈 По текущей", "tr:cp:now")])
    await cb.message.answer(f"По какой цене закрыла #{t['id']} {t['asset']}? Напиши число или нажми кнопку.",
                            reply_markup=inline(buttons))
    await cb.answer()


async def _close(message: Message, state: FSMContext, db: Database, user, price: float):
    trade_id = (await state.get_data()).get("trade_id")
    t = db.get_trade(user["user_id"], trade_id) if trade_id else None
    if t is None or t["exit"] is not None:
        await state.clear()
        return
    db.close_trade(user["user_id"], t["id"], price, today_for(user))
    u = unit(t["asset"])
    pnl = trade_pnl(t["side"], t["entry"], price, t["qty"])
    risk = trade_risk(t["entry"], t["stop"], t["qty"])
    r = pnl / risk if risk else 0
    if pnl > 0:
        verdict = "🎉 Прибыль! Главное — ты действовала по плану?"
    elif r >= -1.05:
        verdict = "🛑 Убыток в пределах стопа — это нормальная часть трейдинга. Ты защитила депозит 💪"
    else:
        verdict = "⚠️ Убыток больше запланированного риска. Стоп был сдвинут или не поставлен? Запиши, что случилось."
    await state.set_state(CloseTrade.lesson)
    await message.answer(
        f"✅ #{t['id']} {t['asset']} закрыта по {num(price)} {u}\nРезультат: <b>{signed(pnl, u)}</b> "
        f"({fmt_r(r)})\n{verdict}\n\nЧто поняла по этой сделке? Какие были эмоции?",
        reply_markup=skip_kb("tr:nolesson"),
    )


@router.callback_query(StateFilter(CloseTrade.price), F.data.startswith("tr:cp:"))
async def close_by_button(cb: CallbackQuery, state: FSMContext, db: Database, user):
    value = cb.data.split(":", 2)[2]
    if value == "now":
        trade = db.get_trade(user["user_id"], (await state.get_data())["trade_id"])
        try:
            price = (await market.quotes())[trade["asset"]].price
        except (MarketError, KeyError):
            await cb.answer("Не смогла узнать курс — напиши цену числом", show_alert=True)
            return
    else:
        price = float(value)
    await _close(cb.message, state, db, user, price)
    await cb.answer()


@router.message(StateFilter(CloseTrade.price), UserText)
async def close_by_text(message: Message, state: FSMContext, db: Database, user):
    nums = parse_numbers(message.text)
    if not nums or nums[0] <= 0:
        await message.answer("Напиши цену выхода числом, например <code>96500</code>")
        return
    await _close(message, state, db, user, nums[0])


@router.message(StateFilter(CloseTrade.lesson), UserText)
async def close_lesson(message: Message, state: FSMContext, db: Database, user):
    trade_id = (await state.get_data()).get("trade_id")
    await state.clear()
    db.set_trade_lesson(user["user_id"], trade_id, message.text.strip())
    await message.answer("📝 Записала. Перечитывай свои выводы раз в неделю — так растёт трейдер.")


@router.callback_query(F.data == "tr:nolesson")
async def close_no_lesson(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Ок")


def stats_block(title: str, trades) -> str:
    if not trades:
        return f"<b>{title}</b>: сделок пока нет"
    by_unit: dict[str, list[tuple[float, float]]] = {}
    for t in trades:
        by_unit.setdefault(unit(t["asset"]), []).append(
            (trade_pnl(t["side"], t["entry"], t["exit"], t["qty"]), trade_risk(t["entry"], t["stop"], t["qty"])))
    all_closed = [x for v in by_unit.values() for x in v]
    s = journal_stats(all_closed)
    pf = "∞" if s["profit_factor"] == float("inf") else num(s["profit_factor"])
    lines = [f"<b>{title}</b>: {s['count']} сделок",
             f"Прибыльных: {s['winrate']:.0f}%",
             f"Средний результат: {fmt_r(s['avg_r'])} на сделку",
             f"Профит-фактор: {pf} (прибыль ÷ убытки; больше 1 — система в плюсе)"]
    lines += [f"Итого: {signed(sum(p for p, _ in v), u)}" for u, v in by_unit.items()]
    if s["count"] >= 10:
        if s["avg_r"] > 0:
            lines.append("✅ Система в плюсе — продолжай, соблюдая риск.")
        else:
            lines.append("⚠️ В среднем сделки убыточны — перечитай выводы в закрытых сделках и поправь план.")
    else:
        lines.append(f"<i>Для выводов нужно хотя бы 10–30 сделок, сейчас {s['count']}.</i>")
    return "\n".join(lines)


@router.callback_query(F.data == "tr:stats")
async def stats(cb: CallbackQuery, db: Database, user):
    uid = user["user_id"]
    text = "<b>📊 Статистика</b>\n\n" + stats_block("🎮 Демо", db.closed_trades(uid, True)) + "\n\n" + \
        stats_block("💵 Реальные", db.closed_trades(uid, False))
    text += "\n\n<i>R — результат в единицах риска: +2R значит заработала вдвое больше, чем рисковала.</i>"
    await cb.message.answer(text)
    await cb.answer()


@router.callback_query(F.data == "tr:closed")
async def closed(cb: CallbackQuery, db: Database, user):
    trades = db.closed_trades(user["user_id"])[-10:]
    await cb.answer()
    if not trades:
        await cb.message.answer("Закрытых сделок пока нет.")
        return
    lines = ["<b>🧾 Последние закрытые сделки</b>\n"]
    for t in reversed(trades):
        u = unit(t["asset"])
        pnl = trade_pnl(t["side"], t["entry"], t["exit"], t["qty"])
        lines.append(f"{t['closed_on'][5:]} #{t['id']} {t['asset']} {'лонг' if t['side'] == 'long' else 'шорт'}"
                     f"{' (демо)' if t['demo'] else ''}: {signed(pnl, u)}")
        if t["reason"]:
            lines.append(f"   💭 {h(t['reason'])}")
        if t["lesson"]:
            lines.append(f"   📝 {h(t['lesson'])}")
    await cb.message.answer("\n".join(lines), reply_markup=grid(
        [(f"🗑 Удалить #{t['id']}", f"tr:del:{t['id']}") for t in reversed(trades)], width=3))


@router.callback_query(F.data.startswith("tr:del:"))
async def delete(cb: CallbackQuery, db: Database, user):
    db.delete_trade(user["user_id"], int(cb.data.split(":")[2]))
    await cb.answer("Удалено")


# ---------------- position size calculator ----------------

CALC_HELP = (
    "<b>🧮 Калькулятор позиции</b>\n\n"
    "Скажу, сколько купить, чтобы при срабатывании стопа потерять не больше выбранного % депозита.\n\n"
    "Напиши через пробел: <b>депозит риск% вход стоп</b>\n"
    "Например: <code>1000 1 95000 93000</code>"
)


@router.message(F.text == BTN_CALC)
async def calc_start(message: Message, state: FSMContext):
    await state.set_state(Calc.numbers)
    await message.answer(CALC_HELP)


@router.message(StateFilter(Calc.numbers), UserText)
async def calc(message: Message, state: FSMContext):
    nums = parse_numbers(message.text)
    if len(nums) != 4 or min(nums) <= 0 or nums[2] == nums[3]:
        await message.answer("Нужно 4 числа: <code>депозит риск% вход стоп</code>, например <code>1000 1 95000 93000</code>")
        return
    deposit, risk_pct, entry, stop = nums
    r = position_size(deposit, risk_pct, entry, stop)
    side = "лонг" if stop < entry else "шорт"
    lines = [
        f"<b>🧮 Расчёт ({side})</b>\n",
        f"Риск: {num(risk_pct)}% депозита = <b>{num(r['risk'])}</b>",
        f"Стоп в {pct(r['stop_pct'])} от входа",
        f"Купить: <b>{num(r['qty'])}</b> монет на {num(r['value'])}",
    ]
    if r["leverage"] > 1:
        lines.append(f"⚠️ Это больше депозита — нужно плечо x{num(r['leverage'])}. Лучше поставь стоп дальше "
                     "или возьми меньше риска. Новичкам — без плеча.")
    else:
        lines.append(f"Это {r['leverage'] * 100:.0f}% депозита, плечо не нужно 👍")
    if risk_pct > 2:
        lines.append("⚠️ Риск больше 2% на сделку — серия из 5 стопов съест 10%+ депозита.")
    lines.append("\nМожешь сразу посчитать ещё — просто пришли новые 4 числа. Выйти — любая кнопка меню.")
    await message.answer("\n".join(lines))
