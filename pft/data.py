"""Load tables from SQLite and describe the active filter scope."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

TABLES = ["programs", "vendors", "budgets", "purchase_orders", "transactions", "receipts",
          "controls", "exception_reviews", "esg_indicators", "esg_values"]


@dataclass(frozen=True)
class Scope:
    """The active program/month filter. Every view and export takes the same Scope."""

    program_ids: tuple[str, ...]
    months: tuple[str, ...]

    def label(self, programs: pd.DataFrame, all_months: list[str]) -> str:
        return f"{self.programs_label(programs)} | {self.months_label(all_months)}"

    def programs_label(self, programs: pd.DataFrame) -> str:
        if set(self.program_ids) == set(programs["program_id"]):
            return "All programs"
        names = programs.set_index("program_id").loc[list(self.program_ids), "name"]
        return ", ".join(names) if len(names) else "No programs"

    def months_label(self, all_months: list[str]) -> str:
        if not self.months:
            return "No months"
        return f"{month_name(self.months[0])} to {month_name(self.months[-1])}" if len(self.months) > 1 \
            else month_name(self.months[0])


def month_name(month: str) -> str:
    return pd.Timestamp(f"{month}-01").strftime("%b %Y")


def load_frames(conn: sqlite3.Connection) -> dict[str, pd.DataFrame]:
    frames = {t: pd.read_sql_query(f"SELECT * FROM {t}", conn) for t in TABLES}
    frames["transactions"]["month"] = frames["transactions"]["txn_date"].str[:7]
    return frames


def all_months(frames: dict[str, pd.DataFrame]) -> list[str]:
    return sorted(set(frames["budgets"]["month"]) | set(frames["transactions"]["month"]))


def full_scope(frames: dict[str, pd.DataFrame]) -> Scope:
    return Scope(tuple(frames["programs"]["program_id"]), tuple(all_months(frames)))
