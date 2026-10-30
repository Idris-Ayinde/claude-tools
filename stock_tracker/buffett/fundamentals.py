"""Merge data from all sources into one consistent view of a company."""
from dataclasses import dataclass, field
from statistics import median

SERIES = ("net_income", "revenue", "equity", "total_debt", "fcf")


@dataclass
class Fundamentals:
    ticker: str
    name: str
    country: str
    sector: str
    price: float | None = None
    currency: str | None = None
    pe: float | None = None
    shares: float | None = None
    market_cap: float | None = None
    fx: float = 1.0  # converts financial-statement currency into the trading currency
    roa: float | None = None
    debt_to_equity: float | None = None
    # Annual series keyed by fiscal-year-end year, in financial-statement currency.
    history: dict[str, dict[int, float]] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def latest(self, key: str) -> float | None:
        series = self.history.get(key) or {}
        return series[max(series)] if series else None


def merge_history(*histories: dict | None) -> dict[str, dict[int, float]]:
    """Union of years across sources; on overlapping years the source with the longest series wins."""
    merged = {}
    for key in SERIES:
        candidates = [
            {int(year): value for year, value in h[key].items()}
            for h in histories
            if h and h.get(key)
        ]
        series: dict[int, float] = {}
        for candidate in sorted(candidates, key=len):
            series.update(candidate)
        if series:
            merged[key] = dict(sorted(series.items()))
    return merged


def _consensus(values: dict[str, float | None], label: str, warnings: list[str], tolerance: float) -> float | None:
    """Median of the sources that reported a positive value; warn about outliers."""
    present = {src: v for src, v in values.items() if v is not None and v > 0}
    if not present:
        return None
    mid = median(present.values())
    outliers = [src for src, v in present.items() if abs(v - mid) / mid > tolerance]
    if outliers:
        warnings.append(f"{label} disagreement: " + ", ".join(f"{s}={present[s]:.2f}" for s in present))
    return mid


def build(company: dict, yahoo: dict | None, sec: dict | None = None, fmp: dict | None = None,
          google: dict | None = None, finviz: dict | None = None, fx: float = 1.0) -> Fundamentals:
    info = (yahoo or {}).get("info", {})
    google, finviz = google or {}, finviz or {}
    f = Fundamentals(
        ticker=company["ticker"],
        name=info.get("name") or company["name"],
        country=company["country"],
        sector=company["sector"],
        currency=info.get("currency"),
        market_cap=info.get("market_cap"),
        fx=fx,
    )
    for name, payload in (("Yahoo", yahoo), ("SEC EDGAR", sec), ("FMP", fmp), ("Google Finance", google), ("Finviz", finviz)):
        if payload:
            f.sources.append(name)

    f.history = merge_history((yahoo or {}).get("history"), (sec or {}).get("history"), (fmp or {}).get("history"))

    f.price = _consensus(
        {"Yahoo": info.get("price"), "Google": google.get("price"), "Finviz": finviz.get("price")},
        "Price", f.warnings, tolerance=0.05,
    )
    f.shares = f.market_cap / f.price if f.market_cap and f.price else info.get("shares")
    if f.market_cap is None and f.shares and f.price:
        f.market_cap = f.shares * f.price

    net_income = f.latest("net_income")
    computed_pe = f.market_cap / (net_income * fx) if f.market_cap and net_income and net_income > 0 else None
    if net_income is not None and net_income <= 0:
        f.pe = None  # loss-making: P/E is not meaningful
    else:
        reported = {"Yahoo": info.get("pe"), "Google": google.get("pe"), "Finviz": finviz.get("pe")}
        # Our own P/E uses last fiscal year (not trailing 12 months), so it only breaks ties / fills gaps.
        if sum(v is not None and v > 0 for v in reported.values()) < 2:
            reported["computed"] = computed_pe
        f.pe = _consensus(reported, "P/E", f.warnings, tolerance=0.25)

    equity, debt = f.latest("equity"), f.latest("total_debt")
    computed_de = debt / equity if debt is not None and equity and equity > 0 else None
    f.debt_to_equity = _consensus(
        {"computed": computed_de, "Yahoo": info.get("debt_to_equity"), "Finviz": finviz.get("debt_to_equity")},
        "Debt/Equity", f.warnings, tolerance=0.5,
    )
    if computed_de == 0 and f.debt_to_equity is None:
        f.debt_to_equity = 0.0  # debt-free companies are filtered out of the positive-only consensus
    roa_values = [v for v in (info.get("roa"), finviz.get("roa")) if v is not None]
    f.roa = median(roa_values) if roa_values else None
    return f
