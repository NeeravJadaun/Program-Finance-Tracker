from pft import metrics
from pft import reconciliation as recon
from pft.data import Scope, full_scope


def _by_rule(exc):
    return {rule: set(g["record_id"]) for rule, g in exc.groupby("rule")}


def test_each_seeded_exception_is_flagged(frames):
    exc = recon.run_reconciliation(frames)
    rules = _by_rule(exc)
    assert set(rules) == set(recon.RULES)
    assert len(rules["MISSING_RECEIPT"]) == 3
    assert len(rules["PARTIAL_SUPPORT"]) == 1
    assert len(rules["AMOUNT_MISMATCH"]) == 2
    assert len(rules["DUPLICATE_RECEIPT"]) == 1
    assert len(rules["UNKNOWN_VENDOR"]) == 1
    assert rules["PO_EXCEEDED"] == {"PO-1005"}
    assert exc["exception_id"].is_unique
    assert (exc["status"] == "Open").all()


def test_exception_ids_are_stable_between_runs(frames):
    a = recon.run_reconciliation(frames)["exception_id"].tolist()
    b = recon.run_reconciliation(frames)["exception_id"].tolist()
    assert a == b


def test_missing_receipt(frames):
    exc = recon.run_reconciliation(frames)
    for _, e in exc[exc["rule"] == "MISSING_RECEIPT"].iterrows():
        assert not (frames["receipts"]["txn_id"] == e["record_id"]).any()
        assert e["category"] == recon.SUPPORT
        assert e["supported_cents"] == 0


def test_partial_receipt_is_missing_support_not_error(frames):
    e = recon.run_reconciliation(frames).query("rule == 'PARTIAL_SUPPORT'").iloc[0]
    receipts = frames["receipts"][frames["receipts"]["txn_id"] == e["record_id"]]
    assert (receipts["receipt_type"] == "partial").all()
    assert e["supported_cents"] == receipts["amount_cents"].sum()
    assert 0 < e["difference_cents"] < e["recorded_cents"]
    assert e["category"] == recon.SUPPORT and e["severity"] == "Medium"


def test_amount_mismatch_is_financial_error(frames):
    exc = recon.run_reconciliation(frames).query("rule == 'AMOUNT_MISMATCH'")
    diffs = sorted(exc["difference_cents"])
    assert diffs == [-36_000, 125_000]  # recorded CA$360 below / CA$1,250 above receipts
    assert (exc["category"] == recon.FINANCIAL).all()
    assert (exc["severity"] == "High").all()


def test_split_receipts_are_summed_before_comparison(frames):
    rec = frames["receipts"]
    counts = rec.groupby("txn_id").size()
    split = counts[counts > 1].index
    assert len(split) == 2
    match = recon.match_table(frames).set_index("txn_id")
    for txn_id in split:
        assert match.loc[txn_id, "support_status"] == "Matched"
        assert match.loc[txn_id, "receipt_total_cents"] == match.loc[txn_id, "amount_cents"]
    flagged = set(recon.run_reconciliation(frames)["record_id"])
    assert not flagged & set(split)


def test_duplicate_receipt_id(frames):
    e = recon.run_reconciliation(frames).query("rule == 'DUPLICATE_RECEIPT'").iloc[0]
    rows = frames["receipts"][frames["receipts"]["receipt_id"] == e["record_id"]]
    assert rows["txn_id"].nunique() == 2
    assert e["related_txns"] == ", ".join(sorted(rows["txn_id"]))


def test_unknown_vendor(frames):
    e = recon.run_reconciliation(frames).query("rule == 'UNKNOWN_VENDOR'").iloc[0]
    txn = frames["transactions"].set_index("txn_id").loc[e["record_id"]]
    assert txn["vendor_id"] not in set(frames["vendors"]["vendor_id"])


def test_po_exceeded(frames):
    e = recon.run_reconciliation(frames).query("rule == 'PO_EXCEEDED'").iloc[0]
    po = frames["purchase_orders"].set_index("po_id").loc["PO-1005"]
    spend = frames["transactions"].query("po_id == 'PO-1005'")["amount_cents"].sum()
    assert e["recorded_cents"] == spend
    assert e["supported_cents"] == po["amount_cents"]
    assert e["difference_cents"] == spend - po["amount_cents"] > 0


def test_flagged_expenses_are_not_silently_fixed(frames):
    """Flagged expenses still count in actual spend exactly as recorded."""
    bva = metrics.budget_vs_actual(frames, full_scope(frames))
    assert metrics.totals(bva)["actual_cents"] == frames["transactions"]["amount_cents"].sum()


def test_exception_filtering_by_scope(frames):
    exc = recon.run_reconciliation(frames)
    scoped = recon.filter_exceptions(exc, Scope(("P02",), ("2026-07", "2026-08")))
    assert set(scoped["program_id"]) == {"P02"}
    assert set(scoped["rule"]) == {"DUPLICATE_RECEIPT", "PO_EXCEEDED"}
