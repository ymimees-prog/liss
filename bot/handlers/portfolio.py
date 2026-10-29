from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import market
from ..common import UserText, today_for
from ..db import Database
from ..keyboards import BTN_PORTFOLIO, grid, inline
from ..logic import build_positions, num, parse_numbers, signed
from ..market import ASSETS, MarketError, fmt_pct

router = Router()

CRYPTO = [code for code, a in ASSETS.items() if a.source == "cg"]


class PortfolioTx(StatesGroup):
    amount = State()


def positions(db: Database, user):
    return build_positions([(t["asset"], t["qty"], t["price"]) for t in db.portfolio_txs(user["user_id"])])


async def portfolio_summary(db: Database, user) -> tuple[str | None, float, float]:
    """(text block, total value $, unrealized PnL $); text is None when the portfolio is empty."""
    pos = {a: p for a, p in positions(db, user).items() if p.qty > 1e-12}
    realized = sum(p.realized for p in positions(db, user).values())
    if not pos and not realized:
        return None, 0.0, 0.0
    try:
        q = await market.quotes()
    except MarketError:
        q = {}
    lines, total, unreal = [], 0.0, 0.0
    for code, p in pos.items():
        price = q[code].usd if code in q and q[code].usd else None
        line = f"{ASSETS[code].name}: {num(p.qty)} шт, средняя {num(p.avg_price)} $"
        if price:
            value = p.qty * price
            pnl = value - p.cost
            total += value
            unreal += pnl
            pct = pnl / p.cost * 100 if p.cost else 0
            line += f"\n   сейчас {num(value)} $ · {signed(pnl, '$')} {fmt_pct(pct)}"
        lines.append(line)
    if realized:
        lines.append(f"\nЗафиксировано продажами: {signed(realized, '$')}")
    rub = q.get("USDT")
    total_line = f"\n💰 Всего: <b>{num(total)} $</b>" + (f" (~{num(total * rub.price)} ₽)" if rub else "")
    total_line += f"\nНереализованный результат: <b>{signed(unreal, '$')}</b>"
    return "\n".join(lines) + total_line, total, unreal


def portfolio_kb():
    return inline([[("➕ Купила", "pf:buy"), ("➖ Продала", "pf:sell")], [("🧾 История", "pf:hist")]])


@router.message(F.text == BTN_PORTFOLIO)
async def portfolio_home(message: Message, state: FSMContext, db: Database, user):
    await state.clear()
    text, _, _ = await portfolio_summary(db, user)
    if text is None:
        text = ("Портфель пуст. Нажми «➕ Купила», когда купишь монеты, — я буду считать их стоимость "
                "и твою прибыль/убыток по текущему курсу.\n\n<i>Тренируешься на демо? Можно вести и "
                "виртуальный портфель — просто записывай покупки.</i>")
    await message.answer("<b>💼 Портфель</b>\n\n" + text, reply_markup=portfolio_kb())


@router.callback_query(F.data.in_({"pf:buy", "pf:sell"}))
async def choose_asset(cb: CallbackQuery):
    kind = cb.data.split(":")[1]
    await cb.message.answer("Какую монету?", reply_markup=grid([(ASSETS[c].name, f"pf:{kind}:{c}") for c in CRYPTO]))
    await cb.answer()


@router.callback_query(F.data.regexp(r"^pf:(buy|sell):[A-Z]+$"))
async def ask_amount(cb: CallbackQuery, state: FSMContext, db: Database, user):
    _, kind, code = cb.data.split(":")
    if kind == "sell" and positions(db, user).get(code, None) is None:
        await cb.answer(f"{code} нет в портфеле", show_alert=True)
        return
    await state.set_state(PortfolioTx.amount)
    await state.update_data(kind=kind, asset=code)
    verb = "купила" if kind == "buy" else "продала"
    await cb.message.answer(
        f"Сколько {code} {verb} и по какой цене в $ за 1 монету?\n"
        f"Например: <code>0.01 95000</code>\n<i>Без цены — возьму текущий курс.</i>"
    )
    await cb.answer()


@router.message(StateFilter(PortfolioTx.amount), UserText)
async def save_tx(message: Message, state: FSMContext, db: Database, user):
    data = await state.get_data()
    nums = parse_numbers(message.text)
    if not nums or nums[0] <= 0:
        await message.answer("Напиши количество и цену: <code>0.01 95000</code>")
        return
    qty = nums[0]
    if len(nums) > 1:
        price = nums[1]
    else:
        try:
            price = (await market.quotes())[data["asset"]].usd
        except (MarketError, KeyError):
            price = None
        if not price:
            await message.answer("Не смогла узнать текущий курс — напиши цену сама: <code>0.01 95000</code>")
            return
    code = data["asset"]
    if data["kind"] == "sell":
        held = positions(db, user).get(code)
        if held is None or qty > held.qty + 1e-12:
            await message.answer(f"В портфеле только {num(held.qty if held else 0)} {code}. Напиши количество поменьше.")
            return
        qty = -qty
    await state.clear()
    db.add_portfolio_tx(user["user_id"], today_for(user), code, qty, price)
    verb = "Купила" if qty > 0 else "Продала"
    msg = f"✅ {verb} {num(abs(qty))} {code} по {num(price)} $ (на {num(abs(qty) * price)} $)"
    if qty < 0:
        p = positions(db, user)[code]
        msg += f"\nЗафиксированный результат по {code}: {signed(p.realized, '$')}"
    await message.answer(msg)
    text, _, _ = await portfolio_summary(db, user)
    if text:
        await message.answer("<b>💼 Портфель</b>\n\n" + text, reply_markup=portfolio_kb())


@router.callback_query(F.data == "pf:hist")
async def history(cb: CallbackQuery, db: Database, user):
    txs = db.portfolio_txs(user["user_id"])[-15:]
    await cb.answer()
    if not txs:
        await cb.message.answer("Записей пока нет.")
        return
    lines = ["<b>🧾 Последние операции</b> (нажми, чтобы удалить ошибочную)\n"]
    buttons = []
    for t in txs:
        label = f"{'➕' if t['qty'] > 0 else '➖'} {num(abs(t['qty']))} {t['asset']} по {num(t['price'])} $"
        lines.append(f"{t['day'][5:]} {label}")
        buttons.append((f"🗑 {label}", f"pf:del:{t['id']}"))
    await cb.message.answer("\n".join(lines), reply_markup=grid(buttons, width=1))


@router.callback_query(F.data.startswith("pf:del:"))
async def delete_tx(cb: CallbackQuery, db: Database, user):
    db.delete_portfolio_tx(user["user_id"], int(cb.data.split(":")[2]))
    await cb.answer("Удалено")
    await cb.message.edit_reply_markup(reply_markup=None)
