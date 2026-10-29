import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from bot import market
from bot.db import Database
from bot.handlers.market import check_alerts
from bot.market import ASSETS

CBR_DAILY = {
    "Date": "2026-10-29T11:30:00+03:00",
    "Valute": {
        "USD": {"CharCode": "USD", "Nominal": 1, "Value": 95.5, "Previous": 95.0},
        "EUR": {"CharCode": "EUR", "Nominal": 1, "Value": 103.2, "Previous": 103.4},
        "CNY": {"CharCode": "CNY", "Nominal": 10, "Value": 131.0, "Previous": 130.0},
    },
}
CG_SIMPLE = {
    "tether": {"rub": 97.4, "usd": 1.0, "rub_24h_change": 0.8, "usd_24h_change": 0.0},
    "bitcoin": {"rub": 9_000_000, "usd": 95000.0, "rub_24h_change": -1.0, "usd_24h_change": -1.2},
    "ethereum": {"rub": 300_000, "usd": 3200.5, "rub_24h_change": 2.0, "usd_24h_change": 2.1},
    "the-open-network": {"rub": 500, "usd": 5.25, "rub_24h_change": 0.0, "usd_24h_change": 0.01},
}
CBR_DYNAMIC = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs ID="R01235" DateRange1="01.10.2026" DateRange2="29.10.2026" name="Foreign Currency Market Dynamic">
""" + "\n".join(
    f'<Record Date="{(date(2026, 10, 1) + timedelta(days=i)):%d.%m.%Y}" Id="R01235"><Nominal>1</Nominal>'
    f'<Value>{f"{90 + i * 0.2:.4f}".replace(".", ",")}</Value></Record>' for i in range(28)
) + "\n</ValCurs>"


def cg_chart(days: int) -> dict:
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    # hourly points, price slowly going up with a wiggle
    return {"prices": [[(start + timedelta(hours=h)).timestamp() * 1000, 95 + h * 0.01 + (h % 5) * 0.1]
                       for h in range(days * 24)]}


@pytest.fixture
def fake_api(monkeypatch):
    calls = []

    async def fake_get(url, params=None, as_text=False):
        calls.append(url)
        if url == market.CBR_DAILY_URL:
            return CBR_DAILY
        if url == market.CBR_DYNAMIC_URL:
            assert as_text and params["VAL_NM_RQ"]
            return CBR_DYNAMIC
        if url.endswith("/simple/price"):
            return CG_SIMPLE
        if "/market_chart" in url:
            return cg_chart(int(params["days"]))
        raise AssertionError(url)

    monkeypatch.setattr(market, "_get", fake_get)
    return calls


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
