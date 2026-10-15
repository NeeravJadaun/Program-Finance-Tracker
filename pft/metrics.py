"""Budget-versus-actual calculations.

Definitions used everywhere (UI, findings, Excel):
    variance  = actual - budget     (positive = overspend on an expense line)
    remaining = budget - actual
    variance % = variance / budget  (None, shown as N/A, when budget is zero)
"""

from __future__ import annotations

import pandas as pd

from pft.data import Scope, month_name
from pft.money import fmt_cad, fmt_pct, pct_variance

BVA_COLUMNS = ["program_id", "program", "month", "budget_cents", "actual_cents",
               "variance_cents", "remaining_cents", "variance_pct", "txn_count"]


def _with_variance(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["variance_cents"] = df["actual_cents"] - df["budget_cents"]
    df["remaining_cents"] = df["budget_cents"] - df["actual_cents"]
    df["variance_pct"] = [pct_variance(v, b) for v, b in zip(df["variance_cents"], df["budget_cents"])]
    return df


def budget_vs_actual(frames: dict[str, pd.DataFrame], scope: Scope) -> pd.DataFrame:
    """One row per program-month in scope.

    Transactions are aggregated to program-month *before* joining to budgets,
    so each budget appears exactly once regardless of how many expenses exist.
    """
    budgets = frames["budgets"]
    budgets = budgets[budgets["program_id"].isin(scope.program_ids) & budgets["month"].isin(scope.months)]
    txns = frames["transactions"]
    txns = txns[txns["program_id"].isin(scope.program_ids) & txns["month"].isin(scope.months)]
    actual = (txns.groupby(["program_id", "month"], as_index=False)
              .agg(actual_cents=("amount_cents", "sum"), txn_count=("txn_id", "count")))
    df = budgets.merge(actual, on=["program_id", "month"], how="outer")
    for col in ["budget_cents", "actual_cents", "txn_count"]:
        df[col] = df[col].fillna(0).astype("int64")
    names = frames["programs"].set_index("program_id")["name"]
    df["program"] = df["program_id"].map(names)
    df = _with_variance(df).sort_values(["program_id", "month"]).reset_index(drop=True)
    return df[BVA_COLUMNS]


def by_program(bva: pd.DataFrame) -> pd.DataFrame:
    if bva.empty:
        return pd.DataFrame(columns=BVA_COLUMNS[:2] + BVA_COLUMNS[3:])
    df = (bva.groupby(["program_id", "program"], as_index=False)
          [["budget_cents", "actual_cents", "txn_count"]].sum())
    return _with_variance(df)


def by_month(bva: pd.DataFrame) -> pd.DataFrame:
    if bva.empty:
        return pd.DataFrame(columns=["month", "budget_cents", "actual_cents", "variance_cents",
                                     "remaining_cents", "variance_pct", "txn_count"])
    df = bva.groupby("month", as_index=False)[["budget_cents", "actual_cents", "txn_count"]].sum()
    return _with_variance(df)


def totals(bva: pd.DataFrame) -> dict[str, int | float | None]:
    budget = int(bva["budget_cents"].sum())
    actual = int(bva["actual_cents"].sum())
    return {
        "budget_cents": budget,
        "actual_cents": actual,
        "variance_cents": actual - budget,
        "remaining_cents": budget - actual,
        "variance_pct": pct_variance(actual - budget, budget),
        "utilization": actual / budget if budget else None,
        "txn_count": int(bva["txn_count"].sum()),
    }


def findings(bva: pd.DataFrame, exceptions: pd.DataFrame) -> list[str]:
    """Short plain-language findings, each computed from the filtered data."""
    if bva.empty:
        return []
    t = totals(bva)
    out = []
    util = "N/A" if t["utilization"] is None else f"{t['utilization']:.1%}"
    out.append(f"Actual spend is {fmt_cad(t['actual_cents'])} against a budget of "
               f"{fmt_cad(t['budget_cents'])}: {util} of budget used, "
               f"{fmt_cad(t['remaining_cents'])} remaining.")

    prog = by_program(bva)
    over = prog[prog["variance_cents"] > 0].sort_values("variance_cents", ascending=False)
    if over.empty:
        out.append(f"No program is over budget for the selected period ({len(prog)} reviewed).")
    else:
        top = over.iloc[0]
        out.append(f"{len(over)} of {len(prog)} programs are over budget. Largest overspend: "
                   f"{top['program']}, {fmt_cad(top['variance_cents'], signed=True)} "
                   f"({fmt_pct(top['variance_pct'])}).")

    cells = bva[bva["budget_cents"] > 0].sort_values("variance_pct", ascending=False)
    if not cells.empty and cells.iloc[0]["variance_cents"] > 0:
        c = cells.iloc[0]
        out.append(f"Highest monthly overspend rate: {c['program']} in {month_name(c['month'])}, "
                   f"{fmt_pct(c['variance_pct'])} ({fmt_cad(c['variance_cents'], signed=True)}).")

    zero = bva[(bva["budget_cents"] == 0) & (bva["actual_cents"] > 0)]
    for _, z in zero.iterrows():
        out.append(f"{z['program']} recorded {fmt_cad(z['actual_cents'])} in {month_name(z['month'])} "
                   f"with no budget; percentage variance is N/A for that month.")

    if exceptions is not None and not exceptions.empty:
        open_exc = exceptions[exceptions["status"] != "Resolved"]
        errors = int((open_exc["category"] == "Financial error").sum())
        control = int((open_exc["category"] == "Control breach").sum())
        support = int((open_exc["category"] == "Missing support").sum())
        out.append(f"{len(open_exc)} reconciliation exceptions are open: {errors} possible financial "
                   f"errors, {control} control breaches and {support} missing-support items.")
    return out
