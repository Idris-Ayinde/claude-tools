"""Plain-English definitions shared by the dashboard tooltips, the Guide tab and the chat assistant."""

HELP = {
    "score": "0–100: how well the stock fits Buffett's rules (business quality + price). 80+ is strong.",
    "checklist": "How many of Buffett's 6 core rules the stock fully passes.",
    "intrinsic_value": "Our estimate of what one share of the business is worth, from its future cash flows.",
    "margin_of_safety": "How far the price is below the estimated value. Positive = a discount; negative = paying more than it's worth.",
    "roe": "Return on equity: yearly profit per $1 shareholders have invested. Buffett wants 15% or more.",
    "debt_to_equity": "Debt for every $1 of shareholders' equity. Lower is safer; Buffett prefers under 0.5.",
    "net_margin": "Share of every sales dollar kept as profit. 10%+ suggests pricing power.",
    "pe": "Price-to-earnings: what you pay for $1 of yearly profit. Lower is cheaper; 15 or less is value territory.",
    "earnings_cagr": "Average yearly growth of profits over the years of data available.",
}

GLOSSARY = {
    "Moat": "A lasting competitive advantage (brand, scale, patents, network) that protects a business's profits, "
            "like a moat protects a castle.",
    "Return on equity (ROE)": HELP["roe"],
    "Return on assets (ROA)": "Yearly profit per $1 of everything a company owns. Used for banks and insurers, "
                              "where borrowing is part of the business. 1%+ is strong.",
    "Debt/Equity": HELP["debt_to_equity"] + " Utilities and real estate naturally carry more debt (up to 1.0).",
    "Net margin": HELP["net_margin"],
    "Free cash flow (FCF)": "Cash left after running the business and paying for new equipment. "
                            "Buffett calls this 'owner earnings'.",
    "Intrinsic value": HELP["intrinsic_value"],
    "Margin of safety": HELP["margin_of_safety"] + " Buffett insists on one because every estimate can be wrong.",
    "P/E ratio": HELP["pe"],
    "CAGR": "Compound annual growth rate: the steady yearly growth that gets you from the first value to the last.",
    "Buffett score": HELP["score"],
}
