import pandas as pd

from pft import metrics
from pft.data import Scope, full_scope
from pft.money import fmt_pct


def test_seed_shape(frames):
    assert len(frames["programs"]) == 4
    assert len(frames["vendors"]) == 12
    assert len(frames["budgets"]) == 24
    assert len(frames["transactions"]) == 100
    assert frames["transactions"]["amount_cents"].dtype.kind == "i"
    assert frames["budgets"]["budget_cents"].dtype.kind == "i"


def test_totals_match_raw_tables(frames):
    bva = metrics.budget_vs_actual(frames, full_scope(frames))
    t = metrics.totals(bva)
    assert t["budget_cents"] == frames["budgets"]["budget_cents"].sum()
    assert t["actual_cents"] == frames["transactions"]["amount_cents"].sum()
    assert t["variance_cents"] == t["actual_cents"] - t["budget_cents"]
    assert t["remaining_cents"] == t["budget_cents"] - t["actual_cents"]
    assert t["txn_count"] == 100


def test_program_totals_match_raw_tables(frames):
    prog = metrics.by_program(metrics.budget_vs_actual(frames, full_scope(frames))).set_index("program_id")
    raw_budget = frames["budgets"].groupby("program_id")["budget_cents"].sum()
    raw_actual = frames["transactions"].groupby("program_id")["amount_cents"].sum()
    pd.testing.assert_series_equal(prog["budget_cents"], raw_budget, check_names=False)
    pd.testing.assert_series_equal(prog["actual_cents"], raw_actual, check_names=False)
    # Positive variance means overspend.
    for pid, row in prog.iterrows():
        assert (row["variance_cents"] > 0) == (raw_actual[pid] > raw_budget[pid])


def test_join_does_not_duplicate_budgets(frames):
    bva = metrics.budget_vs_actual(frames, full_scope(frames))
    assert len(bva) == len(frames["budgets"])
    assert not bva.duplicated(["program_id", "month"]).any()
    assert bva["budget_cents"].sum() == frames["budgets"]["budget_cents"].sum()

    # The naive approach (join transactions to budgets, then sum) inflates budgets.
    naive = frames["transactions"].merge(frames["budgets"], on=["program_id", "month"])
    assert naive["budget_cents"].sum() > frames["budgets"]["budget_cents"].sum()


def test_zero_budget_month_reports_na(frames):
    scope = Scope(("P03",), ("2026-04",))
    bva = metrics.budget_vs_actual(frames, scope)
    assert len(bva) == 1
    row = bva.iloc[0]
    assert row["budget_cents"] == 0
    assert row["actual_cents"] == 485_000
    assert row["variance_cents"] == 485_000
    assert row["remaining_cents"] == -485_000
    assert row["variance_pct"] is None
    assert fmt_pct(row["variance_pct"]) == "N/A"
    t = metrics.totals(bva)
    assert t["variance_pct"] is None and t["utilization"] is None
    assert any("N/A" in f for f in metrics.findings(bva, None))


def test_filters_restrict_every_total(frames):
    scope = Scope(("P01", "P02"), ("2026-06", "2026-07"))
    bva = metrics.budget_vs_actual(frames, scope)
    tx = frames["transactions"]
    tx = tx[tx["program_id"].isin(scope.program_ids) & tx["month"].isin(scope.months)]
    b = frames["budgets"]
    b = b[b["program_id"].isin(scope.program_ids) & b["month"].isin(scope.months)]
    assert set(bva["program_id"]) == {"P01", "P02"}
    assert set(bva["month"]) == {"2026-06", "2026-07"}
    assert bva["actual_cents"].sum() == tx["amount_cents"].sum()
    assert bva["budget_cents"].sum() == b["budget_cents"].sum()


def test_empty_scope(frames):
    bva = metrics.budget_vs_actual(frames, Scope((), ()))
    assert bva.empty
    assert metrics.totals(bva)["budget_cents"] == 0
    assert metrics.findings(bva, None) == []
