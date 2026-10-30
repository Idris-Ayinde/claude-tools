import pandas as pd
import pytest

from buffett.chat import answer, find_stocks
from tests.test_presentation import _row_and_details
from tests.test_scoring import wonderful

COMPANIES = [
    # ticker, name, country, sector, score, margin of safety, debt/equity
    ("DECK", "Deckers Outdoor Corporation", "USA", "Consumer Discretionary", 98, 0.44, 0.2),
    ("BBY", "Best Buy Co., Inc.", "USA", "Consumer Discretionary", 40, -0.5, 1.4),
    ("AAPL", "Apple Inc.", "USA", "Information Technology", 65, -1.8, 0.8),
    ("MSFT", "Microsoft Corporation", "USA", "Information Technology", 74, -1.9, 0.3),
    ("ADBE", "Adobe Inc.", "USA", "Information Technology", 96, 0.41, 0.6),
    ("RY.TO", "Royal Bank of Canada", "Canada", "Financials", 59, -0.3, None),
    ("FFH.TO", "Fairfax Financial Holdings Limited", "Canada", "Financials", 98, 0.36, None),
    ("ATO", "Atmos Energy Corporation", "USA", "Utilities", 54, -0.2, 0.7),
    ("LOW", "Lowe's Companies, Inc.", "USA", "Consumer Discretionary", 50, -0.4, 3.0),
]


@pytest.fixture(scope="module")
def df():
    rows = []
    for ticker, name, country, sector, score, mos, de in COMPANIES:
        f = wonderful()
        f.sector = sector
        row, details = _row_and_details(f)
        import json
        row.update(ticker=ticker, name=name, country=country, score=float(score), margin_of_safety=mos,
                   debt_to_equity=de, eligible=True, checklist=4.0, market_cap=1e11, details=json.dumps(details))
        rows.append(row)
    return pd.DataFrame(rows)


def test_finds_tickers_names_and_ignores_question_words(df):
    assert find_stocks("Compare AAPL and MSFT", df) == ["AAPL", "MSFT"]
    assert find_stocks("tell me about royal bank of canada", df) == ["RY.TO"]
    assert find_stocks("is fairfax cheap?", df) == ["FFH.TO"]
    assert find_stocks("RY", df) == ["RY.TO"]
    assert find_stocks("Best cheap tech stocks", df) == []        # "best" is not Best Buy
    assert find_stocks("show me low debt stocks", df) == []        # lowercase "low" is not the ticker LOW
    assert find_stocks("$LOW", df) == ["LOW"]


def test_explains_a_single_stock(df):
    reply = answer("Why is DECK ranked so high?", df)
    assert "Deckers" in reply.text and "ranks **#1" in reply.text and reply.tickers == ["DECK"]


def test_focuses_on_the_metric_asked_about(df):
    reply = answer("what's MSFT's debt?", df)
    assert "debt" in reply.text and "shareholders invested" not in reply.text


def test_compare_says_when_nothing_is_cheap(df):
    reply = answer("Compare AAPL and MSFT", df)
    assert reply.table is not None and list(reply.table.columns) == ["AAPL", "MSFT"]
    assert "None of them trades below" in reply.text


def test_screen_with_filters(df):
    reply = answer("Best cheap tech stocks in the USA", df)
    assert list(reply.table["Ticker"]) == ["ADBE"]
    assert "the USA" in reply.text
    assert list(answer("Top 5 Canadian banks", df).table["Ticker"]) == ["FFH.TO", "RY.TO"]
    assert list(answer("Low debt utilities", df).table["Ticker"]) == ["ATO"]  # 0.7 is low for a utility


def test_definitions_counts_help_and_fallback(df):
    assert answer("What is a margin of safety?", df).text.startswith("**Margin of safety**")
    assert "ranked **9**" in answer("how many strong stocks are there?", df).text
    assert "I can:" in answer("hi", df).text
    assert "didn't catch that" in answer("blah blah", df).text
