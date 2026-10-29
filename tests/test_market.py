import asyncio
from datetime import date

import pytest

from bot import market
from bot.db import Database
from bot.handlers.market import check_alerts
from bot.market import ASSETS
from tests.conftest import CBR_DAILY, CBR_DYNAMIC, CG_SIMPLE, cg_chart

def test_parsers():
    cbr = market.parse_cbr_daily(CBR_DAILY)
    assert cbr["CNY"] == (13.1, 13.0)  # divided by nominal
    points = market.parse_cbr_dynamic(CBR_DYNAMIC)
    assert points[0] == (date(2026, 10, 1), 90.0) and len(points) == 28
    closes = market.daily_closes(market.parse_cg_chart(cg_chart(3)))
    assert [d for d, _ in closes] == [date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3)]


def test_indicators():
    assert market.rsi([float(i) for i in range(20)]) == 100.0
    assert market.rsi([float(20 - i) for i in range(20)]) == 0.0
    assert market.sma([1, 2, 3, 4], 2) == 3.5
    assert market.fmt_price(95000, "$") == "95 000 $"
    assert market.fmt_price(97.4, "₽") == "97,40 ₽"


def test_quotes_and_analysis(fake_api):
    q = asyncio.run(market.quotes())
    assert set(q) == set(ASSETS)
    assert round(q["USD"].change_pct, 2) == 0.53
    assert "USDT дороже официального доллара на 2,0%" == market.usdt_premium(q)

    points = asyncio.run(market.history(ASSETS["USD"], 30))
    text = market.analyze(ASSETS["USD"], points, "месяц")
    assert "восходящий" in text and "RSI(14): 100" in text and "перекупленность" in text
    png = market.chart_png(ASSETS["USD"], points, "месяц")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    btc = asyncio.run(market.history(ASSETS["BTC"], 7))
    assert len(btc) == 7
    assert "Разбор" in market.analyze(ASSETS["BTC"], btc, "неделю")


def test_market_screens_and_alerts(fake_api):
    from tests.test_bot_flow import Harness, UID

    async def scenario():
        h = Harness()
        await h.text("/start")
        out = await h.text("📈 Рынок")
        assert "Solana" in out
        assert "USDT" in out and "97,40 ₽" in out and "дороже официального" in out
        out = await h.click("mk:a:USD:30")
        assert "Разбор" in out
        assert any(type(m).__name__ == "SendPhoto" for m in h.session.methods)

        await h.click("mk:alert:USDT")
        assert "поднимется до" in await h.text("100")
        await h.click("mk:alert:BTC")
        assert "опустится до" in await h.text("90 000")
        assert len(h.db.alerts(UID)) == 2

        CG_SIMPLE["tether"]["rub"] = 100.5  # USDT crosses 100
        market._cache.clear()
        h.session.sent.clear()
        await check_alerts(h.bot, h.db)
        assert any("USDT" in m and "достигла" in m for m in h.session.sent)
        assert [a["asset"] for a in h.db.alerts(UID)] == ["BTC"]

    import bot.handlers.market as mh
    mh._last_check = 0.0
    try:
        asyncio.run(scenario())
    finally:
        CG_SIMPLE["tether"]["rub"] = 97.4


def test_market_down_is_friendly(monkeypatch):
    async def broken(*a, **kw):
        raise market.MarketError("Не получилось загрузить курсы.")

    monkeypatch.setattr(market, "_get", broken)
    with pytest.raises(market.MarketError):
        asyncio.run(market.quotes())
    db = Database(":memory:")
    asyncio.run(check_alerts(None, db))  # no alerts -> no requests, no error
