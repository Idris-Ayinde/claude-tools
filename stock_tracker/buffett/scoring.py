"""Warren Buffett-style scoring: durable profitability, low debt, consistent earnings, and a margin of safety."""
from dataclasses import dataclass, field

from .config import DISCOUNT_RATE, MAX_GROWTH, PROJECTION_YEARS, TERMINAL_GROWTH
from .fundamentals import Fundamentals

FINANCIALS = {"Financials"}  # banks/insurers: leverage is the business model, FCF is not meaningful
CAPITAL_HEAVY = {"Utilities", "Real Estate"}  # regulated/asset-backed businesses carry more debt
MAX_HISTORY_YEARS = 10
MIN_HISTORY_YEARS = 3
MIN_COVERAGE = 0.6


@dataclass
class Criterion:
    key: str
    label: str
    weight: float
    value: float | None  # 0..1, None when it can't be evaluated (weight is then redistributed)
    detail: str


@dataclass
class ScoreResult:
    score: float
    coverage: float
    eligible: bool
    reason: str
    intrinsic_value: float | None
    margin_of_safety: float | None
    criteria: list[Criterion]
    checklist: dict[str, bool | None]
    metrics: dict[str, float | None] = field(default_factory=dict)


def ramp(x: float | None, bad: float, good: float) -> float | None:
    """Linear partial credit: 0 at `bad`, 1 at `good` (works in either direction)."""
    if x is None:
        return None
    return min(1.0, max(0.0, (x - bad) / (good - bad)))


def recent(series: dict[int, float] | None, n: int = MAX_HISTORY_YEARS) -> list[float]:
    return [series[y] for y in sorted(series)[-n:]] if series else []


def cagr(values: list[float]) -> float | None:
    """Compound annual growth between the averages of the first and last few years.

    Averaging the ends (up to 3 years each) stops one unusual year, like a one-off tax charge, from
    producing a misleading growth rate. None if fewer than 3 points or a non-positive end.
    """
    if len(values) < MIN_HISTORY_YEARS:
        return None
    k = min(3, max(1, len(values) // 3))
    start, end = sum(values[:k]) / k, sum(values[-k:]) / k
    if start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / (len(values) - k)) - 1


def _growth_score(values: list[float], good: float) -> float | None:
    if len(values) < MIN_HISTORY_YEARS:
        return None
    growth = cagr(values)
    return 0.0 if growth is None else ramp(growth, 0.0, good)


def dcf_value(base: float, growth: float, years: int = PROJECTION_YEARS,
              discount: float = DISCOUNT_RATE, terminal: float = TERMINAL_GROWTH) -> float:
    """Present value of cash flows growing at `growth`, fading linearly to `terminal`, plus a terminal value."""
    pv, cash = 0.0, base
    for t in range(1, years + 1):
        g = growth + (terminal - growth) * (t - 1) / (years - 1)
        cash *= 1 + g
        pv += cash / (1 + discount) ** t
    return pv + cash * (1 + terminal) / (discount - terminal) / (1 + discount) ** years


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def score(f: Fundamentals) -> ScoreResult:
    financial = f.sector in FINANCIALS
    h = f.history
    net_income = recent(h.get("net_income"))
    fcf = recent(h.get("fcf"))
    equity = h.get("equity") or {}
    revenue = h.get("revenue") or {}
    ni_series = h.get("net_income") or {}

    roes = [ni_series[y] / equity[y] for y in sorted(ni_series)[-MAX_HISTORY_YEARS:] if equity.get(y, 0) > 0]
    negative_equity = bool(equity) and equity[max(equity)] <= 0
    roe_avg = sum(roes) / len(roes) if roes and not negative_equity else None
    margins = [ni_series[y] / revenue[y] for y in sorted(ni_series)[-3:] if revenue.get(y, 0) > 0]
    margin_avg = sum(margins) / len(margins) if margins else None
    ni_cagr, fcf_cagr = cagr(net_income), cagr(fcf)
    latest_ni = net_income[-1] if net_income else None

    criteria: list[Criterion] = []

    def add(key, label, weight, value, detail):
        criteria.append(Criterion(key, label, weight, value, detail))

    # 1. High, consistent return on equity (Buffett: ROE > 15% without excessive leverage).
    if negative_equity:
        note = "Negative book equity (large buybacks) - ROE not meaningful"
        add("roe_level", "Average ROE >= 15%", 12, None, note)
        add("roe_consistency", "ROE >= 15% every year", 8, None, note)
    else:
        add("roe_level", "Average ROE >= 15%", 12, ramp(roe_avg, 0.05, 0.15),
            f"avg ROE {_pct(roe_avg)} over {len(roes)} yrs")
        hits = sum(r >= 0.15 for r in roes)
        add("roe_consistency", "ROE >= 15% every year", 8,
            hits / len(roes) if len(roes) >= MIN_HISTORY_YEARS else None, f"{hits}/{len(roes)} years >= 15%")

    # 2. Conservative balance sheet.
    debt = f.latest("total_debt")
    if financial:
        add("debt", "Return on assets >= 1% (financials)", 15, ramp(f.roa, 0.005, 0.012), f"ROA {_pct(f.roa)}")
    elif negative_equity or f.debt_to_equity is None:
        if debt is None or latest_ni is None:
            add("debt", "Debt payable from <= 3 yrs earnings", 15, None, "no debt data")
        else:
            years_to_repay = debt / latest_ni if latest_ni > 0 else None
            add("debt", "Debt payable from <= 3 yrs earnings", 15,
                ramp(years_to_repay, 5, 3) if years_to_repay is not None else 0.0,
                f"debt = {years_to_repay:.1f} yrs of earnings" if years_to_repay is not None else "no earnings to repay debt")
    else:
        limit = 1.0 if f.sector in CAPITAL_HEAVY else 0.5
        add("debt", f"Debt/Equity <= {limit}", 15, ramp(f.debt_to_equity, limit * 2, limit),
            f"D/E {f.debt_to_equity:.2f}")

    # 3. Pricing power: healthy net margin.
    add("net_margin", "Net margin (full credit at 15%)", 14, ramp(margin_avg, 0.05, 0.15), f"3-yr avg net margin {_pct(margin_avg)}")

    # 4. Consistent, growing earnings.
    enough = len(net_income) >= MIN_HISTORY_YEARS
    profitable = sum(v > 0 for v in net_income)
    add("profitable_years", "Profitable every year", 6, profitable / len(net_income) if enough else None,
        f"{profitable}/{len(net_income)} profitable years")
    add("earnings_growth", "Earnings growth (full credit at 10%/yr)", 5, _growth_score(net_income, 0.10), f"net income CAGR {_pct(ni_cagr)}")
    declines = sum(b < a for a, b in zip(net_income, net_income[1:]))
    add("earnings_steadiness", "Few earnings declines", 4, 1 - declines / (len(net_income) - 1) if enough else None,
        f"{declines} down years")

    # 5. Owner earnings: positive and growing free cash flow.
    if financial:
        add("fcf_positive", "Positive free cash flow", 6, None, "not meaningful for financials")
        add("fcf_growth", "FCF growth (full credit at 8%/yr)", 5, None, "not meaningful for financials")
    else:
        positive = sum(v > 0 for v in fcf)
        add("fcf_positive", "Positive free cash flow", 6, positive / len(fcf) if len(fcf) >= MIN_HISTORY_YEARS else None,
            f"{positive}/{len(fcf)} positive years")
        add("fcf_growth", "FCF growth (full credit at 8%/yr)", 5, _growth_score(fcf, 0.08), f"FCF CAGR {_pct(fcf_cagr)}")

    # 6. Margin of safety: price vs. DCF intrinsic value, and a sane P/E.
    growth_inputs = [g for g in (ni_cagr, None if financial else fcf_cagr) if g is not None]
    growth = min(max(min(growth_inputs), 0.0), MAX_GROWTH) if growth_inputs else TERMINAL_GROWTH
    base_series = net_income if financial else fcf
    intrinsic = mos = None
    if base_series and f.shares and f.price:
        base = sum(base_series[-3:]) / len(base_series[-3:])
        intrinsic = dcf_value(base, growth) * f.fx / f.shares if base > 0 else 0.0
        mos = (intrinsic - f.price) / intrinsic if intrinsic > 0 else -1.0
    add("margin_of_safety", "Price below intrinsic value", 17, ramp(mos, -0.25, 0.30),
        f"intrinsic {intrinsic:,.2f} vs price {f.price:,.2f} (MoS {_pct(mos)}, growth {growth:.1%})"
        if intrinsic is not None else "insufficient data for DCF")
    if latest_ni is not None and latest_ni <= 0:
        add("pe", "P/E (full credit at 12 or less)", 8, 0.0, "loss-making")
    else:
        add("pe", "P/E (full credit at 12 or less)", 8, ramp(f.pe, 30, 12), f"P/E {f.pe:.1f}" if f.pe else "P/E n/a")

    available = sum(c.weight for c in criteria if c.value is not None)
    total = sum(c.weight for c in criteria)
    earned = sum(c.weight * c.value for c in criteria if c.value is not None)
    result_score = round(100 * earned / available, 1) if available else 0.0
    coverage = available / total

    if f.price is None:
        eligible, reason = False, "no price data"
    elif len(net_income) < MIN_HISTORY_YEARS:
        eligible, reason = False, f"only {len(net_income)} years of earnings history"
    elif coverage < MIN_COVERAGE:
        eligible, reason = False, f"data coverage {coverage:.0%} < {MIN_COVERAGE:.0%}"
    else:
        eligible, reason = True, ""

    debt_value = next(c.value for c in criteria if c.key == "debt")
    checklist = {
        "ROE >= 15%": None if roe_avg is None else roe_avg >= 0.15,
        "Low debt": None if debt_value is None else debt_value >= 0.99,
        "Net margin >= 10%": None if margin_avg is None else margin_avg >= 0.10,
        "Profitable every year": profitable == len(net_income) if enough else None,
        "Growing earnings": None if not enough else (ni_cagr or 0) > 0,
        "Below intrinsic value": None if mos is None else mos > 0,
    }
    metrics = {
        "roe_avg": roe_avg,
        "net_margin": margin_avg,
        "ni_cagr": ni_cagr,
        "fcf_cagr": fcf_cagr,
        "growth_used": growth,
        "years": len(net_income),
    }
    return ScoreResult(result_score, coverage, eligible, reason, intrinsic, mos, criteria, checklist, metrics)
