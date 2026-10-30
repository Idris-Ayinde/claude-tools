"""Finviz quote page (HTML scrape): ratios snapshot for US stocks."""
from bs4 import BeautifulSoup

from ..cache import cached
from ..config import BROWSER_USER_AGENT, TTL_PRICES
from ..http import RateLimiter, make_session, parse_number

QUOTE_URL = "https://finviz.com/quote.ashx?t={ticker}"
FIELDS = {"Price": "price", "P/E": "pe", "ROE": "roe", "ROA": "roa", "Debt/Eq": "debt_to_equity", "Profit Margin": "net_margin"}

_session = make_session(BROWSER_USER_AGENT)
_limiter = RateLimiter(2)  # Finviz throttles aggressive clients


def parse(html: str) -> dict | None:
    # The snapshot is split across several tables with the same class.
    rows = BeautifulSoup(html, "lxml").select("table.snapshot-table2 tr")
    if not rows:
        return None
    cells = {}
    for tr in rows:
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        cells.update(zip(tds[::2], tds[1::2]))
    values = {key: parse_number(cells.get(label)) for label, key in FIELDS.items()}
    return values if any(v is not None for v in values.values()) else None


def fetch(ticker: str) -> dict | None:
    def load():
        _limiter.wait()
        resp = _session.get(QUOTE_URL.format(ticker=ticker), timeout=20)
        return parse(resp.text) if resp.status_code == 200 else None
    return cached("finviz", ticker, TTL_PRICES, load)
