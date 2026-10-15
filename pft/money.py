"""Currency helpers. All amounts are stored and calculated as integer CAD cents."""

from __future__ import annotations

import math


def to_dollars(cents: int | float | None) -> float | None:
    """Convert cents to dollars for display or export only."""
    if cents is None or (isinstance(cents, float) and math.isnan(cents)):
        return None
    return int(cents) / 100


def fmt_cad(cents: int | float | None, signed: bool = False) -> str:
    """Format cents as a CAD string, e.g. 123456 -> 'CA$1,234.56'."""
    if cents is None or (isinstance(cents, float) and math.isnan(cents)):
        return "N/A"
    cents = int(cents)
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    return f"{sign}CA${abs(cents) / 100:,.2f}"


def fmt_cad_whole(cents: int | float | None) -> str:
    """Whole-dollar CAD (half rounds up) for headline figures, e.g. 202710050 -> 'CA$2,027,101'."""
    if cents is None or (isinstance(cents, float) and math.isnan(cents)):
        return "N/A"
    cents = int(cents)
    dollars = (abs(cents) + 50) // 100
    return f"{'-' if cents < 0 and dollars else ''}CA${dollars:,}"


def pct_variance(variance_cents: int, budget_cents: int) -> float | None:
    """Variance as a fraction of budget. None (shown as N/A) when budget is zero."""
    if budget_cents == 0:
        return None
    return variance_cents / budget_cents


def fmt_pct(value: float | None, signed: bool = True) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "N/A"
    return f"{value:+.1%}" if signed else f"{value:.1%}"
