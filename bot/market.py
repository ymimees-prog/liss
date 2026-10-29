"""Market data (CBR for fiat, CoinGecko for crypto), quick technical analysis and charts."""
import io
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev

import aiohttp

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Asset:
    code: str
    name: str
    source: str        # 'cbr' | 'cg'
    source_id: str     # CBR currency id / CoinGecko coin id
    quote: str         # 'rub' | 'usd'

    @property
    def unit(self) -> str:
        return "₽" if self.quote == "rub" else "$"


ASSETS: dict[str, Asset] = {a.code: a for a in [
    Asset("USD", "🇺🇸 Доллар (ЦБ)", "cbr", "R01235", "rub"),
    Asset("EUR", "🇪🇺 Евро (ЦБ)", "cbr", "R01239", "rub"),
    Asset("CNY", "🇨🇳 Юань (ЦБ)", "cbr", "R01375", "rub"),
    Asset("USDT", "💵 USDT", "cg", "tether", "rub"),
    Asset("BTC", "₿ Биткоин", "cg", "bitcoin", "usd"),
    Asset("ETH", "◆ Эфир", "cg", "ethereum", "usd"),
    Asset("TON", "💎 TON", "cg", "the-open-network", "usd"),
]}

CG_URL = "https://api.coingecko.com/api/v3"
CBR_DAILY_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
CBR_DYNAMIC_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"

DISCLAIMER = "⚠️ Это автоматический разбор по формулам, а не совет покупать или продавать."


class MarketError(Exception):
    pass


# ---------------- fetching ----------------

_cache: dict[str, tuple[float, object]] = {}
CACHE_SECONDS = 60


async def _get(url: str, params: dict | None = None, as_text: bool = False):
    key = url + repr(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    headers = {"User-Agent": "akia-bot/1.0"}
    if os.environ.get("COINGECKO_API_KEY") and url.startswith(CG_URL):
        headers["x-cg-demo-api-key"] = os.environ["COINGECKO_API_KEY"]
    proxy = os.environ.get("TELEGRAM_PROXY")  # same outgoing proxy as Telegram on free hosting
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url, params=params, headers=headers, proxy=proxy) as r:
                if r.status == 429:
                    raise MarketError("Сервис курсов просит подождать минутку (лимит запросов).")
                r.raise_for_status()
                data = await r.text(encoding="windows-1251" if url == CBR_DYNAMIC_URL else None) if as_text \
                    else await r.json(content_type=None)
    except MarketError:
        raise
    except Exception as e:
        log.warning("market request failed %s: %r", url, e)
        raise MarketError("Не получилось загрузить курсы. Проверь интернет или попробуй позже.") from e
    _cache[key] = (time.monotonic(), data)
    return data


def parse_cbr_daily(data: dict) -> dict[str, tuple[float, float]]:
    """{'USD': (value, previous)} per 1 unit of currency."""
    out = {}
    for code, v in data.get("Valute", {}).items():
        nominal = v.get("Nominal", 1) or 1
        out[code] = (v["Value"] / nominal, v["Previous"] / nominal)
    return out


def parse_cbr_dynamic(xml_text: str) -> list[tuple[date, float]]:
    root = ET.fromstring(xml_text.encode("windows-1251") if xml_text.lstrip().startswith("<?xml") else xml_text)
    points = []
    for rec in root.findall("Record"):
        d = datetime.strptime(rec.get("Date"), "%d.%m.%Y").date()
        nominal = float(rec.findtext("Nominal", "1").replace(",", "."))
        points.append((d, float(rec.findtext("Value").replace(",", ".")) / nominal))
    return points


def parse_cg_chart(data: dict) -> list[tuple[datetime, float]]:
    return [(datetime.fromtimestamp(ms / 1000, tz=timezone.utc), float(p)) for ms, p in data.get("prices", [])]


@dataclass
class Quote:
    asset: Asset
    price: float
    change_pct: float | None  # vs previous CBR day / last 24h


async def quotes() -> dict[str, Quote]:
    """Current prices for all assets. Partial results if one source is down."""
    result: dict[str, Quote] = {}
    errors = []
    try:
        cbr = parse_cbr_daily(await _get(CBR_DAILY_URL))
        for a in ASSETS.values():
            if a.source == "cbr" and a.code in cbr:
                value, prev = cbr[a.code]
                result[a.code] = Quote(a, value, (value / prev - 1) * 100 if prev else None)
    except MarketError as e:
        errors.append(e)
    cg_assets = [a for a in ASSETS.values() if a.source == "cg"]
    try:
        data = await _get(f"{CG_URL}/simple/price", {
            "ids": ",".join(a.source_id for a in cg_assets),
            "vs_currencies": "rub,usd",
            "include_24hr_change": "true",
        })
        for a in cg_assets:
            row = data.get(a.source_id, {})
            if a.quote in row:
                result[a.code] = Quote(a, float(row[a.quote]), row.get(f"{a.quote}_24h_change"))
    except MarketError as e:
        errors.append(e)
    if not result and errors:
        raise errors[0]
    return result


async def history(asset: Asset, days: int) -> list[tuple[date, float]]:
    """Daily closing prices for the last `days` days."""
    if asset.source == "cbr":
        today = date.today()
        text = await _get(CBR_DYNAMIC_URL, {
            "date_req1": (today - timedelta(days=days)).strftime("%d/%m/%Y"),
            "date_req2": today.strftime("%d/%m/%Y"),
            "VAL_NM_RQ": asset.source_id,
        }, as_text=True)
        return parse_cbr_dynamic(text)
    data = await _get(f"{CG_URL}/coins/{asset.source_id}/market_chart",
                      {"vs_currency": asset.quote, "days": str(days)})
    return daily_closes(parse_cg_chart(data))


def daily_closes(points: list[tuple[datetime, float]]) -> list[tuple[date, float]]:
    by_day: dict[date, float] = {}
    for t, p in points:
        by_day[t.date()] = p  # points are chronological, so the last one of the day wins
    return sorted(by_day.items())


# ---------------- analysis ----------------

def sma(values: list[float], n: int) -> float | None:
    return mean(values[-n:]) if len(values) >= n else None


def rsi(values: list[float], n: int = 14) -> float | None:
    if len(values) <= n:
        return None
    deltas = [b - a for a, b in zip(values[-n - 1:-1], values[-n:])]
    gains = sum(d for d in deltas if d > 0) / n
    losses = -sum(d for d in deltas if d < 0) / n
    if losses == 0:
        return 100.0
    return 100 - 100 / (1 + gains / losses)


def fmt_price(x: float, unit: str) -> str:
    if x >= 1000:
        s = f"{x:,.0f}".replace(",", " ")
    elif x >= 10:
        s = f"{x:.2f}"
    else:
        s = f"{x:.4f}"
    return f"{s.replace('.', ',')} {unit}"


def fmt_pct(x: float | None) -> str:
    if x is None:
        return ""
    arrow = "🟢" if x > 0.05 else "🔴" if x < -0.05 else "⚪️"
    return f"{arrow} {x:+.2f}%".replace(".", ",")


def analyze(asset: Asset, points: list[tuple[date, float]], period_name: str) -> str:
    if len(points) < 2:
        return "Мало данных для разбора — попробуй период побольше."
    values = [p for _, p in points]
    unit = asset.unit
    last, first = values[-1], values[0]
    lo, hi = min(values), max(values)
    lines = [f"<b>🧠 Разбор {asset.name} за {period_name}</b>\n",
             f"Сейчас: <b>{fmt_price(last, unit)}</b>",
             f"Изменение: {fmt_pct((last / first - 1) * 100)}",
             f"Диапазон: {fmt_price(lo, unit)} — {fmt_price(hi, unit)}"]

    s_short, s_long = sma(values, 7), sma(values, 25)
    if s_short and s_long:
        if last > s_short > s_long:
            trend = "📈 восходящий: цена выше средних, короткая средняя выше длинной"
        elif last < s_short < s_long:
            trend = "📉 нисходящий: цена ниже средних, короткая средняя ниже длинной"
        else:
            trend = "↔️ без явного направления (боковик или разворот)"
        lines.append(f"\nТренд: {trend}")
        lines.append(f"Средняя за 7 дн: {fmt_price(s_short, unit)}, за 25 дн: {fmt_price(s_long, unit)}")
    elif s_short:
        lines.append(f"\nСредняя за 7 дн: {fmt_price(s_short, unit)} — цена {'выше' if last > s_short else 'ниже'} неё")

    r = rsi(values)
    if r is not None:
        if r >= 70:
            note = "перекупленность — после сильного роста часто бывает откат"
        elif r <= 30:
            note = "перепроданность — после сильного падения часто бывает отскок"
        else:
            note = "нейтрально"
        lines.append(f"RSI(14): {r:.0f} — {note}")

    recent = values[-14:]
    lines.append(f"\nПоддержка (мин. 14 дн): {fmt_price(min(recent), unit)}")
    lines.append(f"Сопротивление (макс. 14 дн): {fmt_price(max(recent), unit)}")

    returns = [(b / a - 1) * 100 for a, b in zip(values, values[1:]) if a]
    if len(returns) >= 5:
        vol = pstdev(returns)
        mood = "спокойно" if vol < 0.7 else "умеренно" if vol < 2.5 else "очень резко"
        lines.append(f"Волатильность: ±{vol:.1f}% в день — цена ходит {mood}".replace(".", ","))
    lines.append(f"\n{DISCLAIMER}")
    return "\n".join(lines)


def usdt_premium(q: dict[str, Quote]) -> str | None:
    if "USDT" in q and "USD" in q:
        prem = (q["USDT"].price / q["USD"].price - 1) * 100
        side = "дороже" if prem >= 0 else "дешевле"
        return f"USDT {side} официального доллара на {abs(prem):.1f}%".replace(".", ",")
    return None


def chart_png(asset: Asset, points: list[tuple[date, float]], period_name: str) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    days = [d for d, _ in points]
    values = [p for _, p in points]
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=120)
    ax.plot(days, values, color="#2a7de1", linewidth=2, label="Цена")
    for n, color in ((7, "#f2a33a"), (25, "#9b59b6")):
        if len(values) >= n:
            ax.plot(days[n - 1:], [mean(values[i - n + 1:i + 1]) for i in range(n - 1, len(values))],
                    color=color, linewidth=1.2, linestyle="--", label=f"Средняя {n} дн")
    ax.set_title(f"{asset.code} за {period_name}: {fmt_price(values[-1], asset.unit)}")
    ax.grid(alpha=0.3)
    ax.legend(loc="best")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    fig.autofmt_xdate()
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
