"""Human-friendly numbers and labels for the dashboard."""
import math

_SYMBOLS = {"USD": "$", "CAD": "CA$"}


def missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def money(value, currency: str | None) -> str:
    """$247.22 USD / CA$288.21 / 12.50 EUR."""
    if missing(value):
        return "n/a"
    if currency == "USD":
        return f"${value:,.2f} USD"
    if currency in _SYMBOLS:
        return f"{_SYMBOLS[currency]}{value:,.2f}"
    return f"{value:,.2f} {currency or ''}".strip()


def compact(value, currency: str | None = None) -> str:
    """5_092_060_000_000 -> $5.1T (sign kept, symbol optional)."""
    if missing(value):
        return "n/a"
    sign = "-" if value < 0 else ""
    value = abs(value)
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if value >= divisor:
            text = f"{value / divisor:.1f}{suffix}"
            break
    else:
        text = f"{value:.0f}"
    symbol = _SYMBOLS.get(currency or "", "")
    suffix = f" {currency}" if currency and currency not in _SYMBOLS else ""
    return f"{sign}{symbol}{text}{suffix}"


def pct(value, digits: int = 0) -> str:
    return "n/a" if missing(value) else f"{value:.{digits}%}"


def roe_label(roe) -> str:
    if missing(roe):
        return "n/a"
    return "strong" if roe >= 0.15 else "fair" if roe >= 0.10 else "weak"


def debt_label(debt_to_equity, capital_heavy: bool = False) -> str:
    if missing(debt_to_equity):
        return "n/a"
    low, moderate = (1.0, 2.0) if capital_heavy else (0.5, 1.0)
    return "low" if debt_to_equity <= low else "moderate" if debt_to_equity <= moderate else "high"


def margin_label(margin) -> str:
    if missing(margin):
        return "n/a"
    return "strong" if margin >= 0.15 else "good" if margin >= 0.10 else "thin" if margin >= 0.05 else "weak"


def score_tier(score) -> str:
    """Badge tier: strong (80+), moderate (60-79), weak (<60)."""
    if missing(score):
        return "weak"
    return "strong" if score >= 80 else "moderate" if score >= 60 else "weak"


def valuation_label(margin_of_safety) -> str:
    """Cheap when priced 15%+ below estimated value, expensive when 10%+ above it."""
    if missing(margin_of_safety):
        return "n/a"
    if margin_of_safety >= 0.15:
        return "cheap"
    return "fair" if margin_of_safety >= -0.10 else "expensive"
