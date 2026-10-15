"""Deterministic synthetic seed data.

Run:  python -m pft.seed            (seed only if the database is empty)
      python -m pft.seed --reset    (drop and rebuild from scratch)

Every name, vendor, amount and indicator here is fictional. The same seed
always produces the same IDs, so exception IDs stay stable between rebuilds.
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from pft import db

SEED = 20260415
MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
REPORT_AS_OF = "2026-09-30"

PROGRAMS = [
    # id, name, manager, chart color, base monthly budget (CAD dollars)
    ("P01", "Youth Skills Pathways", "Amara Osei", "#0F766E", 92_000),
    ("P02", "Rural Health Access", "Daniel Kim", "#1D4ED8", 118_000),
    ("P03", "Community Literacy", "Lucia Torres", "#7C3AED", 61_000),
    ("P04", "Clean Water Partnerships", "Priya Nair", "#BE185D", 76_000),
]

VENDORS = [
    ("V01", "Northwind Training Co.", "Training delivery"),
    ("V02", "Maple Facilitation Group", "Facilitation"),
    ("V03", "Cedar Community Venues", "Venue hire"),
    ("V04", "Clearpath Logistics", "Logistics"),
    ("V05", "Harbor Mobile Clinics", "Field services"),
    ("V06", "Lakeshore Catering", "Catering"),
    ("V07", "Brightline Print Shop", "Printing"),
    ("V08", "Summit Translation Ltd.", "Translation"),
    ("V09", "Pinewood Office Supply", "Supplies"),
    ("V10", "Riverbend Evaluation Partners", "Evaluation"),
    ("V11", "Trillium Travel Desk", "Travel"),
    ("V12", "Granite Field Equipment", "Equipment"),
]

PROGRAM_VENDORS = {
    "P01": ["V01", "V02", "V03"],
    "P02": ["V04", "V05", "V06"],
    "P03": ["V07", "V08", "V09"],
    "P04": ["V10", "V11", "V12"],
}

# Month multipliers give the budget a realistic shape instead of a flat line.
MONTH_FACTOR = [0.90, 1.00, 1.05, 0.95, 1.10, 1.00]

UNKNOWN_VENDOR_ID = "V-UNLISTED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _split(total: int, parts: int, rng: random.Random) -> list[int]:
    weights = [rng.uniform(0.6, 1.4) for _ in range(parts)]
    scale = sum(weights)
    amounts = [int(total * w / scale) for w in weights[:-1]]
    amounts.append(total - sum(amounts))
    return amounts


def build_dataset() -> dict[str, list[dict]]:
    """Build every seed table in memory. Pure function of SEED."""
    rng = random.Random(SEED)
    vendor_lookup = {v[0]: v for v in VENDORS}

    budgets = []
    for pid, _, _, _, base in PROGRAMS:
        for i, month in enumerate(MONTHS):
            # Community Literacy launches in May: zero April budget, but one
            # start-up cost is booked in April (tests N/A percentage variance).
            dollars = 0 if (pid == "P03" and month == "2026-04") else round(base * MONTH_FACTOR[i], -2)
            budgets.append({"program_id": pid, "month": month, "budget_cents": int(dollars * 100)})

    txns: list[dict] = []
    for b in budgets:
        pid, month = b["program_id"], b["month"]
        if b["budget_cents"] == 0:
            txns.append({
                "program_id": pid, "txn_date": f"{month}-22", "vendor_id": "V07",
                "amount_cents": 485_000, "tag": "zero_budget",
                "description": "Launch materials printed ahead of program start",
            })
            continue
        n = 5 if (month == "2026-06" or (pid == "P01" and month == "2026-09")) else 4
        target = int(b["budget_cents"] * rng.uniform(0.86, 1.10))
        for amount in _split(target, n, rng):
            vid = rng.choice(PROGRAM_VENDORS[pid])
            txns.append({
                "program_id": pid, "txn_date": f"{month}-{rng.randint(2, 27):02d}",
                "vendor_id": vid, "amount_cents": amount, "tag": None,
                "description": f"{vendor_lookup[vid][2]} - {month}",
            })

    # Injected: a second claim reusing an existing receipt (duplicate receipt ID).
    original = next(t for t in txns if t["program_id"] == "P02" and t["txn_date"].startswith("2026-07"))
    original["tag"] = "dup_original"
    txns.append({**original, "txn_date": "2026-07-28", "tag": "dup_copy",
                 "description": original["description"] + " (resubmitted claim)"})

    # Injected: spend with a vendor that is not in the vendor master.
    txns.append({
        "program_id": "P04", "txn_date": "2026-08-19", "vendor_id": UNKNOWN_VENDOR_ID,
        "amount_cents": 237_500, "tag": "unknown_vendor",
        "description": "Pump repair - Quickfix Facility Repairs (not in vendor master)",
    })

    txns.sort(key=lambda t: (t["txn_date"], t["program_id"], t["amount_cents"]))
    for i, t in enumerate(txns, start=1):
        t["txn_id"] = f"TXN-{i:04d}"
        t["category"] = vendor_lookup[t["vendor_id"]][2] if t["vendor_id"] in vendor_lookup else "Repairs"

    # One PO per program/vendor pair covering the six months.
    pos = []
    po_by_pair = {}
    n = 1001
    for pid, *_ in PROGRAMS:
        for vid in PROGRAM_VENDORS[pid]:
            po_id = f"PO-{n}"
            po_by_pair[(pid, vid)] = po_id
            pos.append({"po_id": po_id, "program_id": pid, "vendor_id": vid,
                        "issue_date": "2026-03-20",
                        "description": f"{vendor_lookup[vid][2]}, Apr to Sep 2026"})
            n += 1
    for t in txns:
        t["po_id"] = po_by_pair.get((t["program_id"], t["vendor_id"]))
    for po in pos:
        spend = sum(t["amount_cents"] for t in txns if t["po_id"] == po["po_id"])
        if (po["program_id"], po["vendor_id"]) == ("P02", "V05"):
            # Injected: PO approved below eventual spend (spend exceeds PO).
            po["amount_cents"] = math.floor(spend * 0.93 / 50_000) * 50_000
        else:
            po["amount_cents"] = math.ceil(spend * 1.08 / 50_000) * 50_000

    # Receipts. Seeded issues are spread across programs and months.
    ordinary = [t for t in txns if t["tag"] is None]

    def pick(pid: str, month: str, k: int = 0) -> str:
        return [t for t in ordinary if t["program_id"] == pid and t["txn_date"].startswith(month)][k]["txn_id"]

    missing = {pick("P01", "2026-05"), pick("P03", "2026-07"), pick("P04", "2026-09")}
    partial_support = pick("P01", "2026-08")
    mismatch_high = pick("P03", "2026-06")
    mismatch_low = pick("P04", "2026-08")
    split_complete = {pick("P02", "2026-05"), pick("P04", "2026-04")}

    receipts = []
    seq = 1

    def add(t, amount, rtype, receipt_id=None):
        nonlocal seq
        rid = receipt_id or f"RCT-{seq:04d}"
        if receipt_id is None:
            seq += 1
        receipts.append({"receipt_id": rid, "txn_id": t["txn_id"], "receipt_date": t["txn_date"],
                         "amount_cents": amount, "receipt_type": rtype,
                         "file_ref": f"receipts/{t['txn_date'][:7]}/{rid}.pdf"})
        return rid

    dup_receipt_id = None
    for t in txns:
        tid, amt = t["txn_id"], t["amount_cents"]
        if tid in missing:
            continue
        if t["tag"] == "dup_copy":
            continue  # attached after the original receipt exists
        if tid == partial_support:
            add(t, int(amt * 0.6), "partial")  # deposit invoice; balance not yet supported
        elif tid == mismatch_high:
            add(t, amt + 36_000, "full")  # receipt CA$360 higher than the recorded expense
        elif tid == mismatch_low:
            add(t, amt - 125_000, "full")  # recorded expense CA$1,250 above the receipt
        elif tid in split_complete:
            first = amt // 2
            add(t, first, "partial")
            add(t, amt - first, "partial")  # two instalments that fully support the expense
        else:
            rid = add(t, amt, "full")
            if t["tag"] == "dup_original":
                dup_receipt_id = rid
    dup_copy = next(t for t in txns if t["tag"] == "dup_copy")
    add(dup_copy, dup_copy["amount_cents"], "full", receipt_id=dup_receipt_id)

    for t in txns:
        t.pop("tag")

    controls = [
        ("CTL-01", "Monthly budget-vs-actual sign-off", "Program manager reviews variances above 5% and documents explanations.", None, "EVD-BVA-2026-04", "Finance Lead", "2026-05-10", "Complete", "Signed off; Literacy start-up cost noted."),
        ("CTL-02", "Bank-to-ledger reconciliation", "Operating account balance agreed to general ledger.", None, "EVD-BANK-2026-05", "Finance Officer", "2026-06-10", "Complete", ""),
        ("CTL-03", "PO approved before commitment", "Spend is committed only against an approved PO with remaining balance.", "P02", "EVD-PO-P02-Q2", "Daniel Kim", "2026-07-15", "Needs follow-up", "PO-1005 spend appears to exceed approved amount."),
        ("CTL-04", "Receipt matching review", "Each expense is supported by receipts that sum to the recorded amount.", None, "EVD-RCPT-2026-06", "Finance Officer", "2026-07-10", "Complete", "Q2 expenses matched; exceptions logged in Reconciliation."),
        ("CTL-05", "Vendor master change review", "New or changed vendors are approved before payment.", None, "EVD-VEND-2026-Q2", "Finance Lead", "2026-07-31", "Complete", ""),
        ("CTL-06", "Program expense allocation review", "Shared costs are allocated to the correct program code.", "P01", "EVD-ALLOC-P01-07", "Amara Osei", "2026-08-10", "Complete", ""),
        ("CTL-07", "Payment approval segregation check", "Payment preparer and approver are different people.", None, "EVD-SOD-2026-07", "Finance Lead", "2026-08-15", "In progress", "Sample of 10 payments selected."),
        ("CTL-08", "Duplicate payment scan", "Receipt IDs and vendor/amount pairs scanned for repeats.", None, "EVD-DUP-2026-07", "Finance Officer", "2026-08-20", "In progress", "RCT-0053 appears on two expenses."),
        ("CTL-09", "Monthly budget-vs-actual sign-off", "Program manager reviews variances above 5% and documents explanations.", "P04", "EVD-BVA-P04-2026-08", "Priya Nair", "2026-09-10", "In progress", ""),
        ("CTL-10", "ESG data source verification", "Each ESG value has a named source document and consistent unit.", None, "EVD-ESG-2026-Q3", "Operations Lead", "2026-09-20", "Not started", ""),
        ("CTL-11", "Training attendance evidence check", "Participation counts agree to attendance registers.", "P03", "EVD-ATT-P03-2026-09", "Lucia Torres", "2026-09-25", "Not started", ""),
        ("CTL-12", "Quarter-end accrual review", "Unbilled services at quarter end are accrued.", None, "EVD-ACCR-2026-Q3", "Finance Lead", "2026-09-30", "Not started", ""),
    ]
    now = _now()
    control_rows = [
        {"control_id": c[0], "name": c[1], "description": c[2], "program_id": c[3], "evidence_ref": c[4],
         "owner": c[5], "due_date": c[6], "status": c[7], "notes": c[8], "updated_at": now}
        for c in controls
    ]

    indicators = [
        {"indicator_id": "ESG-ELEC", "name": "Office electricity use",
         "definition": "Metered electricity consumed by the shared head office in the calendar month, taken from the utility bill.",
         "expected_unit": "kWh", "owner": "Operations Lead"},
        {"indicator_id": "ESG-TRAIN", "name": "Training participation",
         "definition": "Unique individuals who attended at least one program training session in the month, per attendance register.",
         "expected_unit": "participants", "owner": "Program managers"},
    ]
    esg = []
    statuses = ["Verified", "Verified", "Unverified", "Pending review"]
    for i, month in enumerate(MONTHS):
        row = {"indicator_id": "ESG-ELEC", "program_id": None, "period": month,
               "value": float(rng.randint(3_550, 4_350)), "unit": "kWh",
               "source": f"Utility bill, office account, {month}", "owner": "Operations Lead",
               "verification_status": statuses[i % 4]}
        if month == "2026-07":
            row["source"] = None  # injected: missing source
        if month == "2026-09":
            row["value"], row["unit"] = 3.9, "MWh"  # injected: inconsistent unit
        esg.append(row)
    managers = {p[0]: p[2] for p in PROGRAMS}
    for pid, *_ in PROGRAMS:
        for i, month in enumerate(MONTHS):
            if pid == "P03" and month == "2026-04":
                continue  # program not yet running; no value expected
            row = {"indicator_id": "ESG-TRAIN", "program_id": pid, "period": month,
                   "value": float(rng.randint(40, 180)), "unit": "participants",
                   "source": f"Attendance register {pid}-{month}", "owner": managers[pid],
                   "verification_status": statuses[(i + int(pid[-1])) % 4]}
            if pid == "P02" and month == "2026-08":
                row["value"] = None  # injected: missing value (must not become 0)
            if pid == "P04" and month == "2026-06":
                row["unit"] = "sessions"  # injected: inconsistent unit
            esg.append(row)

    return {
        "programs": [{"program_id": p[0], "name": p[1], "manager": p[2], "color": p[3]} for p in PROGRAMS],
        "vendors": [{"vendor_id": v[0], "name": v[1], "category": v[2]} for v in VENDORS],
        "budgets": budgets,
        "purchase_orders": pos,
        "transactions": txns,
        "receipts": receipts,
        "controls": control_rows,
        "esg_indicators": indicators,
        "esg_values": esg,
    }


TABLE_ORDER = ["programs", "vendors", "budgets", "purchase_orders", "transactions",
               "receipts", "controls", "esg_indicators", "esg_values"]


def seed(conn: sqlite3.Connection, reset: bool = False) -> None:
    if reset:
        for table in ["change_log", "exception_reviews", *reversed(TABLE_ORDER)]:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    db.create_schema(conn)
    if db.is_seeded(conn):
        return
    data = build_dataset()
    for table in TABLE_ORDER:
        rows = data[table]
        cols = list(rows[0].keys())
        conn.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [tuple(r[c] for c in cols) for r in rows],
        )
    conn.commit()


def ensure_database(path: Path | str | None = None) -> None:
    conn = db.connect(path)
    try:
        seed(conn, reset=False)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the synthetic finance demo database.")
    parser.add_argument("--reset", action="store_true", help="drop all tables (including review history) and reseed")
    parser.add_argument("--db", help="database path (default: data/finance_demo.db or $PFT_DB_PATH)")
    args = parser.parse_args()
    conn = db.connect(args.db)
    seed(conn, reset=args.reset)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLE_ORDER}
    conn.close()
    print(f"Seeded {args.db or db.db_path()}")
    for table, count in counts.items():
        print(f"  {table:<16} {count:>4}")


if __name__ == "__main__":
    main()
