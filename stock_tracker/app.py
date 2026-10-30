"""Moat Finder dashboard: `streamlit run app.py`."""
import base64
import re
import html
import json
import random
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from buffett import chat, explain
from buffett.config import COUNTRIES, DISCOUNT_RATE, FMP_API_KEY, MAX_GROWTH, PROJECTION_YEARS, SECTORS, TERMINAL_GROWTH
from buffett.glossary import GLOSSARY, HELP
from buffett.formatting import (compact, debt_label, margin_label, missing, money, pct, roe_label, score_tier,
                                valuation_label)
from buffett.pipeline import load_results, run_screen, save_results, top_picks
from buffett.scoring import CAPITAL_HEAVY, FINANCIALS, MAX_HISTORY_YEARS
from buffett.sources.google_finance import google_symbol

APP_NAME = "Moat Finder"
st.set_page_config(page_title=APP_NAME, page_icon=str(Path(__file__).parent / "assets" / "logo.svg"), layout="wide")

# Chart and card colours (light and dark steps of the same palette).
THEMES = {
    "light": {"ink": "#141413", "ink2": "#3d3d3a", "muted": "#87867f", "grid": "#e8e6dc", "axis": "#cfccc0",
              "series": "#2a78d6", "card": "#ffffff", "border": "rgba(20,20,19,0.10)", "neutral": "#e8e6dc",
              "accent": "#d97757", "page": "#faf9f5", "shadow": "rgba(20,20,19,0.08)", "track": "#cde2fb"},
    "dark": {"ink": "#f0eee6", "ink2": "#c9c7bd", "muted": "#9a988f", "grid": "#3d3c38", "axis": "#4a4945",
             "series": "#3987e5", "card": "#2b2a27", "border": "rgba(255,255,255,0.10)", "neutral": "#3d3c38",
             "accent": "#e08a6c", "page": "#1f1e1d", "shadow": "rgba(0,0,0,0.35)", "track": "#184f95"},
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a"}
VALUATION_CHIPS = {
    "cheap": (STATUS["good"], "Cheap"),
    "fair": (None, "Fair price"),
    "expensive": (STATUS["serious"], "Expensive"),
    "n/a": (None, "No estimate"),
}
HISTORY_LABELS = {"revenue": "Revenue", "net_income": "Net income (profit)", "fcf": "Free cash flow",
                  "equity": "Shareholders' equity", "total_debt": "Total debt"}
STATUS_ICONS = {True: "✅", False: "❌", None: "➖"}
ASSETS = Path(__file__).parent / "assets"
SERIF = '"Source Serif", "Source Serif 4", Georgia, serif'


def md(text: str) -> str:
    """Escape $ so prices like "$82 vs $147" aren't rendered as a LaTeX formula by st.markdown."""
    return text.replace("$", "\\$")


# Illustration colours re-mapped for dark mode (cream backdrops would glow on a dark page).
DARK_ILLUSTRATION = {"#f0eee6": "#2b2a27", "#ffffff": "#33322e", "#141413": "#e8e6dc", "#e3dacc": "#4a443d",
                     "#cfdde3": "#23384a"}


def illustration(name: str, width: str = "100%", alt: str = "") -> str:
    """Inline an SVG from assets/ as an <img>, so its own animations run and its styles stay contained."""
    svg = (ASSETS / f"{name}.svg").read_text()
    if active_scheme() == "dark":
        for light, dark in DARK_ILLUSTRATION.items():
            svg = svg.replace(light, dark)
    data = base64.b64encode(svg.encode()).decode()
    return f'<img src="data:image/svg+xml;base64,{data}" alt="{html.escape(alt)}" style="width:{width};height:auto;display:block">'

COLUMNS = {
    "ticker": st.column_config.TextColumn("Ticker"),
    "name": st.column_config.TextColumn("Company", width="medium"),
    "sector": st.column_config.TextColumn("Sector"),
    "score": st.column_config.ProgressColumn("Buffett score", min_value=0, max_value=100, format="%.0f", help=HELP["score"]),
    "checklist": st.column_config.NumberColumn("Checklist", format="%d/6", help=HELP["checklist"]),
    "price": st.column_config.NumberColumn("Price", format="%.2f"),
    "intrinsic_value": st.column_config.NumberColumn("Est. value", format="%.2f", help=HELP["intrinsic_value"]),
    "margin_of_safety": st.column_config.NumberColumn("Margin of safety", format="percent", help=HELP["margin_of_safety"]),
    "pe": st.column_config.NumberColumn("P/E", format="%.1f", help=HELP["pe"]),
    "roe_avg": st.column_config.NumberColumn("Avg ROE", format="percent", help=HELP["roe"]),
    "debt_to_equity": st.column_config.NumberColumn("Debt/Equity", format="%.2f", help=HELP["debt_to_equity"]),
    "net_margin": st.column_config.NumberColumn("Net margin", format="percent", help=HELP["net_margin"]),
    "earnings_cagr": st.column_config.NumberColumn("Earnings growth/yr", format="percent", help=HELP["earnings_cagr"]),
    "years_of_data": st.column_config.NumberColumn("Years", format="%d"),
    "market_cap": st.column_config.NumberColumn("Market cap", format="compact"),
    "currency": st.column_config.TextColumn("Cur."),
}

def active_scheme() -> str:
    """The theme the viewer is currently seeing ("light" or "dark"), as reported by the browser."""
    return "dark" if getattr(getattr(st.context, "theme", None), "type", None) == "dark" else "light"


def theme() -> dict:
    return THEMES[active_scheme()]


def inject_css() -> None:
    palette = "\n".join(f"  --mf-{k}: light-dark({THEMES['light'][k]}, {THEMES['dark'][k]});" for k in THEMES["light"])
    # Dialogs render outside .stApp, so they don't inherit its color-scheme; pass the active theme explicitly.
    dialog_scheme = active_scheme()
    st.markdown(f"""<style>
:root {{
{palette}
}}
div[role="dialog"] {{ color-scheme: {dialog_scheme}; }}
section[data-testid="stSidebar"] [data-testid="stExpander"] details {{
  background: var(--mf-card); border: 1px solid var(--mf-border) !important; border-radius: 12px; color: var(--mf-ink); }}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {{ color: var(--mf-ink); }}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{ height: auto; padding-top: 1.1rem; padding-bottom: .35rem; }}
section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] img {{ height: 2rem; max-width: 13rem; }}
.mf-tagline {{ margin-top: -.6rem; }}
.st-key-mf_theme_switch {{ position: fixed; top: .7rem; right: 8.5rem; z-index: 1000001; width: auto !important;
  background: var(--mf-card); border: 1px solid var(--mf-border); border-radius: 999px; padding: .25rem .9rem .25rem .7rem;
  box-shadow: 0 2px 10px var(--mf-shadow); transition: box-shadow .3s ease; }}
.st-key-mf_theme_switch:hover {{ box-shadow: 0 6px 18px var(--mf-shadow); }}
.st-key-mf_theme_switch label {{ margin: 0; }}
.block-container {{ padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1320px; }}
h1, h2, h3 {{ letter-spacing: -0.015em; }}
@keyframes mfFadeUp {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}
.mf-hero {{ animation: mfFadeUp .8s cubic-bezier(.2,.8,.2,1) both; padding: 1.2rem 0 .4rem; }}
.mf-eyebrow {{ color: var(--mf-accent); font-size: .78rem; font-weight: 600; letter-spacing: .12em; text-transform: uppercase; }}
.mf-headline {{ font-family: {SERIF}; color: var(--mf-ink); font-size: clamp(2.3rem, 4.4vw, 3.6rem); line-height: 1.06;
                font-weight: 500; letter-spacing: -0.025em; margin: .6rem 0 1rem; }}
.mf-lede {{ color: var(--mf-ink2); font-size: 1.12rem; line-height: 1.6; max-width: 34rem; }}
.mf-hero-art {{ animation: mfFadeUp 1s cubic-bezier(.2,.8,.2,1) .15s both; }}
[class*="st-key-mfcard"] {{ background: var(--mf-card); border-radius: 18px !important; border-color: var(--mf-border) !important;
    transition: transform .45s cubic-bezier(.2,.8,.2,1), box-shadow .45s cubic-bezier(.2,.8,.2,1);
    animation: mfFadeUp .6s cubic-bezier(.2,.8,.2,1) both; }}
[class*="st-key-mfcard"]:hover {{ transform: translateY(-4px); box-shadow: 0 14px 36px var(--mf-shadow); }}
.stButton button, .stLinkButton a {{ border-radius: 999px; transition: all .3s cubic-bezier(.2,.8,.2,1); }}
.stButton button:hover {{ transform: translateY(-1px); }}
.mf-ticker {{ font-family: {SERIF}; }}
.mf-art {{ max-width: 260px; margin: .5rem auto 1rem; }}
@property --mf-n {{ syntax: '<integer>'; initial-value: 0; inherits: false; }}
@keyframes mfCount {{ from {{ --mf-n: 0; }} to {{ --mf-n: var(--to); }} }}
.mf-count {{ animation: mfCount 1.1s cubic-bezier(.2,.8,.2,1) forwards; counter-reset: mf var(--mf-n);
             font-family: {SERIF}; font-size: 2.1rem; font-weight: 600; color: var(--mf-ink); line-height: 1; }}
.mf-count::after {{ content: counter(mf); }}
.mf-count-label {{ color: var(--mf-ink2); font-size: .82rem; margin-top: .25rem; }}
@keyframes mfPulse {{ 0% {{ box-shadow: 0 0 0 0 rgba(12,163,12,.45); }} 70% {{ box-shadow: 0 0 0 7px rgba(12,163,12,0); }}
                      100% {{ box-shadow: 0 0 0 0 rgba(12,163,12,0); }} }}
.mf-live {{ display: inline-flex; align-items: center; gap: .45rem; color: var(--mf-ink2); font-size: .78rem;
            padding: .2rem .65rem; border: 1px solid var(--mf-border); border-radius: 999px; background: var(--mf-card); }}
.mf-live .mf-dot {{ animation: mfPulse 2.2s infinite; }}
@keyframes mfGrow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
.mf-lead {{ padding: .15rem 0 .1rem; animation: mfFadeUp .5s cubic-bezier(.2,.8,.2,1) both; }}
.mf-lead-top {{ display: flex; align-items: baseline; gap: .45rem; font-size: .84rem; color: var(--mf-ink2); }}
.mf-lead-rank {{ color: var(--mf-muted); width: .9rem; }}
.mf-lead-ticker {{ font-family: {SERIF}; font-weight: 600; color: var(--mf-ink); font-size: .98rem; }}
.mf-lead-name {{ flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--mf-muted); font-size: .76rem; }}
.mf-lead-score {{ font-weight: 600; color: var(--mf-ink); }}
.mf-meter {{ height: 6px; border-radius: 999px; background: var(--mf-track); margin: .3rem 0 0 1.35rem; overflow: hidden; }}
.mf-meter-fill {{ height: 100%; border-radius: 999px; background: var(--mf-series); transform-origin: left;
                  animation: mfGrow .9s cubic-bezier(.2,.8,.2,1) both; }}
[class*="st-key-mfspot"] {{ background: var(--mf-card); border-radius: 16px !important; animation: mfFadeUp .55s cubic-bezier(.2,.8,.2,1) both; }}
.mf-spot-ticker {{ font-family: {SERIF}; font-size: 1.5rem; font-weight: 600; color: var(--mf-ink); line-height: 1.1; }}
.mf-spot-name {{ color: var(--mf-ink2); font-size: .8rem; margin-bottom: .45rem; }}
.mf-spot-verdict {{ color: var(--mf-ink2); font-size: .8rem; line-height: 1.45; margin-top: .45rem; }}
.mf-chat-intro {{ display: flex; gap: 1.5rem; align-items: center; animation: mfFadeUp .6s cubic-bezier(.2,.8,.2,1) both; }}
.mf-chat-intro h3 {{ font-family: {SERIF}; font-weight: 500; margin: 0 0 .3rem; }}
@media (prefers-reduced-motion: reduce) {{
  .mf-hero, .mf-hero-art, [class*="st-key-mfcard"], .mf-chat-intro, .mf-count, .mf-live .mf-dot, .mf-lead,
  .mf-meter-fill, [class*="st-key-mfspot"] {{ animation: none; }}
  .mf-count {{ --mf-n: var(--to); }}
  [class*="st-key-mfcard"], .stButton button {{ transition: none; }}
}}
.mf-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: .5rem; }}
.mf-rank {{ color: var(--mf-muted); font-size: .78rem; }}
.mf-ticker {{ color: var(--mf-ink); font-size: 1.3rem; font-weight: 600; line-height: 1.2; }}
.mf-name {{ color: var(--mf-ink2); font-size: .88rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }}
.mf-badge {{ display: inline-flex; align-items: center; padding: .18rem .6rem; border-radius: 999px;
             font-size: .8rem; font-weight: 600; white-space: nowrap; }}
.mf-badge.strong {{ background: {STATUS['good']}; color: #ffffff; }}
.mf-badge.moderate {{ background: {STATUS['warning']}; color: #0b0b0b; }}
.mf-badge.weak {{ background: var(--mf-neutral); color: var(--mf-ink); }}
.mf-chip {{ display: inline-flex; align-items: center; gap: .35rem; padding: .12rem .55rem; border-radius: 999px;
            border: 1px solid var(--mf-border); color: var(--mf-ink2); font-size: .78rem; white-space: nowrap; }}
.mf-dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; }}
.mf-prices {{ display: flex; gap: 1.5rem; margin: .7rem 0 .4rem; flex-wrap: wrap; }}
.mf-label {{ color: var(--mf-muted); font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; }}
.mf-value {{ color: var(--mf-ink); font-size: 1rem; font-weight: 600; }}
.mf-metrics {{ color: var(--mf-ink2); font-size: .82rem; line-height: 1.6; margin-bottom: .2rem; }}
.mf-verdict {{ border-left: 4px solid var(--mf-series); background: var(--mf-card); padding: .8rem 1rem; border-radius: 6px;
               color: var(--mf-ink); font-size: 1.05rem; margin-bottom: .8rem; }}
.mf-reason {{ padding: .45rem 0; border-bottom: 1px solid var(--mf-grid); color: var(--mf-ink); }}
.mf-tagline {{ color: var(--mf-muted); font-size: .82rem; margin-bottom: .6rem; }}
.mf-section {{ color: var(--mf-muted); font-size: .7rem; font-weight: 600; text-transform: uppercase; letter-spacing: .07em;
               margin: 1.1rem 0 .45rem; }}
.mf-stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }}
.mf-stat {{ border: 1px solid var(--mf-border); border-radius: 10px; padding: .5rem .7rem; background: var(--mf-card); }}
.mf-stat-value {{ color: var(--mf-ink); font-size: 1.3rem; font-weight: 650; line-height: 1.2; }}
.mf-stat-label {{ color: var(--mf-muted); font-size: .72rem; }}
.mf-row {{ display: flex; justify-content: space-between; align-items: center; gap: .5rem; color: var(--mf-ink2);
           font-size: .82rem; padding: .18rem 0; }}
.mf-row b {{ color: var(--mf-ink); font-weight: 600; }}
</style>""", unsafe_allow_html=True)


def as_dict(row: pd.Series) -> dict:
    return {k: (None if missing(v) else v) for k, v in row.to_dict().items()}


def badge(score) -> str:
    tier = score_tier(score)
    return f'<span class="mf-badge {tier}">{0 if missing(score) else score:.0f} · {tier.title()}</span>'


def valuation_chip(mos) -> str:
    color, label = VALUATION_CHIPS[valuation_label(mos)]
    dot = f'<span class="mf-dot" style="background:{color}"></span>' if color else ""
    return f'<span class="mf-chip">{dot}{label}</span>'


def ratio_line(row: dict) -> str:
    parts = [f"ROE {pct(row.get('roe_avg'))} ({roe_label(row.get('roe_avg'))})"]
    if row["sector"] in FINANCIALS:
        parts.append(f"ROA {pct(row.get('roa'), 1)}")
    else:
        de = row.get("debt_to_equity")
        parts.append(f"Debt/Equity {'n/a' if missing(de) else f'{de:.1f}'} ({debt_label(de, row['sector'] in CAPITAL_HEAVY)})")
    parts.append(f"Margin {pct(row.get('net_margin'))} ({margin_label(row.get('net_margin'))})")
    return " · ".join(parts)


# ---------- stock detail ----------

def recent_history(history: dict) -> dict:
    """Keep the most recent years, the same window the score uses."""
    return {k: {y: s[y] for y in sorted(s)[-MAX_HISTORY_YEARS:]} for k, s in history.items() if s}


def history_chart(series: dict, title: str, currency: str | None, t: dict) -> alt.Chart:
    data = pd.DataFrame({"year": list(series.keys()), "value": list(series.values())})
    peak = data["value"].abs().max()
    divisor, unit = (1e9, "billions") if peak >= 1e9 else (1e6, "millions") if peak >= 1e6 else (1, "")
    data["display"] = data["value"] / divisor
    data["label"] = data["value"].map(lambda v: compact(v, currency))
    bars = alt.Chart(data, title=alt.Title(title, anchor="start", color=t["ink"], fontSize=13, fontWeight=600)).mark_bar(
        size=18, cornerRadiusEnd=4, color=t["series"],
    ).encode(
        x=alt.X("year:O", title=None, axis=alt.Axis(labelAngle=0, grid=False)),
        y=alt.Y("display:Q", title=f"{currency or ''} {unit}".strip(), axis=alt.Axis(format=",.2~f", tickCount=4)),
        tooltip=[alt.Tooltip("year:O", title="Year"), alt.Tooltip("label:N", title=title)],
    ).properties(height=190)
    return (bars.configure(background="transparent")
            .configure_axis(gridColor=t["grid"], domainColor=t["axis"], tickColor=t["axis"], labelColor=t["muted"],
                            titleColor=t["muted"], titleFontWeight="normal", labelFontSize=11)
            .configure_view(strokeWidth=0))


def summary_tab(row: dict, details: dict) -> None:
    st.markdown(f"{badge(row['score'])} &nbsp; {valuation_chip(row.get('margin_of_safety'))} &nbsp; "
                f"<span class='mf-chip'>{html.escape(row['sector'])}</span> &nbsp; "
                f"<span class='mf-chip'>{html.escape(row['country'])}</span>", unsafe_allow_html=True)
    st.write("")
    cols = st.columns(4)
    cols[0].metric("Buffett score", f"{row['score']:.0f}/100", help=HELP["score"])
    cols[1].metric("Price", money(row["price"], row["currency"]))
    cols[2].metric("Estimated value", money(row.get("intrinsic_value"), row["currency"]), help=HELP["intrinsic_value"])
    cols[3].metric("Market cap", compact(row.get("market_cap"), row["currency"]))
    pe = "n/a" if missing(row.get("pe")) else f"{row['pe']:.1f}"
    st.markdown(f"<div class='mf-metrics'>{ratio_line(row)} · P/E {pe}</div>", unsafe_allow_html=True)
    lines = [f"**Buffett checklist: {row['checklist']:.0f} of 6 rules passed**"]
    lines += [f"{STATUS_ICONS[passed]} {rule}" for rule, passed in details["checklist"].items()]
    st.markdown("  \n".join(lines))


def reasons_tab(row: dict, details: dict) -> None:
    st.markdown(f"<div class='mf-verdict'>{html.escape(explain.verdict(row, details))}</div>", unsafe_allow_html=True)
    for reason in explain.reasons(row, details):
        st.markdown(f"<div class='mf-reason'>{STATUS_ICONS[reason.passed]} {html.escape(reason.text)}</div>",
                    unsafe_allow_html=True)
    with st.expander("How the score adds up"):
        crit = pd.DataFrame(details["criteria"])
        crit["points"] = crit["weight"] * crit["value"]
        st.dataframe(
            crit[["label", "weight", "value", "points", "detail"]], hide_index=True, width="stretch",
            column_config={
                "label": "Criterion",
                "weight": st.column_config.NumberColumn("Max points", format="%d"),
                "value": st.column_config.ProgressColumn("Credit", min_value=0, max_value=1, format="percent"),
                "points": st.column_config.NumberColumn("Points", format="%.1f"),
                "detail": "Detail",
            },
        )
        st.caption("Criteria without data are skipped and the remaining points are rescaled to 100.")


def history_tab(row: dict, details: dict, t: dict) -> None:
    history = recent_history(details.get("history", {}))
    currency = row.get("financial_currency") or row["currency"]
    years = len(history.get("net_income", {}))
    st.caption(f"{years} years of annual results, in {currency}. "
               + ("US companies show the last 10 years from SEC filings; Canadian companies ~4 years from Yahoo."
                  if row["country"] == "USA" else "Canadian companies have ~4 years of free data available."))
    charts = [(k, HISTORY_LABELS[k]) for k in ("revenue", "net_income", "fcf") if history.get(k)]
    for col, (key, label) in zip(st.columns(len(charts)) if charts else [], charts):
        with col:
            st.altair_chart(history_chart(history[key], label, currency, t), theme=None, width="stretch")
    with st.expander("Show as a table"):
        table = pd.DataFrame(history).sort_index().rename(columns=HISTORY_LABELS)
        st.dataframe(table.map(lambda v: compact(v, currency)).T, width="stretch")


def valuation_tab(row: dict, details: dict) -> None:
    currency = row["currency"]
    financial = row["sector"] in FINANCIALS
    key = "net_income" if financial else "fcf"
    series = details.get("history", {}).get(key) or {}
    recent = [series[y] for y in sorted(series)[-3:]]
    base = sum(recent) / len(recent) if recent else None
    shares = row["market_cap"] / row["price"] if row.get("market_cap") and row.get("price") else None
    value, mos = row.get("intrinsic_value"), row.get("margin_of_safety")

    cols = st.columns(3)
    cols[0].metric("Today's price", money(row["price"], currency))
    cols[1].metric("Estimated value", money(value, currency), help=HELP["intrinsic_value"])
    cols[2].metric("Margin of safety", pct(mos), help=HELP["margin_of_safety"])
    st.markdown(f"**Verdict:** {valuation_chip(mos)}", unsafe_allow_html=True)

    if value is None or base is None:
        st.info("There isn't enough cash-flow history to estimate a value for this company.")
        return
    cash = "net income (profit)" if financial else "free cash flow"
    fin_currency = row.get("financial_currency") or currency
    steps = [
        f"Start with its average yearly {cash} over the last {len(recent)} years: **{compact(base, fin_currency)}**.",
        f"Assume that grows **{pct(details['growth_used'], 1)} a year** (the lower of its past profit and cash-flow "
        f"growth, capped at {pct(MAX_GROWTH)}), slowing gradually to {pct(TERMINAL_GROWTH, 1)} by year {PROJECTION_YEARS}.",
        f"Convert each future year's cash into today's money with a **{pct(DISCOUNT_RATE)} yearly discount**, "
        "the return a Buffett-style investor demands. Cash far in the future counts for less.",
        f"Add it all up and divide by **{compact(shares)} shares** = **{money(value, currency)} per share**.",
    ]
    if base <= 0:
        steps[1:] = ["Because that cash flow is negative, the business isn't producing cash for its owners, "
                     "so its estimated value is zero."]
    st.markdown(md("**How we estimated the value**\n\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))))
    if fin_currency != currency:
        st.caption(f"The company reports in {fin_currency}; values were converted to {currency} to compare with the share price.")
    st.caption("This is a deliberately conservative estimate, not a price target. Small changes in the growth or "
               "discount rate move it a lot, which is exactly why Buffett wants a margin of safety.")


def sources_tab(row: dict) -> None:
    st.markdown(f"**Data used:** {row.get('sources') or 'n/a'}")
    warnings = row.get("warnings")
    if warnings:
        st.markdown("**Data warnings** (sources disagreed; the middle value was used)")
        for w in warnings.split(" | "):
            st.warning(w, icon="⚠️")
    else:
        st.success("All sources agreed.", icon="✅")
    ticker = row["ticker"]
    links = [("Yahoo Finance", f"https://finance.yahoo.com/quote/{ticker}"),
             ("Google Finance", f"https://www.google.com/finance/quote/{google_symbol(ticker, row.get('exchange'))}")]
    if row["country"] == "USA":
        links += [("SEC filings", f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=10-K"),
                  ("Finviz", f"https://finviz.com/quote.ashx?t={ticker}")]
    for col, (label, url) in zip(st.columns(len(links)), links):
        col.link_button(label, url, width="stretch")


def stock_detail(series: pd.Series) -> None:
    row = as_dict(series)
    details = json.loads(row["details"])
    t = theme()
    tabs = st.tabs(["Summary", "Why it fits (or not)", "Financial history", "Valuation", "Sources & links"])
    with tabs[0]:
        summary_tab(row, details)
    with tabs[1]:
        reasons_tab(row, details)
    with tabs[2]:
        history_tab(row, details, t)
    with tabs[3]:
        valuation_tab(row, details)
    with tabs[4]:
        sources_tab(row)


def open_detail(series: pd.Series) -> None:
    st.dialog(f"{series['name']} ({series['ticker']})", width="large")(stock_detail)(series)


# ---------- lists ----------

def card(series: pd.Series, rank: int, key: str, show_sector: bool) -> None:
    row = as_dict(series)
    subtitle = row["sector"] if show_sector else row["name"]
    with st.container(border=True, key=f"mfcard_{key}"):
        st.markdown(f"""
<div class="mf-head">
  <div style="min-width:0">
    <div class="mf-rank">#{rank}</div>
    <div class="mf-ticker">{html.escape(row['ticker'])}</div>
    <div class="mf-name" title="{html.escape(row['name'])}">{html.escape(subtitle if show_sector else row['name'])}</div>
  </div>
  {badge(row['score'])}
</div>
<div class="mf-prices">
  <div><div class="mf-label">Price</div><div class="mf-value">{money(row['price'], row['currency'])}</div></div>
  <div><div class="mf-label">Est. value</div><div class="mf-value">{money(row.get('intrinsic_value'), row['currency'])}</div></div>
</div>
<div class="mf-metrics">{valuation_chip(row.get('margin_of_safety'))} &nbsp; {row['checklist']:.0f}/6 rules passed</div>
<div class="mf-metrics">{ratio_line(row)}</div>
""", unsafe_allow_html=True)
        if st.button("See why →", key=key, width="stretch"):
            open_detail(series)


def card_grid(df: pd.DataFrame, key: str, show_sector: bool = False) -> None:
    rows = list(df.iterrows())
    for start in range(0, len(rows), 3):  # one st.columns per row keeps each row of cards aligned
        for col, (i, (_, row)) in zip(st.columns(3), enumerate(rows[start:start + 3], start)):
            with col:
                card(row, i + 1, re.sub(r"\W", "_", f"{key}_{row['ticker']}"), show_sector)


def apply_filters(data: pd.DataFrame, filters: dict) -> pd.DataFrame:
    out = data[data["score"] >= filters["min_score"]]
    if filters["cheap_only"]:
        out = out[out["margin_of_safety"] >= 0.15]
    return out


def country_tab(df: pd.DataFrame, country: str, filters: dict) -> None:
    data = df[df["country"] == country]
    if data.empty:
        st.info(f"No {country} results yet. Run the screen from the sidebar.")
        return
    picks = top_picks(apply_filters(data, filters), filters["top_n"])
    left, right = st.columns([3, 1])
    sector = left.selectbox("Sector", ["All sectors (best pick in each)"] + [s for s in SECTORS if s in set(data["sector"])],
                            key=f"sector_{country}")
    view = right.segmented_control("View", ["Cards", "Table"], default="Cards", key=f"view_{country}") or "Cards"

    if sector.startswith("All"):
        shown = picks.groupby("sector", group_keys=False).head(1).sort_values("score", ascending=False)
        st.caption("The highest-scoring stock in each sector.")
    else:
        shown = picks[picks["sector"] == sector]
        screened = data[data["sector"] == sector]
        st.caption(f"Top {len(shown)} of {len(screened)} {sector} stocks screened in the "
                   f"{'S&P 500' if country == 'USA' else 'S&P/TSX Composite'}.")

    if shown.empty:
        st.markdown(f"<div class='mf-art'>{illustration('empty', alt='Nothing found')}</div>", unsafe_allow_html=True)
        st.info("No stocks match your filters. Lower the minimum score or turn off \"Only show cheap stocks\" in the sidebar.")
        return
    if view == "Cards":
        card_grid(shown, key=f"card_{country}_{sector}", show_sector=sector.startswith("All"))
        return
    cols = ["ticker", "name", "sector", "score", "checklist", "price", "currency", "intrinsic_value", "margin_of_safety",
            "pe", "roe_avg", "debt_to_equity", "net_margin", "earnings_cagr", "years_of_data", "market_cap"]
    selection = st.dataframe(shown[cols], column_config=COLUMNS, hide_index=True, width="stretch",
                             on_select="rerun", selection_mode="single-row", key=f"table_{country}_{sector}")
    if selection.selection.rows:
        stock = shown.iloc[selection.selection.rows[0]]
        st.subheader(f"{stock['name']} ({stock['ticker']})")
        stock_detail(stock)
    else:
        st.caption("Click a row to see the full explanation. Click a column header to sort.")


# ---------- chat ----------

def _queue_question(question: str | None) -> None:
    if question:
        st.session_state["chat_pending"] = question


def _pick_example() -> None:
    _queue_question(st.session_state.get("chat_pick"))
    st.session_state["chat_pick"] = None


def _open(ticker: str) -> None:
    st.session_state["open_ticker"] = ticker


def chat_tab(df: pd.DataFrame) -> None:
    history = st.session_state.setdefault("chat", [])
    if not history:
        st.markdown(f"""<div class="mf-chat-intro">
  <div style="width:200px;flex:none">{illustration('chat', alt='Chat')}</div>
  <div><h3>Ask Moat Finder</h3>
  <div class="mf-lede">Ask about any stock, compare companies, find ideas by sector, or look up a term.
  Answers come straight from the screen results: no AI, no tokens, instant.</div></div>
</div>""", unsafe_allow_html=True)
    st.pills("Try asking", chat.EXAMPLES, key="chat_pick", on_change=_pick_example,
             label_visibility="collapsed" if history else "visible")

    for i, message in enumerate(history):
        avatar = str(ASSETS / f"logo{'-dark' if active_scheme() == 'dark' else ''}.svg")
        with st.chat_message(message["role"], avatar=avatar if message["role"] == "assistant" else None):
            st.markdown(md(message["text"]))
            if message.get("table") is not None:
                table = message["table"]
                st.dataframe(table, hide_index=isinstance(table.index, pd.RangeIndex), width="stretch",
                             height=min(36 * (len(table) + 1) + 4, 600))  # tall enough to show every row
            tickers = message.get("tickers") or []
            if tickers:
                for col, ticker in zip(st.columns(min(len(tickers), 6)), tickers[:6]):
                    col.button(f"Open {ticker}", key=f"chat_open_{i}_{ticker}", on_click=_open, args=(ticker,),
                               width="stretch")
    if history and st.button("Clear conversation", key="chat_clear"):
        st.session_state["chat"] = []
        st.rerun()

    question = st.chat_input("Ask about a stock, a sector, or a term…", key="chat_input")
    pending = st.session_state.pop("chat_pending", None) or question
    if pending:
        reply = chat.answer(pending, df)
        history.append({"role": "user", "text": pending})
        history.append({"role": "assistant", "text": reply.text, "table": reply.table, "tickers": reply.tickers})
        st.rerun()


# ---------- guide & sidebar ----------

HOW_TO_READ = """
1. **Pick a country tab and a sector.** Each card is one of the top stocks in that sector, best first.
2. **The coloured badge is the Buffett score** (0–100): 🟢 *Strong* 80+, 🟡 *Moderate* 60–79, ⚪ *Weak* below 60.
3. **Price vs. Est. value** compares today's share price with our estimate of what the business is worth.
   The chip says whether that looks *Cheap*, *Fair* or *Expensive*.
4. **The ratio line** shows the quality signals Buffett cares about: high return on equity, low debt, healthy margins.
5. **Click "See why →"** for a plain-English explanation, 4–10 years of history, and how the value was estimated.

Hover over any ⓘ or column header for a definition. The **Guide** tab has a full glossary.
"""


def guide_tab() -> None:
    st.markdown(f"<div class='mf-art' style='margin-left:0'>{illustration('guide', alt='Guide')}</div>",
                unsafe_allow_html=True)
    st.markdown("### How to read this page")
    st.markdown(HOW_TO_READ)
    st.markdown("### Glossary")
    for term, meaning in GLOSSARY.items():
        st.markdown(f"**{term}**: {meaning}")
    st.markdown("""
### How stocks are scored
Each stock earns up to 100 points across Buffett's core principles. Partial credit scales between a "poor" and "great" level.

| Principle | What we check | Points | Full points at |
|---|---|---|---|
| Durable competitive advantage | Average return on equity | 12 | 15%+ (0 at 5%) |
| | ROE consistency | 8 | 15%+ every year |
| Conservative balance sheet | Debt/Equity | 15 | 0.5 or less (1.0 for Utilities/Real Estate); ROA 1.2%+ for Financials |
| Pricing power | 3-year average net margin | 14 | 15%+ (0 at 5%) |
| Predictable earnings | Profitable years · growth · few down years | 6 · 5 · 4 | every year · 10%/yr · no declines |
| Owner earnings | Positive & growing free cash flow | 6 · 5 | every year · 8%/yr (skipped for Financials) |
| Margin of safety | Price vs. estimated value · P/E | 17 · 8 | 30%+ below value · P/E 12 or less |

**Data:** Yahoo Finance, SEC EDGAR (US filings), Google Finance and Finviz (cross-checks; when they disagree the middle
value is used and a warning is shown), plus Financial Modeling Prep if an API key is set.

*An educational tool, not investment advice. Free data can be incomplete or wrong, so check before investing.*
""")


def section(title: str) -> None:
    st.markdown(f"<div class='mf-section'>{title}</div>", unsafe_allow_html=True)


def dot(color: str | None) -> str:
    return f'<span class="mf-dot" style="background:{color or THEMES["light"]["muted"]}"></span>'


def freshness(generated_at) -> tuple[str, str, str]:
    """('2 h ago', status colour, status label) for the last screen run."""
    then = pd.Timestamp(generated_at)
    now = pd.Timestamp.now(tz=then.tz) if then.tz else pd.Timestamp.now()  # results saved by CI are in UTC
    seconds = (now - then).total_seconds()
    hours = seconds / 3600
    ago = (f"{max(1, int(seconds // 60))} min ago" if hours < 1 else f"{hours:.0f} h ago" if hours < 48
           else f"{hours / 24:.0f} days ago")
    if hours < 24:
        return ago, STATUS["good"], "Fresh"
    if hours < 24 * 7:
        return ago, STATUS["warning"], "Getting old"
    return ago, STATUS["serious"], "Stale, refresh"


def queue_search(labels: dict) -> None:
    st.session_state["open_ticker"] = labels.get(st.session_state["search"])
    st.session_state["search"] = None  # clear the box so the same stock can be opened again


def live_badge(df: pd.DataFrame) -> None:
    newest = max(df["generated_at"].dropna())
    ago, color, label = freshness(newest)
    st.markdown(f"<span class='mf-live'><span class='mf-dot' style='background:{color}'></span>"
                f"{label} · updated {ago}</span>", unsafe_allow_html=True)


def match_count(filtered: pd.DataFrame, shown: int, top_n: int) -> None:
    n = len(filtered)
    st.markdown(f"<div class='mf-count' style='--to:{n}' role='img' aria-label='{n} stocks match'></div>"
                f"<div class='mf-count-label'>stocks match your filters · {shown} make the top-{top_n} lists</div>",
                unsafe_allow_html=True)


def spotlight(filtered: pd.DataFrame) -> None:
    pool = filtered[(filtered["score"] >= 80) & (filtered["margin_of_safety"] >= 0.15)].drop_duplicates("name")
    if pool.empty:
        pool = filtered.sort_values("score", ascending=False).drop_duplicates("name").head(10)
    if pool.empty:
        st.caption("No stocks match your filters.")
        return
    tickers = list(pool["ticker"])
    if st.session_state.get("spotlight") not in tickers:
        st.session_state["spotlight"] = random.choice(tickers)
    row = as_dict(pool[pool["ticker"] == st.session_state["spotlight"]].iloc[0])
    details = json.loads(row["details"])
    with st.container(border=True, key=f"mfspot_{re.sub(r'\W', '_', row['ticker'])}"):
        st.markdown(f"""<div class="mf-head"><div style="min-width:0">
  <div class="mf-spot-ticker">{html.escape(row['ticker'])}</div>
  <div class="mf-spot-name">{html.escape(row['name'])}</div></div>{badge(row['score'])}</div>
<div>{valuation_chip(row.get('margin_of_safety'))} &nbsp;<span class="mf-chip">{html.escape(row['sector'])}</span></div>
<div class="mf-spot-verdict">{html.escape(explain.verdict(row, details))}</div>""", unsafe_allow_html=True)
        left, right = st.columns(2)
        left.button("Open", key="spot_open", on_click=_open, args=(row["ticker"],), width="stretch")
        if right.button("🔀 Shuffle", key="spot_shuffle", width="stretch", disabled=len(tickers) < 2):
            st.session_state["spotlight"] = random.choice([t for t in tickers if t != row["ticker"]])
            st.rerun()
    st.caption(f"Picked from {len(tickers)} {'strong, cheap ' if len(pool) and pool['score'].min() >= 80 else 'top '}"
               "stocks that match your filters.")


def leaderboard(filtered: pd.DataFrame) -> None:
    scope = st.segmented_control("Leaderboard scope", ["All", "🇺🇸 USA", "🇨🇦 Canada"], default="All",
                                 key="lead_scope", label_visibility="collapsed") or "All"
    data = filtered if scope == "All" else filtered[filtered["country"] == scope.split(" ")[1]]
    top = data.sort_values(["score", "margin_of_safety"], ascending=False).drop_duplicates("name").head(5)
    if top.empty:
        st.caption("No stocks match your filters.")
        return
    for i, (_, row) in enumerate(top.iterrows()):
        text, action = st.columns([6, 1], vertical_alignment="center")
        text.markdown(f"""<div class="mf-lead" style="animation-delay:{i * 70}ms">
  <div class="mf-lead-top"><span class="mf-lead-rank">{i + 1}</span>
    <span class="mf-lead-ticker">{html.escape(row['ticker'])}</span>
    <span class="mf-lead-name" title="{html.escape(row['name'])}">{html.escape(row['name'])}</span>
    <span class="mf-lead-score">{row['score']:.0f}</span></div>
  <div class="mf-meter"><div class="mf-meter-fill" style="width:{row['score']:.0f}%;animation-delay:{i * 70}ms"></div></div>
</div>""", unsafe_allow_html=True)
        action.button("↗", key=f"lead_{row['ticker']}", on_click=_open, args=(row["ticker"],), type="tertiary",
                      help=f"Open {row['name']}")


def data_health(df: pd.DataFrame) -> None:
    rows = []
    for country, ts in df.groupby("country")["generated_at"].first().items():
        ago, color, label = freshness(ts)
        rows.append(f"<div class='mf-row'><span>{dot(color)} {country} · {ago}</span><span>{label}</span></div>")
    us = (df["country"] == "USA").sum()
    sources = df["sources"].fillna("")
    for name, total in (("Yahoo", len(df)), ("Google Finance", len(df)), ("SEC EDGAR", us), ("Finviz", us)):
        covered = int(sources.str.contains(name).sum())
        share = covered / total if total else 0
        color = STATUS["good"] if share >= 0.9 else STATUS["warning"] if share >= 0.5 else STATUS["serious"]
        rows.append(f"<div class='mf-row'><span>{dot(color)} {name}</span><b>{covered:,}/{total:,}</b></div>")
    rows.append(f"<div class='mf-row'><span>{dot(STATUS['good'] if FMP_API_KEY else None)} FMP (extra Canadian history)</span>"
                f"<b>{'on' if FMP_API_KEY else 'off'}</b></div>")
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("SEC EDGAR and Finviz cover US stocks only.")


def refresh_controls(expanded: bool) -> None:
    with st.expander("🔄 Refresh data", expanded=expanded):
        countries = st.multiselect("Countries", COUNTRIES, default=list(COUNTRIES))
        limit = st.number_input("Max stocks per sector (0 = all)", min_value=0, max_value=200, value=0,
                                help="Use a small number for a quick test run.")
        st.caption("A full run checks ~720 stocks: 10–20 min the first time, much faster afterwards (cached).")
        if st.button("Run screen", type="primary", disabled=not countries, width="stretch"):
            bar = st.progress(0.0, text="Starting...")
            df = run_screen(countries, limit_per_sector=limit or None,
                            progress=lambda done, total, tk: bar.progress(done / total, text=f"{done}/{total} · {tk}"))
            save_results(df)
            st.rerun()


def set_theme(choice: str) -> None:
    """Switch Streamlit's theme to "Light" or "Dark" for this viewer, then reload.

    Streamlit has no Python API for this. It keeps the viewer's choice in localStorage ("System", "Light" or
    "Dark" under stActiveTheme-<path>-v2) and applies it on page load, which is what its ⋮ > Settings menu does
    too. If a Streamlit upgrade changes that key, the Settings menu still works. The component iframe may write
    storage but isn't allowed to reload the page (sandbox), so the reload runs from a script added to the page.
    """
    components.html(f"""<script>
  const w = window.parent;
  w.localStorage.setItem("stActiveTheme-" + w.location.pathname + "-v2", JSON.stringify("{choice}"));
  const reload = w.document.createElement("script");
  reload.textContent = "location.reload()";
  w.document.head.appendChild(reload);
</script>""", height=0)


def theme_switch() -> None:
    """Dark-mode toggle pinned to the top right. It starts from the theme on screen (the system's, by default)."""
    is_dark = active_scheme() == "dark"
    with st.container(key="mf_theme_switch"):
        dark = st.toggle("🌙 Dark mode", value=is_dark, key="dark_mode")
    if dark != is_dark:
        set_theme("Dark" if dark else "Light")


TOP_N_OPTIONS = [5, 10, 15, 25]
MIN_SCORE_OPTIONS = {"Any": 0, "60+": 60, "70+": 70, "80+": 80}
PRICE_OPTIONS = ["Any price", "Cheap only"]


def brand() -> None:
    """Logo in the sidebar's top row (next to the collapse arrow); just the mark when the sidebar is collapsed."""
    suffix = "-dark" if active_scheme() == "dark" else ""
    st.logo(str(ASSETS / f"wordmark{suffix}.svg"), size="large", icon_image=str(ASSETS / f"logo{suffix}.svg"))


def sidebar(df: pd.DataFrame | None) -> dict:
    filters = {"top_n": 10, "min_score": 0, "cheap_only": False}
    brand()
    with st.sidebar:
        st.markdown("<div class='mf-tagline'>Great businesses at sensible prices</div>", unsafe_allow_html=True)
        if df is None:
            refresh_controls(expanded=True)
            return filters
        live_badge(df)
        st.write("")
        ranked = df[df["eligible"] == True]  # noqa: E712
        labels = {f"{r.ticker} · {r.name}": r.ticker for r in ranked.sort_values("score", ascending=False).itertuples()}
        st.selectbox("Find a stock", list(labels), index=None, placeholder="🔎  Search ticker or company…",
                     key="search", on_change=queue_search, args=(labels,), label_visibility="collapsed")

        section("Tune your screen")
        filters["top_n"] = st.segmented_control("Stocks per sector", TOP_N_OPTIONS, default=10, key="f_top_n") or 10
        min_label = st.segmented_control("Minimum Buffett score", list(MIN_SCORE_OPTIONS), default="Any",
                                         key="f_min_score", help=HELP["score"]) or "Any"
        filters["min_score"] = MIN_SCORE_OPTIONS[min_label]
        price = st.segmented_control("Price", PRICE_OPTIONS, default="Any price", key="f_price",
                                     help="Cheap = priced at least 15% below our estimate of what the business is worth.")
        filters["cheap_only"] = price == "Cheap only"
        filtered = apply_filters(ranked, filters)
        match_count(filtered, len(top_picks(filtered, filters["top_n"])), filters["top_n"])

        section("Spotlight")
        spotlight(filtered)
        section("Leaderboard")
        leaderboard(filtered)

        st.write("")
        with st.expander("📡 Data health"):
            data_health(df)
        refresh_controls(expanded=False)
    return filters


def main() -> None:
    inject_css()
    theme_switch()
    text, art = st.columns([1.25, 1], vertical_alignment="center")
    text.markdown("""<div class="mf-hero">
  <div class="mf-eyebrow">Moat Finder · USA &amp; Canada</div>
  <div class="mf-headline">Find wonderful businesses at fair prices.</div>
  <div class="mf-lede">Every stock in the S&amp;P 500 and the S&amp;P/TSX Composite, scored against Warren Buffett's
  principles and explained in plain English.</div>
</div>""", unsafe_allow_html=True)
    art.markdown(f"<div class='mf-hero-art'>{illustration('hero', alt='A castle protected by a moat')}</div>",
                 unsafe_allow_html=True)
    df = load_results()
    filters = sidebar(df)
    if df is None:
        st.info("No results yet. Choose countries in the sidebar and click **Run screen**.")
        guide_tab()
        return
    with st.expander("New here? How to read this page"):
        st.markdown(HOW_TO_READ)

    tabs = st.tabs(["🇺🇸 USA", "🇨🇦 Canada", "💬 Ask Moat Finder", "All results", "Guide"])
    for tab, country in zip(tabs, COUNTRIES):
        with tab:
            country_tab(df, country, filters)
    with tabs[2]:
        chat_tab(df)
    with tabs[3]:
        cols = [c for c in COLUMNS if c in df.columns] + ["country", "eligible", "reason", "sources", "warnings"]
        st.dataframe(df[cols].sort_values("score", ascending=False), hide_index=True, column_config=COLUMNS, width="stretch")
        st.download_button("Download CSV", df.drop(columns=["details"]).to_csv(index=False), "moat_finder.csv", "text/csv")
    with tabs[4]:
        guide_tab()

    # Opened from the sidebar search or a top-pick button.
    ticker = st.session_state.pop("open_ticker", None)
    if ticker in set(df["ticker"]):
        open_detail(df[df["ticker"] == ticker].iloc[0])


main()
