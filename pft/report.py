"""Single source for everything the UI and the Excel export show for a scope."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pft import controls, esg, metrics, reconciliation
from pft.data import Scope, all_months


@dataclass
class Report:
    scope: Scope
    scope_label: str
    programs_label: str
    months_label: str
    bva: pd.DataFrame            # program-month rows
    programs: pd.DataFrame       # program totals
    months: pd.DataFrame         # month totals
    totals: dict
    exceptions: pd.DataFrame
    open_exceptions: int
    controls: pd.DataFrame
    esg: pd.DataFrame
    findings: list[str]


def build_report(frames: dict[str, pd.DataFrame], scope: Scope) -> Report:
    bva = metrics.budget_vs_actual(frames, scope)
    exc = reconciliation.filter_exceptions(reconciliation.run_reconciliation(frames), scope)
    return Report(
        scope=scope,
        scope_label=scope.label(frames["programs"], all_months(frames)),
        programs_label=scope.programs_label(frames["programs"]),
        months_label=scope.months_label(all_months(frames)),
        bva=bva,
        programs=metrics.by_program(bva),
        months=metrics.by_month(bva),
        totals=metrics.totals(bva),
        exceptions=exc,
        open_exceptions=reconciliation.open_count(exc),
        controls=controls.filter_controls(frames["controls"], frames["programs"], scope),
        esg=esg.filter_esg(esg.validate(frames), scope),
        findings=metrics.findings(bva, exc),
    )
