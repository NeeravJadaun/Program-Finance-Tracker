"""SQLite schema and connection helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "data" / "finance_demo.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
    program_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    manager      TEXT NOT NULL,
    color        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL
);

-- Budgets are one row per program per month. Kept separate from transactions
-- so that joining never repeats a budget once per transaction.
CREATE TABLE IF NOT EXISTS budgets (
    program_id   TEXT NOT NULL REFERENCES programs(program_id),
    month        TEXT NOT NULL,              -- YYYY-MM
    budget_cents INTEGER NOT NULL CHECK (budget_cents >= 0),
    PRIMARY KEY (program_id, month)
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id        TEXT PRIMARY KEY,
    program_id   TEXT NOT NULL REFERENCES programs(program_id),
    vendor_id    TEXT NOT NULL,
    issue_date   TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    description  TEXT NOT NULL
);

-- vendor_id is deliberately not a foreign key: unknown vendors are flagged
-- by reconciliation rather than rejected at insert time.
CREATE TABLE IF NOT EXISTS transactions (
    txn_id       TEXT PRIMARY KEY,
    program_id   TEXT NOT NULL REFERENCES programs(program_id),
    txn_date     TEXT NOT NULL,              -- YYYY-MM-DD
    vendor_id    TEXT NOT NULL,
    po_id        TEXT,
    amount_cents INTEGER NOT NULL,
    category     TEXT NOT NULL,
    description  TEXT NOT NULL
);

-- receipt_id is not unique on purpose: duplicates are a reconciliation finding.
CREATE TABLE IF NOT EXISTS receipts (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id    TEXT NOT NULL,
    txn_id        TEXT NOT NULL,
    receipt_date  TEXT NOT NULL,
    amount_cents  INTEGER NOT NULL,
    receipt_type  TEXT NOT NULL CHECK (receipt_type IN ('full', 'partial')),
    file_ref      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS controls (
    control_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    description   TEXT NOT NULL,
    program_id    TEXT,                      -- NULL = organization-wide
    evidence_ref  TEXT NOT NULL,
    owner         TEXT NOT NULL,
    due_date      TEXT NOT NULL,
    status        TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exception_reviews (
    exception_id  TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    note          TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    change_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,              -- 'control' or 'exception'
    entity_id    TEXT NOT NULL,
    field        TEXT NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    changed_at   TEXT NOT NULL,              -- ISO 8601 UTC
    changed_by   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS esg_indicators (
    indicator_id  TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    definition    TEXT NOT NULL,
    expected_unit TEXT NOT NULL,
    owner         TEXT NOT NULL
);

-- value may be NULL: missing values stay missing and are never coerced to 0.
CREATE TABLE IF NOT EXISTS esg_values (
    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    indicator_id  TEXT NOT NULL REFERENCES esg_indicators(indicator_id),
    program_id    TEXT,                      -- NULL = organization-wide
    period        TEXT NOT NULL,             -- YYYY-MM
    value         REAL,
    unit          TEXT NOT NULL,
    source        TEXT,
    owner         TEXT NOT NULL,
    verification_status TEXT NOT NULL
);
"""


def db_path() -> Path:
    return Path(os.environ.get("PFT_DB_PATH", DEFAULT_DB_PATH))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def is_seeded(conn: sqlite3.Connection) -> bool:
    try:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] > 0
    except sqlite3.OperationalError:
        return False
