"""The daily summary: market, open trades, portfolio, learning — on demand and every morning."""
from . import market
from .common import today_for
from .db import Database
from .handlers.portfolio import portfolio_summary
from .handlers.trades import open_trades_text
from .logic import num, random_tip, signed
from .market import MarketError, fmt_pct, fmt_price

DIGEST_ASSETS = ("USD", "USDT", "BTC", "ETH", "TON")


async def build_digest(db: Database, user) -> str:
    today = today_for(user)
    lines = [f"<b>☀️ Сводка на {today.strftime('%d.%m')}</b>\n"]
    try:
        q = await market.quotes()
        for code in DIGEST_ASSETS:
            if code in q:
                lines.append(f"{q[code].asset.name}: <b>{fmt_price(q[code].price, q[code].asset.unit)}</b> "
                             f"{fmt_pct(q[code].change_pct)}")
        premium = market.usdt_premium(q)
        if premium:
            lines.append(f"💡 {premium}")
    except MarketError as e:
        lines.append(f"😔 {e}")

    trades = await open_trades_text(db, user)
    if trades:
        lines.append(f"\n<b>📓 Открытые сделки</b>\n{trades}")

    portfolio, total, unreal = await portfolio_summary(db, user)
    if portfolio and total:
        lines.append(f"\n<b>💼 Портфель</b>: {num(total)} $ ({signed(unreal, '$')})")

    due = len(db.due_reviews(user["user_id"], today))
    if due:
        lines.append(f"\n🔁 Повторить тем: <b>{due}</b> (🎓 Обучение → Повторить)")
    lines.append(f"\n💬 <i>{random_tip()}</i>")
    return "\n".join(lines)
