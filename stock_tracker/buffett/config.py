import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CACHE_DIR = ROOT / "cache"
DATA_DIR = ROOT / "data"
RESULTS_FILE = DATA_DIR / "results.csv"

FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
FMP_DAILY_BUDGET = int(os.getenv("FMP_DAILY_BUDGET", "240"))
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "").strip() or "BuffettScreener/1.0 (personal research)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

# Cache lifetimes, in hours.
TTL_PRICES = 24
TTL_FUNDAMENTALS = 24 * 7

# DCF assumptions (Buffett-style: conservative growth, ~10% hurdle rate).
DISCOUNT_RATE = 0.10
TERMINAL_GROWTH = 0.025
MAX_GROWTH = 0.12
PROJECTION_YEARS = 10

COUNTRIES = ("USA", "Canada")
SECTORS = (
    "Communication Services",
    "Consumer Discretionary",
    "Consumer Staples",
    "Energy",
    "Financials",
    "Health Care",
    "Industrials",
    "Information Technology",
    "Materials",
    "Real Estate",
    "Utilities",
)
