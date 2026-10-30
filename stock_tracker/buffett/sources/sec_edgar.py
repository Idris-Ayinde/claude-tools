"""SEC EDGAR XBRL company facts: official 10-K figures, usually 10+ years (US companies only)."""
from datetime import date

from ..cache import cached
from ..config import SEC_USER_AGENT, TTL_FUNDAMENTALS
from ..http import RateLimiter, make_session

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Companies switch tags over time, so values from all listed tags are merged (earlier tags win on overlap).
CONCEPTS = {
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenuesNetOfInterestExpense",
    ],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}
_INSTANT = {"equity"}

_session = make_session(SEC_USER_AGENT)
_limiter = RateLimiter(8)  # SEC allows 10 requests/second


def _get_json(url: str):
    _limiter.wait()
    resp = _session.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _cik_map() -> dict[str, int]:
    def load():
        data = _get_json(TICKERS_URL)
        return {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
    return cached("sec", "_company_tickers", TTL_FUNDAMENTALS, load)


def annual_values(entries: list[dict], instant: bool) -> dict[str, float]:
    """Pick one value per fiscal year (keyed by period-end year) from 10-K facts; later filings win."""
    values = {}
    for e in sorted(entries, key=lambda e: e.get("filed", "")):
        if not e.get("form", "").startswith("10-K") or "end" not in e:
            continue
        if not instant:
            if "start" not in e:
                continue
            days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if not 350 <= days <= 380:
                continue
        values[e["end"][:4]] = float(e["val"])
    return values


def extract_history(facts: dict) -> dict[str, dict[str, float]]:
    gaap = facts.get("facts", {}).get("us-gaap", {})
    history = {}
    for key, tags in CONCEPTS.items():
        merged: dict[str, float] = {}
        for tag in reversed(tags):
            entries = gaap.get(tag, {}).get("units", {}).get("USD", [])
            merged.update(annual_values(entries, key in _INSTANT))
        if merged:
            history[key] = merged
    ocf, capex = history.pop("ocf", {}), history.pop("capex", {})
    fcf = {year: ocf[year] - capex[year] for year in ocf if year in capex}
    if fcf:
        history["fcf"] = fcf
    return history


def fetch(ticker: str) -> dict | None:
    cik = _cik_map().get(ticker.upper())
    if cik is None:
        return None
    return cached("sec", ticker, TTL_FUNDAMENTALS, lambda: {"history": extract_history(_get_json(FACTS_URL.format(cik=cik)))})
