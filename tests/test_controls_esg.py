from datetime import datetime

import pandas as pd
import pytest

from pft import controls as ctl
from pft import db, esg
from pft import reconciliation as recon
from pft.data import Scope, load_frames


def test_control_update_persists_with_history(db_file, conn):
    n = ctl.update_control(conn, "CTL-05", "In progress", "  Reviewing two new vendors  ")
    assert n == 2
    conn.close()

    fresh = db.connect(db_file)  # survives a new connection, i.e. an app restart
    row = fresh.execute("SELECT status, notes, updated_at FROM controls WHERE control_id='CTL-05'").fetchone()
    assert row["status"] == "In progress"
    assert row["notes"] == "Reviewing two new vendors"
    hist = ctl.history(fresh, "control", "CTL-05")
    assert set(hist["field"]) == {"status", "notes"}
    status = hist[hist["field"] == "status"].iloc[0]
    assert (status["old_value"], status["new_value"]) == ("Complete", "In progress")
    datetime.fromisoformat(status["changed_at"])  # valid ISO timestamp
    assert status["changed_at"] == row["updated_at"]

    # A second change appends rather than overwrites history.
    ctl.update_control(fresh, "CTL-05", "Complete", "Reviewing two new vendors")
    hist = ctl.history(fresh, "control", "CTL-05")
    assert len(hist) == 3
    assert hist.iloc[0]["new_value"] == "Complete"  # most recent first
    fresh.close()


def test_control_noop_and_invalid_status(conn):
    row = conn.execute("SELECT status, notes FROM controls WHERE control_id='CTL-01'").fetchone()
    assert ctl.update_control(conn, "CTL-01", row["status"], row["notes"]) == 0
    assert ctl.history(conn, "control", "CTL-01").empty
    with pytest.raises(ValueError):
        ctl.update_control(conn, "CTL-01", "Certified", "")


def test_exception_review_persists_and_feeds_open_count(db_file, conn):
    frames = load_frames(conn)
    exc = recon.run_reconciliation(frames)
    target = exc.iloc[0]["exception_id"]
    before = recon.open_count(exc)
    assert ctl.update_exception(conn, target, "Resolved", "Vendor credit note received") == 2
    conn.close()

    fresh = db.connect(db_file)
    exc2 = recon.run_reconciliation(load_frames(fresh))
    row = exc2.set_index("exception_id").loc[target]
    assert row["status"] == "Resolved" and row["note"] == "Vendor credit note received"
    assert recon.open_count(exc2) == before - 1
    assert len(exc2) == len(exc)  # resolved exceptions are still listed, not deleted
    assert len(ctl.history(fresh, "exception", target)) == 2
    fresh.close()


def test_controls_filter(frames):
    out = ctl.filter_controls(frames["controls"], frames["programs"], Scope(("P02",), ("2026-07",)))
    assert set(out["control_id"]) == {"CTL-03", "CTL-04", "CTL-05"}
    assert set(out["scope"]) == {"Rural Health Access", "Organization-wide"}


def test_esg_flags(frames):
    v = esg.validate(frames)
    flagged = v[v["flag_count"] > 0]
    assert len(flagged) == 4
    issues = " | ".join(flagged["issues"])
    assert esg.FLAG_MISSING_VALUE in issues
    assert esg.FLAG_MISSING_SOURCE in issues
    assert "MWh reported, kWh expected" in issues
    assert "sessions reported, participants expected" in issues


def test_esg_missing_value_is_not_zero_and_units_not_converted(frames):
    v = esg.validate(frames)
    missing = v[v["issues"].str.contains(esg.FLAG_MISSING_VALUE)]
    assert len(missing) == 1 and pd.isna(missing.iloc[0]["value"])
    mwh = v[v["unit"] == "MWh"].iloc[0]
    assert mwh["value"] == 3.9  # left as reported, not multiplied to kWh


def test_esg_filter_keeps_org_rows(frames):
    v = esg.filter_esg(esg.validate(frames), Scope(("P01",), ("2026-05",)))
    assert set(v["scope"]) == {"Youth Skills Pathways", "Organization-wide"}
