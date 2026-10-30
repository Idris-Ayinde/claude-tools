"""Financial Modeling Prep (optional API key): statement history to fill gaps, within a daily call budget."""
import json
import threading
from datetime import date

from ..cache import cached
from ..config import CACHE_DIR, FMP_API_KEY, FMP_DAILY_BUDGET, TTL_FUNDAMENTALS
from ..http import RateLimiter, make_session

BASE_URL = "https://financialmodelingprep.com/stable/{endpoint}"
STATEMENTS = {
    "income-statement": {"netIncome": "net_income", "revenue": "revenue"},
    "balance-sheet-statement": {"totalStockholdersEquity": "equity", "totalDebt": "total_debt"},
    "cash-flow-statement": {"freeCashFlow": "fcf"},
}

_session = make_session("BuffettScreener/1.0")
_limiter = RateLimiter(4)
_budget_lock = threading.Lock()
_BUDGET_FILE = CACHE_DIR / "fmp" / "_budget.json"


def enabled() -> bool:
    return bool(FMP_API_KEY)


def _take_budget(calls: int) -> bool:
    with _budget_lock:
        today = date.today().isoformat()
        used = {}
        if _BUDGET_FILE.exists():
            used = json.loads(_BUDGET_FILE.read_text())
        count = used.get(today, 0)
        if count + calls > FMP_DAILY_BUDGET:
            return False
        _BUDGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BUDGET_FILE.write_text(json.dumps({today: count + calls}))
        return True


def _statement(endpoint: str, ticker: str) -> list[dict] | None:
    _limiter.wait()
    resp = _session.get(
        BASE_URL.format(endpoint=endpoint),
        params={"symbol": ticker, "period": "annual", "limit": 10, "apikey": FMP_API_KEY},
        timeout=30,
    )
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data if isinstance(data, list) else None  # errors come back as {"Error Message": ...}


def _fetch(ticker: str) -> dict | None:
    if not _take_budget(len(STATEMENTS)):
        return None
    history: dict[str, dict[str, float]] = {}
    for endpoint, fields in STATEMENTS.items():
        for row in _statement(endpoint, ticker) or []:
            year = str(row.get("date", ""))[:4]
            for field, key in fields.items():
                if year and row.get(field) is not None:
                    history.setdefault(key, {})[year] = float(row[field])
    return {"history": history} if history else None


def fetch(ticker: str) -> dict | None:
    if not enabled():
        return None
    return cached("fmp", ticker, TTL_FUNDAMENTALS, lambda: _fetch(ticker))
