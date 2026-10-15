"""Match expenses to purchase orders and receipts, and flag exceptions.

Exceptions are reported, never corrected: flagged expenses remain in actual
spend exactly as recorded until a person reviews them.

Receipt amounts are summed per expense before comparison, so an expense paid
in instalments with several receipts is matched when the receipts add up.
"""

from __future__ import annotations

import pandas as pd

from pft.data import Scope
from pft.money import fmt_cad

FINANCIAL = "Financial error"
SUPPORT = "Missing support"
CONTROL = "Control breach"

RULES = {
    "MISSING_RECEIPT": ("Missing receipt", SUPPORT, "Medium"),
    "PARTIAL_SUPPORT": ("Partial receipt support", SUPPORT, "Medium"),
    "AMOUNT_MISMATCH": ("Receipt amount mismatch", FINANCIAL, "High"),
    "DUPLICATE_RECEIPT": ("Duplicate receipt ID", FINANCIAL, "High"),
    "UNKNOWN_VENDOR": ("Unknown vendor", CONTROL, "High"),
    "PO_EXCEEDED": ("Spend exceeds PO", CONTROL, "High"),
}

RULE_HELP = {
    "MISSING_RECEIPT": "Expense has no receipt attached. A documentation gap, not proof the amount is wrong.",
    "PARTIAL_SUPPORT": "Receipts marked partial (instalments or deposits) cover less than the expense. The rest is unsupported, not proven wrong.",
    "AMOUNT_MISMATCH": "Summed receipts differ from the recorded expense, and the receipts are not partial. Possible entry or payment error.",
    "DUPLICATE_RECEIPT": "The same receipt ID supports more than one expense. Possible duplicate claim.",
    "UNKNOWN_VENDOR": "Vendor ID on the expense is not in the approved vendor master.",
    "PO_EXCEEDED": "Total expenses against a purchase order exceed its approved amount.",
}

STATUSES = ["Open", "Under review", "Resolved"]

EXCEPTION_COLUMNS = ["exception_id", "rule", "rule_label", "category", "severity", "record_type",
                     "record_id", "program_id", "month", "recorded_cents", "supported_cents",
                     "difference_cents", "related_txns", "explanation", "status", "note"]


def match_table(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per expense with its PO, summed receipts and support status."""
    txns = frames["transactions"].copy()
    rec = frames["receipts"]
    agg = (rec.groupby("txn_id")
           .agg(receipt_total_cents=("amount_cents", "sum"),
                receipt_count=("row_id", "count"),
                has_partial=("receipt_type", lambda s: bool((s == "partial").any())),
                receipt_ids=("receipt_id", lambda s: ", ".join(s)))
           .reset_index())
    df = txns.merge(agg, on="txn_id", how="left")
    df["receipt_total_cents"] = df["receipt_total_cents"].fillna(0).astype("int64")
    df["receipt_count"] = df["receipt_count"].fillna(0).astype("int64")
    df["has_partial"] = df["has_partial"].astype("boolean").fillna(False).astype(bool)
    df["receipt_ids"] = df["receipt_ids"].fillna("")
    df["difference_cents"] = df["amount_cents"] - df["receipt_total_cents"]
    vendors = frames["vendors"].set_index("vendor_id")["name"]
    df["vendor_known"] = df["vendor_id"].isin(vendors.index)
    df["vendor_name"] = df["vendor_id"].map(vendors).fillna("Not in vendor master")
    df["support_status"] = [_support_status(r) for r in df.itertuples()]
    return df


def _support_status(r) -> str:
    if r.receipt_count == 0:
        return "No receipt"
    if r.difference_cents == 0:
        return "Matched"
    if r.has_partial and r.difference_cents > 0:
        return "Partial support"
    return "Amount mismatch"


def _exc(rule: str, record_type: str, record_id: str, program_id: str, month: str,
         recorded: int, supported: int | None, related: list[str], explanation: str) -> dict:
    label, category, severity = RULES[rule]
    return {
        "exception_id": f"{rule}:{record_id}", "rule": rule, "rule_label": label,
        "category": category, "severity": severity, "record_type": record_type,
        "record_id": record_id, "program_id": program_id, "month": month,
        "recorded_cents": recorded, "supported_cents": supported,
        "difference_cents": None if supported is None else recorded - supported,
        "related_txns": ", ".join(related), "explanation": explanation,
    }


def run_reconciliation(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute every exception across the full dataset, with review status."""
    m = match_table(frames)
    rows: list[dict] = []

    for r in m.itertuples():
        if r.support_status == "No receipt":
            rows.append(_exc("MISSING_RECEIPT", "Expense", r.txn_id, r.program_id, r.month,
                             r.amount_cents, 0, [r.txn_id],
                             f"No receipt is attached to this {fmt_cad(r.amount_cents)} expense. "
                             "This is missing support, not a proven error in the amount."))
        elif r.support_status == "Partial support":
            rows.append(_exc("PARTIAL_SUPPORT", "Expense", r.txn_id, r.program_id, r.month,
                             r.amount_cents, r.receipt_total_cents, [r.txn_id],
                             f"Partial receipts total {fmt_cad(r.receipt_total_cents)} of "
                             f"{fmt_cad(r.amount_cents)}; {fmt_cad(r.difference_cents)} is not yet "
                             "supported. Request the balance receipt before treating it as an error."))
        elif r.support_status == "Amount mismatch":
            direction = "above" if r.difference_cents > 0 else "below"
            rows.append(_exc("AMOUNT_MISMATCH", "Expense", r.txn_id, r.program_id, r.month,
                             r.amount_cents, r.receipt_total_cents, [r.txn_id],
                             f"Recorded expense {fmt_cad(r.amount_cents)} is "
                             f"{fmt_cad(abs(r.difference_cents))} {direction} its receipts "
                             f"({fmt_cad(r.receipt_total_cents)}). Possible entry or payment error."))
        if not r.vendor_known:
            rows.append(_exc("UNKNOWN_VENDOR", "Expense", r.txn_id, r.program_id, r.month,
                             r.amount_cents, None, [r.txn_id],
                             f"Vendor ID {r.vendor_id} is not in the vendor master. The "
                             f"{fmt_cad(r.amount_cents)} remains in actual spend until the "
                             "vendor is approved or the expense is reversed."))

    rec = frames["receipts"].merge(m[["txn_id", "program_id", "month", "txn_date", "amount_cents"]]
                                   .rename(columns={"amount_cents": "txn_amount_cents"}), on="txn_id")
    for receipt_id, grp in rec.groupby("receipt_id"):
        if grp["txn_id"].nunique() > 1:
            grp = grp.sort_values("txn_date")
            latest = grp.iloc[-1]
            related = list(grp["txn_id"])
            rows.append(_exc("DUPLICATE_RECEIPT", "Receipt", receipt_id, latest["program_id"],
                             latest["month"], int(grp["txn_amount_cents"].sum()),
                             int(grp["amount_cents"].iloc[0]), related,
                             f"Receipt {receipt_id} ({fmt_cad(grp['amount_cents'].iloc[0])}) supports "
                             f"{len(related)} expenses: {', '.join(related)}. All remain in actual "
                             "spend; confirm whether one is a duplicate claim."))

    pos = frames["purchase_orders"]
    for po in pos.itertuples():
        spend = m[m["po_id"] == po.po_id].sort_values(["txn_date", "txn_id"])
        if spend.empty:
            continue
        total = int(spend["amount_cents"].sum())
        if total > po.amount_cents:
            cumulative = spend["amount_cents"].cumsum()
            breach = spend[cumulative > po.amount_cents].iloc[0]
            rows.append(_exc("PO_EXCEEDED", "Purchase order", po.po_id, po.program_id,
                             breach["month"], total, int(po.amount_cents), list(spend["txn_id"]),
                             f"Expenses against {po.po_id} total {fmt_cad(total)} versus "
                             f"{fmt_cad(po.amount_cents)} approved, {fmt_cad(total - po.amount_cents)} "
                             f"over. First exceeded by {breach['txn_id']} on {breach['txn_date']}."))

    exc = pd.DataFrame(rows, columns=EXCEPTION_COLUMNS[:-2])
    reviews = frames["exception_reviews"][["exception_id", "status", "note"]]
    exc = exc.merge(reviews, on="exception_id", how="left")
    exc["status"] = exc["status"].fillna("Open")
    exc["note"] = exc["note"].fillna("")
    sev_order = {"High": 0, "Medium": 1}
    exc = (exc.assign(_s=exc["severity"].map(sev_order))
           .sort_values(["_s", "rule", "record_id"]).drop(columns="_s").reset_index(drop=True))
    return exc[EXCEPTION_COLUMNS]


def filter_exceptions(exc: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """Exceptions are assigned to the program and month of the triggering record."""
    mask = exc["program_id"].isin(scope.program_ids) & exc["month"].isin(scope.months)
    return exc[mask].reset_index(drop=True)


def open_count(exc: pd.DataFrame) -> int:
    return int((exc["status"] != "Resolved").sum())
