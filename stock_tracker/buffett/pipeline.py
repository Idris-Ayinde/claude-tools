"""Fetch every source for each stock, score it, and rank the top picks per country and sector."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

import pandas as pd

from . import fundamentals, scoring
from .config import RESULTS_FILE
from .sources import finviz, fmp, google_finance, sec_edgar, yahoo
from .universe import load_universe

FMP_MIN_YEARS = 5  # call FMP only when the free sources give fewer years of earnings than this
RETRYABLE = ("Yahoo error", "analysis error")  # failures worth a second, slower attempt (usually throttling)


def _safe(fn, *args):
    """Secondary sources are best-effort: a broken scraper must not drop the stock."""
    try:
        return fn(*args)
    except Exception:
        return None


def analyze(company: dict) -> dict:
    ticker = company["ticker"]
    row = {"country": company["country"], "sector": company["sector"], "ticker": ticker, "name": company["name"]}
    try:
        yh = yahoo.fetch(ticker)
    except Exception as exc:
        return {**row, "eligible": False, "reason": f"Yahoo error: {exc}"[:200]}
    if yh is None:
        return {**row, "eligible": False, "reason": "no Yahoo quote"}

    info = yh["info"]
    us = company["country"] == "USA"
    sec = _safe(sec_edgar.fetch, ticker) if us else None
    google = _safe(google_finance.fetch, ticker, info.get("exchange"))
    fv = _safe(finviz.fetch, ticker) if us else None
    fx = _safe(yahoo.fx_rate, info.get("financial_currency"), info.get("currency")) or 1.0

    f = fundamentals.build(company, yh, sec=sec, google=google, finviz=fv, fx=fx)
    if fmp.enabled() and len(f.history.get("net_income", {})) < FMP_MIN_YEARS:
        fmp_data = _safe(fmp.fetch, ticker)
        if fmp_data:
            f = fundamentals.build(company, yh, sec=sec, fmp=fmp_data, google=google, finviz=fv, fx=fx)
    if fx != 1.0:
        f.warnings.append(f"Financials in {info.get('financial_currency')}, converted at {fx:.4f} to {f.currency}")

    result = scoring.score(f)
    m = result.metrics
    return {
        **row,
        "name": f.name,
        "score": result.score,
        "eligible": result.eligible,
        "reason": result.reason,
        "checklist": sum(bool(v) for v in result.checklist.values()),
        "price": f.price,
        "currency": f.currency,
        "financial_currency": info.get("financial_currency"),
        "exchange": info.get("exchange"),
        "intrinsic_value": result.intrinsic_value,
        "margin_of_safety": result.margin_of_safety,
        "pe": f.pe,
        "roe_avg": m["roe_avg"],
        "debt_to_equity": f.debt_to_equity,
        "roa": f.roa,
        "net_margin": m["net_margin"],
        "earnings_cagr": m["ni_cagr"],
        "fcf_cagr": m["fcf_cagr"],
        "years_of_data": m["years"],
        "market_cap": f.market_cap,
        "data_coverage": result.coverage,
        "sources": ", ".join(f.sources),
        "warnings": " | ".join(f.warnings),
        "details": json.dumps({
            "criteria": [vars(c) for c in result.criteria],
            "checklist": result.checklist,
            "history": {k: {str(y): v for y, v in s.items()} for k, s in f.history.items()},
            "growth_used": m["growth_used"],
        }),
    }


def run_screen(countries=("USA", "Canada"), sectors=None, limit_per_sector: int | None = None,
               workers: int = 4, progress: Callable[[int, int, str], None] | None = None,
               retry_pause: float = 60) -> pd.DataFrame:
    companies = [c for c in load_universe(countries) if not sectors or c["sector"] in sectors]
    if limit_per_sector:
        seen: dict[tuple, int] = {}
        subset = []
        for c in companies:
            key = (c["country"], c["sector"])
            if seen.get(key, 0) < limit_per_sector:
                seen[key] = seen.get(key, 0) + 1
                subset.append(c)
        companies = subset

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(analyze, c): c for c in companies}
        for done, future in enumerate(as_completed(futures), 1):
            company = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                rows.append({**company, "eligible": False, "reason": f"analysis error: {exc}"[:200]})
            if progress:
                progress(done, len(companies), company["ticker"])

    # Throttled stocks get one more try, one at a time, after Yahoo has had a pause to cool down.
    failed = [i for i, r in enumerate(rows) if str(r.get("reason", "")).startswith(RETRYABLE)]
    if failed and retry_pause:
        time.sleep(retry_pause)
        for n, i in enumerate(failed, 1):
            company = next(c for c in companies if c["ticker"] == rows[i]["ticker"])
            try:
                rows[i] = analyze(company)
            except Exception as exc:
                rows[i] = {**company, "eligible": False, "reason": f"analysis error: {exc}"[:200]}
            if progress:
                progress(n, len(failed), f"retry {company['ticker']}")

    df = pd.DataFrame(rows)
    df.attrs["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return df


def top_picks(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    ranked = df[df["eligible"] == True].sort_values("score", ascending=False)  # noqa: E712 (NaN-safe)
    ranked = ranked.drop_duplicates(["country", "name"])  # one share class per company (GOOG/GOOGL, FOX/FOXA)
    return ranked.groupby(["country", "sector"], group_keys=False).head(n)


def save_results(df: pd.DataFrame) -> None:
    """Write results, keeping previously saved rows for countries this run didn't cover."""
    df = df.assign(generated_at=df.attrs.get("generated_at"))
    existing = load_results()
    if existing is not None:
        df = pd.concat([existing[~existing["country"].isin(df["country"].unique())], df], ignore_index=True)
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS_FILE, index=False)


def load_results() -> pd.DataFrame | None:
    if not RESULTS_FILE.exists():
        return None
    df = pd.read_csv(RESULTS_FILE)
    df["eligible"] = df["eligible"].astype(str).str.lower() == "true"
    return df
