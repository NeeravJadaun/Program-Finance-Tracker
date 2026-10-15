"""ESG indicator records and data-quality checks.

These are simple synthetic operational measures. Missing values stay missing
(never zero), units are compared but never converted, and nothing here is
audited impact data or evidence of compliance with any reporting framework.
"""

from __future__ import annotations

import pandas as pd

from pft.data import Scope

FLAG_MISSING_VALUE = "Missing value"
FLAG_MISSING_SOURCE = "Missing source"
FLAG_UNIT = "Inconsistent unit"


def validate(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    vals = frames["esg_values"].merge(frames["esg_indicators"], on="indicator_id", how="left",
                                      suffixes=("", "_indicator"))
    names = frames["programs"].set_index("program_id")["name"]
    vals["scope"] = vals["program_id"].map(names).fillna("Organization-wide")

    def flags(r) -> list[str]:
        out = []
        if pd.isna(r["value"]):
            out.append(FLAG_MISSING_VALUE)
        if pd.isna(r["source"]) or not str(r["source"]).strip():
            out.append(FLAG_MISSING_SOURCE)
        if r["unit"] != r["expected_unit"]:
            out.append(f"{FLAG_UNIT}: {r['unit']} reported, {r['expected_unit']} expected")
        return out

    vals["flags"] = vals.apply(flags, axis=1)
    vals["issues"] = vals["flags"].map(lambda f: "; ".join(f) if f else "None")
    vals["flag_count"] = vals["flags"].map(len)
    cols = ["row_id", "indicator_id", "name", "definition", "scope", "program_id", "period", "value",
            "unit", "expected_unit", "source", "owner", "verification_status", "issues", "flag_count"]
    return vals[cols].sort_values(["indicator_id", "period", "scope"]).reset_index(drop=True)


def filter_esg(esg: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """Organization-wide rows are always shown; program rows follow the program filter."""
    in_program = esg["program_id"].isna() | esg["program_id"].isin(scope.program_ids)
    return esg[in_program & esg["period"].isin(scope.months)].reset_index(drop=True)
