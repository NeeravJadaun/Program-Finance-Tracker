"""Control checklist and exception review updates with a timestamped change history.

This is a demo workflow. It records who changed what and when inside a local
SQLite file; it is not a certified internal-control system.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pandas as pd

from pft.data import Scope

CONTROL_STATUSES = ["Not started", "In progress", "Needs follow-up", "Complete"]
DEMO_USER = "demo user"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log(conn, entity_type, entity_id, field, old, new, changed_at, changed_by):
    conn.execute(
        "INSERT INTO change_log (entity_type, entity_id, field, old_value, new_value, changed_at, changed_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, field, old, new, changed_at, changed_by),
    )


def update_control(conn: sqlite3.Connection, control_id: str, status: str, notes: str,
                   changed_by: str = DEMO_USER) -> int:
    """Persist a status/notes change. Returns the number of fields changed (0 = no-op)."""
    if status not in CONTROL_STATUSES:
        raise ValueError(f"Unknown status: {status}")
    row = conn.execute("SELECT status, notes FROM controls WHERE control_id = ?", (control_id,)).fetchone()
    if row is None:
        raise KeyError(control_id)
    notes = notes.strip()
    changes = [(f, old, new) for f, old, new in
               [("status", row["status"], status), ("notes", row["notes"], notes)] if old != new]
    if not changes:
        return 0
    ts = _now()
    with conn:
        conn.execute("UPDATE controls SET status = ?, notes = ?, updated_at = ? WHERE control_id = ?",
                     (status, notes, ts, control_id))
        for field, old, new in changes:
            _log(conn, "control", control_id, field, old, new, ts, changed_by)
    return len(changes)


def update_exception(conn: sqlite3.Connection, exception_id: str, status: str, note: str,
                     changed_by: str = DEMO_USER) -> int:
    """Record a review status for a computed exception. The underlying data is not changed."""
    from pft.reconciliation import STATUSES

    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    row = conn.execute("SELECT status, note FROM exception_reviews WHERE exception_id = ?",
                       (exception_id,)).fetchone()
    old_status, old_note = (row["status"], row["note"]) if row else ("Open", "")
    note = note.strip()
    changes = [(f, old, new) for f, old, new in
               [("status", old_status, status), ("note", old_note, note)] if old != new]
    if not changes:
        return 0
    ts = _now()
    with conn:
        conn.execute(
            "INSERT INTO exception_reviews (exception_id, status, note, updated_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(exception_id) DO UPDATE SET status = excluded.status, note = excluded.note,"
            " updated_at = excluded.updated_at",
            (exception_id, status, note, ts))
        for field, old, new in changes:
            _log(conn, "exception", exception_id, field, old, new, ts, changed_by)
    return len(changes)


def history(conn: sqlite3.Connection, entity_type: str | None = None,
            entity_id: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM change_log WHERE 1=1"
    params: list = []
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    if entity_id:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    return pd.read_sql_query(sql + " ORDER BY change_id DESC", conn, params=params)


def filter_controls(controls: pd.DataFrame, programs: pd.DataFrame, scope: Scope) -> pd.DataFrame:
    """Controls for the selected programs plus organization-wide controls,
    with a due date in the selected months."""
    df = controls.copy()
    in_program = df["program_id"].isna() | df["program_id"].isin(scope.program_ids)
    in_months = df["due_date"].str[:7].isin(scope.months)
    df = df[in_program & in_months]
    names = programs.set_index("program_id")["name"]
    df["scope"] = df["program_id"].map(names).fillna("Organization-wide")
    return df.sort_values(["due_date", "control_id"]).reset_index(drop=True)
