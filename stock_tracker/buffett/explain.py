"""Plain-English reasons why a stock does or doesn't meet Buffett's rules, written from its own numbers."""
from dataclasses import dataclass

from .formatting import missing, money, pct, valuation_label
from .scoring import CAPITAL_HEAVY, FINANCIALS, MAX_HISTORY_YEARS

VALUATION_KEYS = {"margin_of_safety", "pe"}


@dataclass
class Reason:
    passed: bool | None  # None = couldn't be judged
    text: str


def _cents(x: float) -> str:
    return f"${x:.2f}"


def _years(history: dict, key: str) -> list[float]:
    """Values for the most recent years, matching the window the score uses."""
    series = history.get(key) or {}
    return [series[y] for y in sorted(series)[-MAX_HISTORY_YEARS:]]


def quality(details: dict) -> float | None:
    """Share of the business-quality points earned (everything except the price criteria)."""
    rated = [c for c in details["criteria"] if c["key"] not in VALUATION_KEYS and c["value"] is not None]
    weight = sum(c["weight"] for c in rated)
    return sum(c["weight"] * c["value"] for c in rated) / weight if weight else None


def reasons(row: dict, details: dict) -> list[Reason]:
    history = details.get("history", {})
    criteria = {c["key"]: c for c in details["criteria"]}
    financial = row["sector"] in FINANCIALS
    net_income = _years(history, "net_income")
    n = len(net_income)
    out: list[Reason] = []

    # Return on equity
    roe = row.get("roe_avg")
    if criteria["roe_level"]["value"] is None and "Negative" in criteria["roe_level"]["detail"]:
        out.append(Reason(None, "Shareholders' equity is negative because of large share buybacks, "
                                "so return on equity can't be measured."))
    elif not missing(roe) and roe < 0:
        out.append(Reason(False, f"Lost {_cents(-roe)} on every $1 shareholders invested, on average over {n} years "
                                 "(Buffett wants a profit of at least $0.15)."))
    elif not missing(roe):
        note = (" That's unusually high because large share buybacks have shrunk shareholders' equity."
                if roe > 1 else "")
        out.append(Reason(roe >= 0.15, f"Earns {_cents(roe)} profit on every $1 shareholders invested, on average "
                                       f"over {n} years (Buffett wants at least $0.15).{note}"))

    # Debt
    debt_to_equity = row.get("debt_to_equity")
    debt_years = _years(history, "total_debt")
    if financial:
        roa = row.get("roa")
        if not missing(roa):
            out.append(Reason(roa >= 0.01, f"As a financial company, it earns {pct(roa, 1)} a year on everything it owns "
                                           "(return on assets; 1% or more is strong for banks and insurers)."))
    elif criteria["debt"]["label"].startswith("Debt payable"):
        latest_ni = net_income[-1] if net_income else None
        if debt_years and latest_ni and latest_ni > 0:
            years = debt_years[-1] / latest_ni
            out.append(Reason(years <= 3, f"Its debt could be paid off with {years:.1f} years of profits "
                                          "(Buffett likes 3 years or less)."))
        elif debt_years:
            out.append(Reason(False, "It has debt but no recent profits to pay it off with."))
    elif not missing(debt_to_equity):
        limit = 1.0 if row["sector"] in CAPITAL_HEAVY else 0.5
        out.append(Reason(debt_to_equity <= limit,
                          f"Has {_cents(debt_to_equity)} of debt for every $1 of shareholders' equity "
                          f"(Buffett prefers under {_cents(limit)}{' for this kind of business' if limit > 0.5 else ''})."))

    # Profit margin
    margin = row.get("net_margin")
    if not missing(margin):
        out.append(Reason(margin >= 0.10, f"Keeps {_cents(max(margin, 0))} of every $1 of sales as profit "
                                          "(businesses with pricing power keep $0.10 or more)."
                          if margin >= 0 else "Loses money on its sales on average over the last 3 years."))

    # Earnings record
    if n >= 3:
        losses = sum(v <= 0 for v in net_income)
        out.append(Reason(losses == 0, f"Made money in each of the last {n} years." if losses == 0
                          else f"Lost money in {losses} of the last {n} years."))
        growth = row.get("earnings_cagr")
        if missing(growth):
            out.append(Reason(False, "Profits were negative at the start or end of the period, so there's no steady growth."))
        elif growth > 0:
            out.append(Reason(True, f"Profits grew about {pct(growth)} a year over {n} years."))
        else:
            out.append(Reason(False, f"Profits shrank about {pct(-growth)} a year over {n} years."))

    # Free cash flow
    fcf = _years(history, "fcf")
    if not financial and len(fcf) >= 3:
        positive = sum(v > 0 for v in fcf)
        out.append(Reason(positive == len(fcf),
                          f"Had cash left over after investing in the business (free cash flow) in {positive} "
                          f"of {len(fcf)} years."))

    # Price
    mos, value, price, currency = row.get("margin_of_safety"), row.get("intrinsic_value"), row.get("price"), row.get("currency")
    if not missing(value) and value <= 0:
        out.append(Reason(False, "Its cash flows are too weak to estimate what the business is worth."))
    elif not missing(mos):
        if mos > 0:
            out.append(Reason(True, f"The price is {pct(mos)} below our estimate of what the business is worth "
                                    f"({money(value, currency)}), giving a margin of safety."))
        else:
            ratio = price / value
            gap = f"about {ratio:.0f}× our estimate" if ratio >= 3 else f"{pct(ratio - 1)} above our estimate"
            out.append(Reason(False, f"The price is {gap} of what the business is worth "
                                     f"({money(value, currency)}), so there's no margin of safety."))
    pe = row.get("pe")
    if not missing(pe):
        out.append(Reason(pe <= 15, f"You pay ${pe:.0f} for every $1 of yearly profit (P/E {pe:.1f}; "
                                    "Buffett-style investors like 15 or less)."))
    return out


def verdict(row: dict, details: dict) -> str:
    q = quality(details)
    if q is None:
        return "Not enough data to judge this business."
    business = ("A high-quality business" if q >= 0.75
                else "A decent business with some weak spots" if q >= 0.5
                else "A business that misses several of Buffett's quality tests")
    price = {
        "cheap": "trading below what it appears to be worth",
        "fair": "priced fairly",
        "expensive": "priced above what it appears to be worth",
        "n/a": "hard to value with the data available",
    }[valuation_label(row.get("margin_of_safety"))]
    return f"{business} that's currently {price}."
