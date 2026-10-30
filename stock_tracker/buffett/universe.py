"""Index constituents (the stocks we screen), scraped from Wikipedia."""
import io

import pandas as pd

from .cache import cached
from .config import BROWSER_USER_AGENT, TTL_FUNDAMENTALS
from .http import make_session

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
TSX_URL = "https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index"

_SECTOR_ALIASES = {"Healthcare": "Health Care", "Telecommunication Services": "Communication Services"}

_session = make_session(BROWSER_USER_AGENT)


def _tables(url: str) -> list[pd.DataFrame]:
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), keep_default_na=False)


def _find_table(tables, ticker_col: str) -> tuple[pd.DataFrame, str]:
    for table in tables:
        cols = [str(c) for c in table.columns]
        sector_col = next((c for c in cols if c.lower().startswith(("gics sector", "sector"))), None)
        if ticker_col in cols and sector_col:
            return table, sector_col
    raise ValueError(f"No constituents table with a '{ticker_col}' column found")


def _sp500() -> list[dict]:
    table, sector_col = _find_table(_tables(SP500_URL), "Symbol")
    return [
        {
            "ticker": str(row["Symbol"]).strip().replace(".", "-"),
            "name": row["Security"],
            "country": "USA",
            "sector": _SECTOR_ALIASES.get(row[sector_col], row[sector_col]),
        }
        for _, row in table.iterrows()
        if str(row["Symbol"]).strip()
    ]


def _tsx() -> list[dict]:
    table, sector_col = _find_table(_tables(TSX_URL), "Ticker")
    return [
        {
            "ticker": str(row["Ticker"]).strip().replace(".", "-") + ".TO",
            "name": row["Company"],
            "country": "Canada",
            "sector": _SECTOR_ALIASES.get(row[sector_col], row[sector_col]),
        }
        for _, row in table.iterrows()
        if str(row["Ticker"]).strip()
    ]


def load_universe(countries=("USA", "Canada")) -> list[dict]:
    companies = []
    if "USA" in countries:
        companies += cached("universe", "sp500", TTL_FUNDAMENTALS, _sp500)
    if "Canada" in countries:
        companies += cached("universe", "tsx_composite", TTL_FUNDAMENTALS, _tsx)
    return companies
