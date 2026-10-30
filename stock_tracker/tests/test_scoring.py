import pytest

from buffett.fundamentals import Fundamentals, build, merge_history
from buffett.http import parse_number
from buffett.scoring import cagr, dcf_value, ramp, score
from buffett.sources import finviz, google_finance, sec_edgar


def years(values, start=2016):
    return {start + i: v for i, v in enumerate(values)}


def company(sector="Information Technology", **history):
    return Fundamentals(ticker="TEST", name="Test Co", country="USA", sector=sector, price=50.0,
                        currency="USD", pe=12.0, shares=1e9, market_cap=50e9, debt_to_equity=0.2,
                        roa=0.015, history=history)


def wonderful():
    return company(
        net_income=years([5e9 * 1.1 ** i for i in range(10)]),
        revenue=years([20e9 * 1.1 ** i for i in range(10)]),
        equity=years([20e9 * 1.1 ** i for i in range(10)]),
        total_debt=years([4e9] * 10),
        fcf=years([5e9 * 1.1 ** i for i in range(10)]),
    )


def test_ramp_both_directions():
    assert ramp(0.15, 0.05, 0.15) == 1.0
    assert ramp(0.10, 0.05, 0.15) == pytest.approx(0.5)
    assert ramp(0.75, 1.0, 0.5) == pytest.approx(0.5)  # lower is better
    assert ramp(None, 0, 1) is None


def test_cagr():
    assert cagr([100, 110, 121]) == pytest.approx(0.10)
    steady = [100 * 1.1 ** i for i in range(10)]
    assert cagr(steady) == pytest.approx(0.10)
    # A one-off bad first year no longer explodes the growth rate.
    assert cagr([1] + steady[1:]) < 0.25
    assert cagr([100, 110]) is None
    assert cagr([-1, 5, 10]) is None


def test_dcf_no_growth_matches_perpetuity_when_growth_equals_terminal():
    # Constant growth g == terminal: value equals the Gordon growth model base*(1+g)/(r-g).
    assert dcf_value(100, 0.025, discount=0.10, terminal=0.025) == pytest.approx(100 * 1.025 / 0.075)


def test_wonderful_business_scores_high():
    result = score(wonderful())
    assert result.eligible
    assert result.score > 85
    assert all(result.checklist.values())
    assert result.margin_of_safety > 0


def test_poor_business_scores_low():
    f = company(
        net_income=years([1e9, -2e9, 0.5e9, -1e9, 0.2e9]),
        revenue=years([30e9] * 5),
        equity=years([20e9] * 5),
        total_debt=years([40e9] * 5),
        fcf=years([-1e9, 0.5e9, -2e9, -1e9, 0.1e9]),
    )
    f.debt_to_equity, f.pe = 2.0, 80.0
    result = score(f)
    assert result.score < 25
    assert result.checklist["Low debt"] is False


def test_financials_skip_fcf_and_use_roa():
    f = wonderful()
    f.sector = "Financials"
    result = score(f)
    by_key = {c.key: c for c in result.criteria}
    assert by_key["fcf_positive"].value is None
    assert "ROA" in by_key["debt"].detail


def test_negative_equity_uses_debt_to_earnings():
    f = wonderful()
    f.history["equity"] = years([-1e9] * 10)
    f.debt_to_equity = None
    by_key = {c.key: c for c in score(f).criteria}
    assert by_key["roe_level"].value is None
    assert "yrs of earnings" in by_key["debt"].detail


def test_short_history_is_not_eligible():
    f = company(net_income=years([1e9, 2e9]), revenue=years([5e9, 6e9]))
    result = score(f)
    assert not result.eligible
    assert "years" in result.reason


def test_currency_conversion_scales_intrinsic_value():
    usd = score(wonderful())
    f = wonderful()
    f.fx = 1.4  # e.g. reports in USD, trades in CAD
    assert score(f).intrinsic_value == pytest.approx(usd.intrinsic_value * 1.4)


def test_merge_history_prefers_longest_series():
    short = {"net_income": {"2024": 1.0, "2025": 2.0}}
    long = {"net_income": {str(y): 10.0 for y in range(2015, 2025)}}
    merged = merge_history(short, long)["net_income"]
    assert merged[2024] == 10.0 and merged[2025] == 2.0 and len(merged) == 11


def test_build_uses_median_price_and_flags_outliers():
    yahoo = {"info": {"price": 100.0, "pe": 20.0, "market_cap": 1e11}, "history": {"net_income": {"2025": 5e9}}}
    f = build({"ticker": "X", "name": "X", "country": "USA", "sector": "Energy"}, yahoo,
              google={"price": 101.0, "pe": 0.01}, finviz={"price": 150.0, "pe": 21.0})
    assert f.price == 101.0
    assert any("Price" in w for w in f.warnings)
    assert f.pe == 20.0


def test_parse_number():
    assert parse_number("CA$1,116.41") == pytest.approx(1116.41)
    assert parse_number("148.75%") == pytest.approx(1.4875)
    assert parse_number("5.09T") == pytest.approx(5.09e12)
    assert parse_number("-") is None


def test_sec_annual_values_keeps_full_years_and_latest_filing():
    entries = [
        {"start": "2023-01-01", "end": "2023-12-31", "val": 10, "form": "10-K", "filed": "2024-02-01"},
        {"start": "2023-01-01", "end": "2023-12-31", "val": 11, "form": "10-K", "filed": "2025-02-01"},  # restated
        {"start": "2023-10-01", "end": "2023-12-31", "val": 3, "form": "10-K", "filed": "2024-02-01"},  # quarter
        {"start": "2024-01-01", "end": "2024-12-31", "val": 20, "form": "10-Q", "filed": "2025-01-01"},
    ]
    assert sec_edgar.annual_values(entries, instant=False) == {"2023": 11.0}


def test_google_symbol_mapping():
    assert google_finance.google_symbol("BRK-B", "NYQ") == "BRK.B:NYSE"
    assert google_finance.google_symbol("AAPL", "NMS") == "AAPL:NASDAQ"
    assert google_finance.google_symbol("RCI-B.TO", "TOR") == "RCI.B:TSE"


def test_google_parse_picks_quote_price_not_index_ticker():
    html = """<span jsname="Pdsbrc"><span>1,116.41</span></span>
    <div class="gO24Ff">Royal Bank of Canada</div><span jsname="Pdsbrc"><span>CA$288.21</span></span>
    <div class="KxsRFb"><div>P/E ratio</div><div>18.16</div></div>"""
    assert google_finance.parse(html) == {"price": 288.21, "pe": 18.16}


def test_finviz_parse_reads_all_tables():
    html = """<table class="snapshot-table2"><tr><td>Index</td><td>S&P 500</td></tr></table>
    <table class="snapshot-table2"><tr><td>P/E</td><td>13.24</td><td>ROE</td><td>16.91%</td></tr></table>"""
    data = finviz.parse(html)
    assert data["pe"] == 13.24 and data["roe"] == pytest.approx(0.1691)


def test_top_picks_keeps_one_share_class_per_company():
    import pandas as pd
    from buffett.pipeline import top_picks
    df = pd.DataFrame({
        "country": ["USA"] * 3, "sector": ["Communication Services"] * 3,
        "ticker": ["GOOGL", "GOOG", "META"], "name": ["Alphabet Inc.", "Alphabet Inc.", "Meta Platforms, Inc."],
        "score": [79.0, 79.5, 70.0], "eligible": [True] * 3,
    })
    assert list(top_picks(df)["ticker"]) == ["GOOG", "META"]
