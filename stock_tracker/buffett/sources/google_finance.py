"""Google Finance quote page (HTML scrape): price and P/E for cross-checking."""
from bs4 import BeautifulSoup

from ..cache import cached
from ..config import BROWSER_USER_AGENT, TTL_PRICES
from ..http import RateLimiter, make_session, parse_number

QUOTE_URL = "https://www.google.com/finance/quote/{symbol}?hl=en"
# Yahoo exchange codes -> Google exchange codes.
_EXCHANGES = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NYQ": "NYSE", "ASE": "NYSEAMERICAN", "PCX": "NYSEARCA", "BTS": "BATS"}

_session = make_session(BROWSER_USER_AGENT)
_limiter = RateLimiter(3)


def google_symbol(ticker: str, yahoo_exchange: str | None) -> str:
    if ticker.endswith(".TO"):
        return ticker[:-3].replace("-", ".") + ":TSE"
    return ticker.replace("-", ".") + ":" + _EXCHANGES.get(yahoo_exchange or "", "NYSE")


def _stat(soup: BeautifulSoup, label: str) -> str | None:
    el = soup.find(lambda t: t.name == "div" and t.get_text(strip=True) == label and t.find_next_sibling("div"))
    return el.find_next_sibling("div").get_text(strip=True) if el else None


def parse(html: str) -> dict | None:
    soup = BeautifulSoup(html, "lxml")
    # The page also carries index tickers in the same span type; the quote's own price follows the company name.
    name = soup.select_one("div.gO24Ff")
    price_el = name.find_next("span", attrs={"jsname": "Pdsbrc"}) if name else None
    price = parse_number(price_el.get_text()) if price_el else None
    pe = parse_number(_stat(soup, "P/E ratio"))
    if price is None and pe is None:
        return None
    return {"price": price, "pe": pe}


def fetch(ticker: str, yahoo_exchange: str | None) -> dict | None:
    def load():
        _limiter.wait()
        resp = _session.get(QUOTE_URL.format(symbol=google_symbol(ticker, yahoo_exchange)), timeout=20)
        return parse(resp.text) if resp.status_code == 200 else None
    return cached("google", ticker, TTL_PRICES, load)
