from dataclasses import asdict

from buffett import explain
from buffett.formatting import compact, debt_label, money, roe_label, score_tier, valuation_label
from buffett.scoring import score
from tests.test_scoring import wonderful


def test_money_and_compact():
    assert money(247.221, "USD") == "$247.22 USD"
    assert money(288.21, "CAD") == "CA$288.21"
    assert money(None, "USD") == "n/a"
    assert compact(5_092_060_000_000, "USD") == "$5.1T"
    assert compact(-2.5e9, "CAD") == "-CA$2.5B"
    assert compact(1.2e9) == "1.2B"


def test_labels():
    assert roe_label(0.18) == "strong" and roe_label(0.12) == "fair" and roe_label(0.02) == "weak"
    assert debt_label(0.3) == "low" and debt_label(0.8, capital_heavy=True) == "low" and debt_label(1.5) == "high"
    assert score_tier(85) == "strong" and score_tier(65) == "moderate" and score_tier(40) == "weak"
    assert valuation_label(0.2) == "cheap" and valuation_label(0.0) == "fair" and valuation_label(-0.3) == "expensive"


def _row_and_details(f):
    result = score(f)
    row = {"sector": f.sector, "roe_avg": result.metrics["roe_avg"], "debt_to_equity": f.debt_to_equity, "roa": f.roa,
           "net_margin": result.metrics["net_margin"], "earnings_cagr": result.metrics["ni_cagr"],
           "margin_of_safety": result.margin_of_safety, "intrinsic_value": result.intrinsic_value,
           "price": f.price, "currency": f.currency, "pe": f.pe}
    details = {"criteria": [asdict(c) for c in result.criteria], "checklist": result.checklist,
               "history": {k: {str(y): v for y, v in s.items()} for k, s in f.history.items()},
               "growth_used": result.metrics["growth_used"]}
    return row, details


def test_wonderful_business_reasons_all_pass():
    row, details = _row_and_details(wonderful())
    reasons = explain.reasons(row, details)
    assert reasons and all(r.passed for r in reasons)
    assert any("$0.15" in r.text for r in reasons)
    assert explain.verdict(row, details).startswith("A high-quality business")


def test_reasons_use_last_ten_years_only():
    f = wonderful()
    f.history = {k: {y - 10: v for y, v in s.items()} | s for k, s in f.history.items()}  # 20 years of data
    row, details = _row_and_details(f)
    assert any("each of the last 10 years" in r.text for r in explain.reasons(row, details))


def test_expensive_stock_has_no_margin_of_safety():
    f = wonderful()
    f.price = 10_000.0
    row, details = _row_and_details(f)
    texts = [r.text for r in explain.reasons(row, details) if r.passed is False]
    assert any("× our estimate" in t and "no margin of safety" in t for t in texts)
    assert "priced above" in explain.verdict(row, details)
