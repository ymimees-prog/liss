import asyncio
import time

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from .. import market
from ..common import UserText
from ..db import Database
from ..keyboards import BTN_MARKET, grid, inline
from ..market import ASSETS, MarketError, fmt_pct, fmt_price

router = Router()

PERIODS = {7: "неделю", 30: "месяц", 90: "3 месяца", 365: "год"}


class Alert(StatesGroup):
    price = State()


def market_kb():
    buttons = [(a.name, f"mk:a:{code}:30") for code, a in ASSETS.items()]
    return grid(buttons, width=2, extra=[("🔄 Обновить", "mk:home"), ("🔔 Мои уведомления", "mk:alerts")])


async def market_text() -> str:
    q = await market.quotes()
    lines = ["<b>📈 Рынок сейчас</b>\n"]
    for code in ASSETS:
        if code in q:
            lines.append(f"{q[code].asset.name}: <b>{fmt_price(q[code].price, q[code].asset.unit)}</b> "
                         f"{fmt_pct(q[code].change_pct)}")
    premium = market.usdt_premium(q)
    if premium:
        lines.append(f"\n💡 {premium}")
    lines.append("\n<i>Курсы ЦБ обновляются раз в день, крипта — постоянно (24 ч изменение).</i>\n"
                 "Нажми на актив — покажу график и разбор 👇")
    return "\n".join(lines)


@router.message(F.text == BTN_MARKET)
async def market_home(message: Message, state: FSMContext):
    await state.clear()
    try:
        text = await market_text()
    except MarketError as e:
        text = f"😔 {e}"
    await message.answer(text, reply_markup=market_kb())


@router.callback_query(F.data == "mk:home")
async def market_refresh(cb: CallbackQuery):
    await cb.answer("Обновляю…")
    try:
        text = await market_text()
    except MarketError as e:
        text = f"😔 {e}"
    await cb.message.answer(text, reply_markup=market_kb())


@router.callback_query(F.data.startswith("mk:a:"))
async def asset_view(cb: CallbackQuery):
    _, _, code, days = cb.data.split(":")
    asset, days = ASSETS[code], int(days)
    await cb.answer("Строю график…")
    try:
        points = await market.history(asset, days)
    except MarketError as e:
        await cb.message.answer(f"😔 {e}")
        return
    if len(points) < 2:
        await cb.message.answer("Пока мало данных для графика, попробуй период побольше.")
        return
    period = PERIODS[days]
    png = await asyncio.to_thread(market.chart_png, asset, points, period)
    await cb.message.answer_photo(BufferedInputFile(png, f"{code}.png"), caption=f"{asset.name} за {period}")
    other = [(f"📅 {name}", f"mk:a:{code}:{d}") for d, name in PERIODS.items() if d != days]
    await cb.message.answer(
        market.analyze(asset, points, period),
        reply_markup=grid(other, width=3, extra=[(f"🔔 Уведомить о цене {code}", f"mk:alert:{code}"),
                                                 ("⬅️ Все курсы", "mk:home")]),
    )


@router.callback_query(F.data.startswith("mk:alert:"))
async def alert_start(cb: CallbackQuery, state: FSMContext):
    code = cb.data.split(":")[2]
    await state.set_state(Alert.price)
    await state.update_data(asset=code)
    try:
        q = (await market.quotes()).get(code)
        now = f" Сейчас {fmt_price(q.price, q.asset.unit)}." if q else ""
    except MarketError:
        now = ""
    await cb.message.answer(f"🔔 При какой цене {code} написать тебе?{now}\nНапример: <code>100</code>")
    await cb.answer()


@router.message(StateFilter(Alert.price), UserText)
async def alert_save(message: Message, state: FSMContext, db: Database, user):
    try:
        target = float(message.text.replace(" ", "").replace(",", ".").rstrip("₽$"))
        assert target > 0
    except (ValueError, AssertionError):
        await message.answer("Напиши просто число, например <code>98.5</code>")
        return
    code = (await state.get_data())["asset"]
    await state.clear()
    asset = ASSETS[code]
    try:
        q = (await market.quotes()).get(code)
    except MarketError:
        q = None
    direction = "above" if q is None or target > q.price else "below"
    db.add_alert(user["user_id"], code, direction, target)
    word = "поднимется до" if direction == "above" else "опустится до"
    await message.answer(f"🔔 Готово! Напишу, когда {asset.name} {word} {fmt_price(target, asset.unit)}.\n"
                         "<i>Проверяю цены каждые несколько минут.</i>")


@router.callback_query(F.data == "mk:alerts")
async def alerts_list(cb: CallbackQuery, db: Database, user):
    rows = db.alerts(user["user_id"])
    await cb.answer()
    if not rows:
        await cb.message.answer("Уведомлений нет. Открой актив и нажми «🔔 Уведомить о цене».")
        return
    sign = {"above": "≥", "below": "≤"}
    items = [(f"🗑 {r['asset']} {sign[r['direction']]} {fmt_price(r['price'], ASSETS[r['asset']].unit)}",
              f"mk:adel:{r['id']}") for r in rows]
    await cb.message.answer("🔔 Твои уведомления (нажми, чтобы удалить):", reply_markup=grid(items, width=1))


@router.callback_query(F.data.startswith("mk:adel:"))
async def alert_delete(cb: CallbackQuery, db: Database, user):
    db.delete_alert(user["user_id"], int(cb.data.split(":")[2]))
    await cb.answer("Удалено")
    await cb.message.edit_reply_markup(reply_markup=None)


ALERT_CHECK_SECONDS = 120
_last_check = 0.0


async def check_alerts(bot: Bot, db: Database) -> None:
    """Sends and removes alerts whose target price was reached. Throttled to spare the free APIs."""
    global _last_check
    alerts = db.alerts()
    if not alerts or time.monotonic() - _last_check < ALERT_CHECK_SECONDS:
        return
    _last_check = time.monotonic()
    q = await market.quotes()
    for a in alerts:
        quote = q.get(a["asset"])
        if quote is None:
            continue
        hit = quote.price >= a["price"] if a["direction"] == "above" else quote.price <= a["price"]
        if hit:
            db.delete_alert(a["user_id"], a["id"])
            unit = quote.asset.unit
            await bot.send_message(
                a["user_id"],
                f"🔔 <b>{quote.asset.name}: {fmt_price(quote.price, unit)}</b>\n"
                f"Цена {'достигла' if a['direction'] == 'above' else 'опустилась до'} "
                f"{fmt_price(a['price'], unit)}, как ты просила.\n\n"
                "Действуй по своему торговому плану, а не на эмоциях 🧘‍♀️",
                reply_markup=inline([[("📈 Открыть график", f"mk:a:{a['asset']}:30")]]),
            )
