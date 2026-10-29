"""Pure helpers: trading math, spaced repetition, parsing. No Telegram, no DB."""
import random
import re
from dataclasses import dataclass
from datetime import date, timedelta

# Spaced repetition: days until the next review after each successful recall.
REVIEW_INTERVALS = [1, 3, 7, 14, 30, 60]

ROADMAP = [
    ("Основы", "Правило №1: сначала подушка безопасности, торгуем только свободными деньгами"),
    ("Основы", "Биржа, брокер, акции, облигации, фонды, криптовалюта — в чём разница"),
    ("Крипта", "Блокчейн, биткоин и стейблкоины: что такое USDT"),
    ("Крипта", "Кошельки: биржевой и свой, сид-фраза и как её хранить"),
    ("Крипта", "Как купить USDT: биржа, P2P и как не потерять деньги и карту"),
    ("Основы", "Инвестиции vs трейдинг: почему большинство трейдеров теряют деньги"),
    ("Крипта", "Спот, фьючерсы, плечо и ликвидация"),
    ("Крипта", "Типы ордеров: рыночный, лимитный, стоп-лосс, тейк-профит"),
    ("Анализ", "Свечной график, таймфреймы, объём"),
    ("Анализ", "Тренд, уровни поддержки и сопротивления"),
    ("Анализ", "Индикаторы: скользящие средние и RSI"),
    ("Риск", "Риск-менеджмент: не больше 1–2% депозита на сделку, стоп-лосс"),
    ("Риск", "Психология: FOMO, жадность, страх, отыгрыш"),
    ("Риск", "Торговый план и дневник сделок"),
    ("Практика", "Демо-счёт: 30 сделок на виртуальных деньгах, без реальных"),
    ("Практика", "DCA: покупка частями вместо попытки поймать дно"),
    ("Право", "Налоги с дохода от торговли"),
    ("Право", "Мошенники: «сигналы», «гарантированный доход», пирамиды"),
    ("Код", "Скрипт на Python: скачать котировки и построить график"),
]

TIPS = [
    "Правило 1%: в одной сделке рискуй не больше 1% депозита. 10 убыточных сделок подряд — и ты потеряла всего ~10%.",
    "Стоп-лосс ставится ДО входа в сделку, а не когда «уже страшно».",
    "Нет плана — нет сделки. Запиши вход, стоп и цель до того, как нажать кнопку.",
    "После 2 убыточных сделок подряд — перерыв до завтра. Так ты не уйдёшь в отыгрыш.",
    "Плечо не увеличивает прибыль — оно увеличивает скорость, с которой ты теряешь депозит.",
    "Если не понимаешь, почему растёт монета, — ты не инвестор, ты пассажир.",
    "«Гарантированный доход», «сигналы за деньги», «удвой депозит» — почти всегда мошенники.",
    "Храни сид-фразу только на бумаге. Никогда — в заметках, скриншотах или чатах.",
    "На P2P проверяй поступление денег в приложении банка, а не по скриншоту от продавца.",
    "Лучшая сделка иногда — не входить в сделку.",
    "Записывай эмоции в дневник сделок: через месяц увидишь, какие из них стоят тебе денег.",
    "Торгуй только деньгами, потерю которых переживёшь спокойно. Подушка безопасности — неприкосновенна.",
]


def next_review(stage: int, today: date) -> date | None:
    """Date of the next review after a successful recall at `stage`, or None when mastered."""
    if stage >= len(REVIEW_INTERVALS):
        return None
    return today + timedelta(days=REVIEW_INTERVALS[stage])


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def parse_numbers(text: str) -> list[float]:
    """'95 000 93000,5 0.01' -> [95000.0, 93000.5, 0.01]. A space between thousands is joined."""
    text = re.sub(r"(?<=\d) (?=\d{3}(?!\d))", "", text or "")
    return [float(x.replace(",", ".")) for x in _NUMBER_RE.findall(text)]


_TIME_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def parse_time(text: str) -> str | None:
    """'7:05' / '07.05' -> '07:05'."""
    m = _TIME_RE.match(text or "")
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2))
    if h > 23 or mnt > 59:
        return None
    return f"{h:02d}:{mnt:02d}"


def time_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def num(x: float) -> str:
    """Human number: 95 000 / 97,40 / 0,0052."""
    if abs(x) >= 1000:
        s = f"{x:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
    elif abs(x) >= 10:
        s = f"{x:.2f}"
    elif abs(x) >= 1:
        s = f"{x:.3f}".rstrip("0").rstrip(".")
    else:
        s = f"{x:.6f}".rstrip("0").rstrip(".") or "0"
    return s.replace(".", ",")


def pct(x: float) -> str:
    return f"{x:.1f}%".replace(".", ",")


def signed(x: float, unit: str) -> str:
    return f"{'+' if x >= 0 else '−'}{num(abs(x))} {unit}"


# ---------------- portfolio ----------------

@dataclass
class Position:
    qty: float = 0.0
    cost: float = 0.0       # money still invested in the remaining qty (avg price * qty)
    realized: float = 0.0   # profit fixed by sells

    @property
    def avg_price(self) -> float:
        return self.cost / self.qty if self.qty > 1e-12 else 0.0


def build_positions(txs: list[tuple[str, float, float]]) -> dict[str, Position]:
    """txs = [(asset, qty (+buy / -sell), price)] in chronological order. Average-cost method."""
    positions: dict[str, Position] = {}
    for asset, qty, price in txs:
        p = positions.setdefault(asset, Position())
        if qty > 0:
            p.qty += qty
            p.cost += qty * price
        else:
            sell = min(-qty, p.qty)
            avg = p.avg_price
            p.realized += (price - avg) * sell
            p.cost -= avg * sell
            p.qty -= sell
    return positions


# ---------------- trades ----------------

def trade_risk(entry: float, stop: float, qty: float) -> float:
    """Money lost if the stop is hit (positive number)."""
    return abs(entry - stop) * qty


def trade_pnl(side: str, entry: float, exit_price: float, qty: float) -> float:
    return (exit_price - entry) * qty if side == "long" else (entry - exit_price) * qty


def stop_is_valid(side: str, entry: float, stop: float) -> bool:
    return stop < entry if side == "long" else stop > entry


def reward_risk(entry: float, stop: float, take: float) -> float:
    return abs(take - entry) / abs(entry - stop) if entry != stop else 0.0


def position_size(deposit: float, risk_pct: float, entry: float, stop: float) -> dict[str, float]:
    """How much to buy so that hitting the stop loses exactly risk_pct of the deposit."""
    risk_money = deposit * risk_pct / 100
    qty = risk_money / abs(entry - stop)
    value = qty * entry
    return {"risk": risk_money, "qty": qty, "value": value, "leverage": value / deposit,
            "stop_pct": abs(entry - stop) / entry * 100}


def journal_stats(closed: list[tuple[float, float]]) -> dict[str, float]:
    """closed = [(pnl, risk)] -> count, winrate %, total, avg R, profit factor."""
    wins = [p for p, _ in closed if p > 0]
    losses = [-p for p, _ in closed if p < 0]
    rs = [p / r for p, r in closed if r > 0]
    if losses:
        pf = sum(wins) / sum(losses)
    else:
        pf = float("inf") if wins else 0.0
    return {
        "count": len(closed),
        "winrate": len(wins) / len(closed) * 100 if closed else 0.0,
        "total": sum(p for p, _ in closed),
        "avg_r": sum(rs) / len(rs) if rs else 0.0,
        "profit_factor": pf,
    }


def random_tip() -> str:
    return random.choice(TIPS)
