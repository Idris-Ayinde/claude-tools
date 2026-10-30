"""Rule-based assistant: answers questions from the screen results with pattern matching, no AI model."""
import difflib
import json
import re
from dataclasses import dataclass, field

import pandas as pd

from . import explain
from .config import COUNTRIES
from .formatting import compact, money, pct, valuation_label
from .glossary import GLOSSARY
from .scoring import CAPITAL_HEAVY

EXAMPLES = [
    "Best cheap tech stocks in the USA",
    "Why is DECK ranked so high?",
    "Compare AAPL and MSFT",
    "Top 5 Canadian banks",
    "What is a margin of safety?",
    "Low debt utilities",
]

SECTOR_WORDS = {
    "Information Technology": ["tech", "technology", "software", "semiconductor", "semiconductors", "chip", "chips"],
    "Financials": ["bank", "banks", "financial", "financials", "insurance", "insurer", "insurers"],
    "Health Care": ["health", "healthcare", "health care", "pharma", "pharmaceutical", "biotech", "medical"],
    "Energy": ["energy", "oil", "gas", "pipeline", "pipelines"],
    "Utilities": ["utility", "utilities"],
    "Real Estate": ["real estate", "reit", "reits", "property", "properties"],
    "Materials": ["materials", "mining", "miner", "miners", "gold", "chemical", "chemicals"],
    "Industrials": ["industrial", "industrials", "railroad", "railway", "aerospace", "defense", "manufacturing"],
    "Consumer Staples": ["staples", "consumer staples", "food", "beverage", "beverages", "grocery"],
    "Consumer Discretionary": ["discretionary", "consumer discretionary", "retail", "retailer", "retailers",
                               "restaurant", "restaurants", "apparel", "automaker", "automakers"],
    "Communication Services": ["communication", "communications", "telecom", "telecoms", "media"],
}
COUNTRY_WORDS = {
    "USA": ["usa", "u.s.", "u.s", "america", "american", "united states", "s&p", "s&p 500"],
    "Canada": ["canada", "canadian", "tsx", "toronto"],
}
# Glossary phrases, longest/most specific first so "margin of safety" wins over "margin".
TERMS = [
    (["margin of safety"], "Margin of safety"),
    (["intrinsic value", "estimated value", "fair value"], "Intrinsic value"),
    (["free cash flow", "fcf", "owner earnings"], "Free cash flow (FCF)"),
    (["return on equity", "roe"], "Return on equity (ROE)"),
    (["return on assets", "roa"], "Return on assets (ROA)"),
    (["debt to equity", "debt/equity", "d/e"], "Debt/Equity"),
    (["net margin", "profit margin", "margin"], "Net margin"),
    (["p/e", "pe ratio", "price to earnings", "price-to-earnings"], "P/E ratio"),
    (["cagr", "compound annual growth"], "CAGR"),
    (["moat", "moats"], "Moat"),
    (["buffett score", "score"], "Buffett score"),
]
# For "what's X's <metric>?" we answer with the matching plain-English reason.
METRIC_HINTS = [
    (["margin of safety", "cheap", "expensive", "undervalued", "overvalued", "worth", "value", "price"], "estimate"),
    (["roe", "return on equity"], "shareholders invested"),
    (["debt", "leverage", "d/e"], "debt"),
    (["free cash flow", "fcf", "cash flow"], "free cash flow"),
    (["margin"], "of sales"),
    (["p/e", "pe", "earnings multiple"], "P/E"),
    (["growth", "growing", "grow"], "Profits"),
]
CHEAP_WORDS = ["cheap", "cheapest", "undervalued", "bargain", "bargains", "discount", "discounted", "below value"]
EXPENSIVE_WORDS = ["expensive", "overvalued", "pricey"]
NOT_TICKERS = {"I", "A", "US", "USA", "TSX", "ROE", "ROA", "PE", "FCF", "CAGR", "DCF", "CEO", "AI", "IT", "OK", "S", "P",
               "E", "THE", "AND", "OR", "VS", "MY", "IS", "ME"}
NAME_SUFFIXES = re.compile(r"\b(inc|incorporated|corp|corporation|co|company|ltd|limited|plc|holdings|group|the|"
                           r"trust|fund|real estate investment trust|class [a-z])\b\.?", re.I)
AMBIGUOUS_FIRST_WORDS = {"american", "general", "first", "united", "national", "international", "royal", "canadian",
                         "bank", "global", "great", "new", "south", "north", "west", "east", "pacific", "power", "energy",
                         "capital", "the", "public", "standard", "western", "eastern", "brookfield",
                         # everyday question words that are also first words of company names (Best Buy, Target...)
                         "best", "target", "show", "tell", "find", "about", "stock", "stocks", "cheap", "strong",
                         "quality", "compare", "which", "what", "with", "most", "high", "lowest", "growth", "value",
                         "price", "free", "news", "home", "life", "health", "well", "five", "four", "three"}


@dataclass
class Reply:
    text: str
    table: pd.DataFrame | None = None
    tickers: list[str] = field(default_factory=list)  # stocks the UI can offer "open details" for


def _has(text: str, words) -> bool:
    return any(re.search(rf"(?<![\w$]){re.escape(w)}(?![\w])", text) for w in words)


def _simple_name(name: str) -> str:
    return re.sub(r"\s+", " ", NAME_SUFFIXES.sub(" ", re.sub(r"[,.&']", " ", name.lower()))).strip()


def find_stocks(question: str, df: pd.DataFrame) -> list[str]:
    """Tickers mentioned in the question, in the order they appear."""
    lower = question.lower()
    tickers = set(df["ticker"])
    prefer_canada = _has(lower, COUNTRY_WORDS["Canada"])
    hits: list[tuple[int, str]] = []

    # 1. Tickers typed in capitals or with a $ (so "low debt" never matches the ticker LOW).
    for m in re.finditer(r"\$?[A-Za-z][A-Za-z0-9.\-]{0,9}", question):
        raw = m.group().rstrip(".")
        token = raw.lstrip("$")
        if not raw.startswith("$") and (not token.isupper() or token in NOT_TICKERS):
            continue
        t = token.upper()
        if t.endswith(".TO"):
            candidates = [t[:-3].replace(".", "-") + ".TO"]
        else:
            base = t.replace(".", "-")
            candidates = [base + ".TO", base] if prefer_canada else [base, base + ".TO"]
        match = next((c for c in candidates if c in tickers), None)
        if match:
            hits.append((m.start(), match))

    # 2. Company names: the full name ("royal bank of canada"), else a distinctive first word ("deckers").
    names = {_simple_name(n): t for t, n in zip(df["ticker"], df["name"]) if isinstance(n, str)}
    for name, ticker in sorted(names.items(), key=lambda kv: -len(kv[0])):
        if len(name) >= 4:
            m = re.search(rf"\b{re.escape(name)}\b", lower)
            if m and not any(t == ticker for _, t in hits):
                hits.append((m.start(), ticker))
    first_words: dict[str, list[str]] = {}
    for name, ticker in names.items():
        word = name.split(" ")[0] if name else ""
        if len(word) >= 4 and word not in AMBIGUOUS_FIRST_WORDS:
            first_words.setdefault(word, []).append(ticker)
    for word, owners in first_words.items():
        unique = {t.removesuffix(".TO") for t in owners}
        if len(unique) == 1:
            m = re.search(rf"\b{re.escape(word)}('s)?\b", lower)
            if m and not any(t in owners for _, t in hits):
                hits.append((m.start(), owners[0]))

    ordered, seen = [], set()
    for _, t in sorted(hits):
        if t not in seen:
            ordered.append(t)
            seen.add(t)
    return ordered


def _row(df: pd.DataFrame, ticker: str) -> dict:
    row = df[df["ticker"] == ticker].iloc[0].to_dict()
    return {k: (None if isinstance(v, float) and v != v else v) for k, v in row.items()}


def _stock_line(row: dict) -> str:
    label = valuation_label(row.get("margin_of_safety"))
    return (f"**{row['name']} ({row['ticker']})**: Buffett score **{row['score']:.0f}/100**, "
            f"{row['checklist']:.0f}/6 rules passed. Price {money(row['price'], row['currency'])} vs. estimated value "
            f"{money(row.get('intrinsic_value'), row['currency'])} ({label}).")


def _explain_stock(df: pd.DataFrame, ticker: str, lower: str) -> Reply:
    row = _row(df, ticker)
    if not row.get("eligible"):
        return Reply(f"I screened **{row['name']} ({ticker})** but couldn't score it: {row.get('reason') or 'not enough data'}.")
    details = json.loads(row["details"])
    reasons = explain.reasons(row, details)
    icon = {True: "✅", False: "❌", None: "➖"}
    for words, needle in METRIC_HINTS:
        if _has(lower, words):
            focused = [r for r in reasons if needle.lower() in r.text.lower()]
            if focused:
                return Reply(f"{_stock_line(row)}\n\n" + "\n".join(f"- {icon[r.passed]} {r.text}" for r in focused),
                             tickers=[ticker])
    rank = _rank(df, row)
    return Reply(f"{_stock_line(row)}{rank}\n\n**{explain.verdict(row, details)}**\n\n"
                 + "\n".join(f"- {icon[r.passed]} {r.text}" for r in reasons), tickers=[ticker])


def _rank(df: pd.DataFrame, row: dict) -> str:
    peers = df[(df["country"] == row["country"]) & (df["sector"] == row["sector"]) & (df["eligible"] == True)]  # noqa: E712
    peers = peers.drop_duplicates("name").sort_values("score", ascending=False).reset_index(drop=True)
    position = peers.index[peers["ticker"] == row["ticker"]]
    if len(position) == 0:
        return ""
    return f" It ranks **#{position[0] + 1} of {len(peers)}** in {row['country']} {row['sector']}."


def _compare(df: pd.DataFrame, tickers: list[str]) -> Reply:
    rows = [_row(df, t) for t in tickers[:4]]
    metrics = {
        "Buffett score": lambda r: f"{r['score']:.0f}" if r.get("score") is not None else "n/a",
        "Rules passed": lambda r: f"{r['checklist']:.0f}/6" if r.get("checklist") is not None else "n/a",
        "Price": lambda r: money(r.get("price"), r.get("currency")),
        "Estimated value": lambda r: money(r.get("intrinsic_value"), r.get("currency")),
        "Valuation": lambda r: valuation_label(r.get("margin_of_safety")).title(),
        "Avg ROE": lambda r: pct(r.get("roe_avg")),
        "Debt/Equity": lambda r: "n/a" if r.get("debt_to_equity") is None else f"{r['debt_to_equity']:.2f}",
        "Net margin": lambda r: pct(r.get("net_margin")),
        "P/E": lambda r: "n/a" if r.get("pe") is None else f"{r['pe']:.1f}",
        "Market cap": lambda r: compact(r.get("market_cap"), r.get("currency")),
        "Sector": lambda r: r["sector"],
    }
    table = pd.DataFrame({r["ticker"]: {k: f(r) for k, f in metrics.items()} for r in rows})
    scored = [r for r in rows if r.get("score") is not None]
    text = "Here's how they compare."
    if len(scored) >= 2:
        best = max(scored, key=lambda r: r["score"])
        cheapest = max((r for r in scored if r.get("margin_of_safety") is not None),
                       key=lambda r: r["margin_of_safety"], default=None)
        text = f"**{best['name']} ({best['ticker']})** fits Buffett's rules best, with a score of {best['score']:.0f}."
        if cheapest and cheapest["margin_of_safety"] > 0:
            text += (f" **{cheapest['ticker']}** has the biggest discount to its estimated value "
                     f"({pct(cheapest['margin_of_safety'])} margin of safety).")
        elif cheapest:
            text += (" None of them trades below its estimated value; "
                     f"**{cheapest['ticker']}** is the closest.")
    return Reply(text, table=table, tickers=[r["ticker"] for r in rows])


def _screen(df: pd.DataFrame, lower: str) -> Reply | None:
    sectors = [s for s, words in SECTOR_WORDS.items() if _has(lower, words)]
    countries = [c for c, words in COUNTRY_WORDS.items() if _has(lower, words)]
    cheap, expensive = _has(lower, CHEAP_WORDS), _has(lower, EXPENSIVE_WORDS)
    low_debt = _has(lower, ["low debt", "little debt", "no debt", "debt free", "debt-free"])
    high_roe = _has(lower, ["high roe", "high return"])
    strong = _has(lower, ["strong", "quality", "high quality", "high-quality", "wonderful"])
    worst = _has(lower, ["worst", "lowest", "weakest"])
    asks_for_list = _has(lower, ["stock", "stocks", "pick", "picks", "best", "top", "ideas", "companies", "list",
                                 "show", "find", "recommend", "worst", "lowest"])
    if not (sectors or countries or cheap or expensive or low_debt or high_roe or asks_for_list):
        return None

    n_match = re.search(r"\b(?:top|best|worst)\s+(\d{1,2})\b|\b(\d{1,2})\s+(?:stocks|picks|companies)\b", lower)
    n = min(25, int(next(g for g in n_match.groups() if g))) if n_match else 5

    data = df[df["eligible"] == True].drop_duplicates(["country", "name"])  # noqa: E712
    if sectors:
        data = data[data["sector"].isin(sectors)]
    if countries:
        data = data[data["country"].isin(countries)]
    if cheap:
        data = data[data["margin_of_safety"] >= 0.15]
    if expensive:
        data = data[data["margin_of_safety"] <= -0.10]
    if low_debt:  # same limits as the score: 0.5, or 1.0 for asset-heavy sectors; banks are judged on ROA instead
        limit = data["sector"].map(lambda s: 1.0 if s in CAPITAL_HEAVY else 0.5)
        data = data[(data["debt_to_equity"] <= limit) | (data["sector"] == "Financials")]
    if high_roe:
        data = data[data["roe_avg"] >= 0.15]
    if strong:
        data = data[data["score"] >= 80]
    most_overpriced = expensive and _has(lower, ["most expensive", "most overvalued", "most overpriced"])
    if most_overpriced:
        data = data.sort_values("margin_of_safety").head(n)
    else:
        data = data.sort_values("score", ascending=worst).head(n)

    parts = [w for w, on in (("cheap", cheap), ("expensive", expensive and not most_overpriced), ("low-debt", low_debt),
                              ("high-ROE", high_roe), ("strong", strong)) if on]
    what = " ".join(parts + [" & ".join(sectors)] if sectors else parts)
    what = f"{what} " if what else ""
    where = " and ".join("the USA" if c == "USA" else c for c in countries) if countries else "the USA and Canada"
    if data.empty:
        return Reply(f"I couldn't find any {what}stocks in {where}. Try removing a filter, "
                     "for example drop \"cheap\" or pick a broader sector.")
    table = pd.DataFrame({
        "Ticker": data["ticker"],
        "Company": data["name"],
        "Sector": data["sector"],
        "Score": data["score"].round(0).astype(int),
        "Price": [money(p, c) for p, c in zip(data["price"], data["currency"])],
        "Est. value": [money(v, c) for v, c in zip(data["intrinsic_value"], data["currency"])],
        "Valuation": [valuation_label(m).title() for m in data["margin_of_safety"]],
    }).reset_index(drop=True)
    if most_overpriced:
        text = f"Here are the {len(data)} most overpriced {what}stocks in {where}, compared with their estimated value."
    else:
        order = "lowest" if worst else "highest"
        text = (f"Here {'is' if len(data) == 1 else 'are'} the {len(data)} {order}-scoring {what}stocks in {where}"
                f"{', ranked by Buffett score' if len(data) > 1 else ''}.")
    if _has(lower, ["dividend", "dividends", "yield"]):
        text += " (I don't track dividends yet, so I ignored that part.)"
    return Reply(text, table=table, tickers=list(data["ticker"]))


def _define(lower: str) -> Reply | None:
    for words, term in TERMS:
        if _has(lower, words):
            return Reply(f"**{term}**: {GLOSSARY[term]}")
    return None


def _help() -> Reply:
    return Reply("I'm a simple assistant that answers from Moat Finder's own screen results, with no AI involved. "
                 "I can:\n- explain any stock: *\"Why is DECK ranked so high?\"*\n"
                 "- compare stocks: *\"Compare AAPL and MSFT\"*\n"
                 "- find stocks: *\"Top 5 cheap tech stocks in the USA\"*, *\"Low debt utilities\"*\n"
                 "- define terms: *\"What is ROE?\"*\n- count things: *\"How many strong stocks are there?\"*\n\n"
                 "Tip: type tickers in capitals (AAPL, RY.TO) or use the company name.")


def _counts(df: pd.DataFrame, lower: str) -> Reply:
    data = df[df["eligible"] == True]  # noqa: E712
    countries = [c for c, words in COUNTRY_WORDS.items() if _has(lower, words)] or list(COUNTRIES)
    data = data[data["country"].isin(countries)]
    strong = data[data["score"] >= 80]
    cheap = data[data["margin_of_safety"] >= 0.15]
    both = strong[strong["margin_of_safety"] >= 0.15]
    where = " and ".join("the USA" if c == "USA" else c for c in countries)
    return Reply(f"In {where} I ranked **{len(data)}** stocks: **{len(strong)}** strong (score 80+), "
                 f"**{len(cheap)}** cheap (15%+ below estimated value), and **{len(both)}** that are both.")


def answer(question: str, df: pd.DataFrame) -> Reply:
    question = question.strip()
    lower = question.lower()
    if not question:
        return _help()
    if re.fullmatch(r"(hi|hello|hey|yo|help|\?|what can you do\??|how does this work\??)[!. ]*", lower):
        return _help()

    stocks = find_stocks(question, df)
    asks_definition = re.search(r"\b(what is|what's|what are|whats|define|definition|meaning of|mean)\b", lower)
    if asks_definition and not stocks:
        definition = _define(lower)
        if definition:
            return definition
    if len(stocks) >= 2:
        return _compare(df, stocks)
    if len(stocks) == 1:
        return _explain_stock(df, stocks[0], lower)
    if re.search(r"\bhow many\b", lower):
        return _counts(df, lower)
    screened = _screen(df, lower)
    if screened:
        return screened
    definition = _define(lower)
    if definition:
        return definition

    # Maybe a misspelled company name.
    names = {_simple_name(n): t for t, n in zip(df["ticker"], df["name"]) if isinstance(n, str)}
    words = re.findall(r"[a-z]{4,}", lower)
    for word in words:
        close = difflib.get_close_matches(word, [n.split(" ")[0] for n in names], n=1, cutoff=0.85)
        if close:
            ticker = next(t for n, t in names.items() if n.split(" ")[0] == close[0])
            return _explain_stock(df, ticker, lower)
    return Reply("Sorry, I didn't catch that. I'm rule-based, so I understand a few kinds of questions:\n"
                 + "\n".join(f"- *{e}*" for e in EXAMPLES))
