"""Yahoo Finance via yfinance: quote, ratios and ~4 years of annual statements."""
import math
import time

import yfinance as yf

from ..cache import cached
from ..config import TTL_PRICES

# Statement rows per series, most preferred first; companies don't all report the same line items.
_ROWS = {
    "income_stmt": {
        "net_income": ["Net Income", "Net Income Common Stockholders",
                       "Net Income From Continuing And Discontinued Operation",
                       "Net Income From Continuing Operation Net Minority Interest"],
        "revenue": ["Total Revenue", "Operating Revenue"],
    },
    "balance_sheet": {"equity": ["Stockholders Equity", "Common Stock Equity"], "total_debt": ["Total Debt"]},
    "cashflow": {"fcf": ["Free Cash Flow"]},
}


def _clean(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _fetch(ticker: str) -> dict | None:
    t = yf.Ticker(ticker)
    info = t.info or {}
    price = _clean(info.get("currentPrice")) or _clean(info.get("regularMarketPrice"))
    if price is None:
        return None
    history: dict[str, dict[str, float]] = {}
    for attr, rows in _ROWS.items():
        df = getattr(t, attr)
        if df is None or df.empty:
            continue
        for key, names in rows.items():
            series: dict[str, float] = {}
            for name in reversed(names):  # preferred rows overwrite fallbacks year by year
                if name in df.index:
                    values = {str(col.year): _clean(v) for col, v in df.loc[name].items()}
                    series.update({year: v for year, v in values.items() if v is not None})
            if series:
                history[key] = series
    if not history:
        # Yahoo sometimes returns empty statements while throttling; raise so it's retried, not cached.
        raise RuntimeError("Yahoo returned no financial statements")
    debt_to_equity = _clean(info.get("debtToEquity"))
    return {
        "info": {
            "name": info.get("longName") or info.get("shortName"),
            "price": price,
            "pe": _clean(info.get("trailingPE")),
            "shares": _clean(info.get("sharesOutstanding")),
            "market_cap": _clean(info.get("marketCap")),
            "exchange": info.get("exchange"),
            "currency": info.get("currency"),
            "financial_currency": info.get("financialCurrency") or info.get("currency"),
            "roe": _clean(info.get("returnOnEquity")),
            "roa": _clean(info.get("returnOnAssets")),
            "net_margin": _clean(info.get("profitMargins")),
            # Yahoo reports D/E as a percentage (78.4 == 0.784).
            "debt_to_equity": debt_to_equity / 100 if debt_to_equity is not None else None,
        },
        "history": history,
    }


def fetch(ticker: str, attempts: int = 4) -> dict | None:
    def load():
        for attempt in range(attempts):
            try:
                return _fetch(ticker)
            except Exception:  # yfinance raises assorted errors on throttling / bad symbols
                if attempt == attempts - 1:
                    raise
                time.sleep(5 * 3 ** attempt)  # 5s, 15s, 45s: Yahoo's throttling lasts tens of seconds
    return cached("yahoo", ticker, TTL_PRICES, load)


def fx_rate(from_currency: str, to_currency: str) -> float | None:
    """Rate to convert amounts in `from_currency` into `to_currency`."""
    if not from_currency or not to_currency or from_currency == to_currency:
        return 1.0

    def load():
        price = yf.Ticker(f"{from_currency}{to_currency}=X").fast_info.get("last_price")
        return _clean(price)
    return cached("fx", f"{from_currency}{to_currency}", TTL_PRICES, load)
