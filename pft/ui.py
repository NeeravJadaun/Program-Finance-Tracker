"""Presentation helpers: scoped CSS, badges, table styling and column formats."""

from __future__ import annotations

import html

import pandas as pd
import streamlit as st

TEXT = "#171717"
MUTED = "#475569"
BORDER = "#E2E8F0"
TEAL = "#0F766E"

# (background, text) pairs; every tone is always paired with a text label.
TONES = {
    "red": ("#FEE2E2", "#991B1B"),
    "amber": ("#FEF3C7", "#92400E"),
    "green": ("#DCFCE7", "#166534"),
    "teal": ("#CCFBF1", "#115E59"),
    "gray": ("#F1F5F9", "#334155"),
}

STATUS_TONE = {
    "High": "red", "Medium": "amber",
    "Open": "amber", "Under review": "teal", "Resolved": "green",
    "Not started": "gray", "In progress": "teal", "Needs follow-up": "amber", "Complete": "green",
    "Overdue": "red", "Due": "gray", "Done": "green",
    "Over budget": "red", "Within budget": "green", "No budget": "amber",
    "Verified": "green", "Unverified": "amber", "Pending review": "gray",
    "Financial error": "red", "Control breach": "red", "Missing support": "amber",
}

CSS = f"""
<style>
.block-container {{ max-width: 1240px; padding-top: 2.25rem; padding-bottom: 3rem; }}
html, body, [class*="st-"] {{ font-variant-numeric: tabular-nums; }}
[data-testid="stMainMenu"], [data-testid="stAppDeployButton"] {{ display: none; }}
.st-key-kpis [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; row-gap: 1rem; }}
.st-key-kpis [data-testid="stColumn"] {{ min-width: 210px; }}
.st-key-kpis [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height: 100%; }}
.st-key-kpis [data-testid="stColumn"] [data-testid="stLayoutWrapper"] {{ flex: 1 1 auto; }}
.st-key-kpis [class*="st-key-card"] {{ height: 100%; }}
div.stVerticalBlock[class*="st-key-card"] {{
  background: #FFFFFF; border: 1px solid {BORDER}; border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); padding: 1rem 1.1rem;
}}
[data-testid="stMetricValue"] {{ font-size: 1.6rem; font-weight: 600; color: {TEXT}; }}
[data-testid="stMetricLabel"] p {{ color: {MUTED}; font-weight: 600; }}
.pft-title {{ font-size: 1.6rem; font-weight: 700; color: {TEXT}; margin: 0; line-height: 1.2; }}
.pft-sub {{ color: {MUTED}; margin: .35rem 0 0 0; font-size: .95rem; }}
.pft-badge {{ display: inline-block; padding: .15rem .55rem; border-radius: 999px; font-size: .8rem;
  font-weight: 600; line-height: 1.4; vertical-align: middle; border: 1px solid transparent; }}
.pft-h2 {{ font-size: 1.25rem; font-weight: 700; color: {TEXT}; margin: 0 0 .15rem 0; }}
.pft-muted {{ color: {MUTED}; font-size: .95rem; margin: 0; }}
.pft-findings {{ margin: 0; padding-left: 1.1rem; }}
.pft-findings li {{ margin-bottom: .55rem; color: {TEXT}; line-height: 1.45; }}
.pft-kv {{ display: grid; grid-template-columns: minmax(120px, max-content) 1fr; gap: .3rem 1rem; margin: .25rem 0 .5rem 0; }}
.pft-kv dt {{ color: {MUTED}; font-weight: 600; }}
.pft-kv dd {{ margin: 0; color: {TEXT}; }}
.pft-num {{ text-align: right; }}
hr {{ margin: 1rem 0; border-color: {BORDER}; }}
@media (max-width: 640px) {{
  .block-container {{ padding-left: 1rem; padding-right: 1rem; padding-top: 1.25rem; }}
  .pft-title {{ font-size: 1.35rem; }}
}}
</style>
"""


def inject_css() -> None:
    st.html(CSS)


def badge(text: str, tone: str | None = None) -> str:
    bg, fg = TONES[tone or STATUS_TONE.get(text, "gray")]
    return f'<span class="pft-badge" style="background:{bg};color:{fg};border-color:{bg}">{html.escape(text)}</span>'


def heading(title: str, caption: str | None = None) -> None:
    sub = f'<p class="pft-muted">{html.escape(caption)}</p>' if caption else ""
    st.html(f'<div><p class="pft-h2">{html.escape(title)}</p>{sub}</div>')


def kv_list(items: list[tuple[str, str]]) -> None:
    """Definition list. Values are escaped unless they are badge HTML (prefixed with '<span')."""
    rows = "".join(
        f"<dt>{html.escape(k)}</dt><dd>{v if v.startswith('<span') else html.escape(v)}</dd>" for k, v in items
    )
    st.html(f'<dl class="pft-kv">{rows}</dl>')


def style_badges(df: pd.DataFrame, columns: list[str]):
    """Tint status/severity cells. Text is unchanged, so meaning never relies on colour alone."""

    def tint(value):
        tone = STATUS_TONE.get(str(value))
        if not tone:
            return ""
        bg, fg = TONES[tone]
        return f"background-color: {bg}; color: {fg}; font-weight: 600"

    present = [c for c in columns if c in df.columns]
    return df.style.map(tint, subset=present) if present else df.style


def money(label: str, help: str | None = None):
    return st.column_config.NumberColumn(label, help=help, format="dollar", alignment="right")


def right_text(label: str, help: str | None = None):
    return st.column_config.TextColumn(label, help=help, alignment="right")


def cents_to_dollars(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in columns:
        df[c] = df[c].map(lambda v: None if pd.isna(v) else int(v) / 100)
    return df
