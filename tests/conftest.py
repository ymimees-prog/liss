"""Sample responses from the CBR and CoinGecko APIs and a fixture that serves them instead of the network."""
from datetime import date, datetime, timedelta, timezone

import pytest

from bot import market

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
    "solana": {"rub": 15000, "usd": 160.0, "rub_24h_change": 1.0, "usd_24h_change": 1.1},
    "binancecoin": {"rub": 60000, "usd": 640.0, "rub_24h_change": 0.5, "usd_24h_change": 0.4},
    "ripple": {"rub": 200, "usd": 2.1, "rub_24h_change": -0.5, "usd_24h_change": -0.4},
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


@pytest.fixture(autouse=True)
def _clear_market_cache():
    market._cache.clear()
