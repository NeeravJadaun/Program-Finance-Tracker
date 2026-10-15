"""The four app pages. Each renders only from the shared Report, so the UI and
the Excel export always reflect the same filtered data."""

from __future__ import annotations

import html
import sqlite3
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from pft import controls as ctl
from pft import reconciliation as recon
from pft import ui
from pft.data import month_name
from pft.money import fmt_cad, fmt_cad_whole, fmt_pct
from pft.report import Report
from pft.seed import REPORT_AS_OF

FONT = "Source Sans 3, Source Sans Pro, -apple-system, Segoe UI, sans-serif"


@dataclass
class Ctx:
    conn: sqlite3.Connection
    frames: dict[str, pd.DataFrame]
    report: Report
    names: dict[str, str]
    colors: dict[str, str]


def _empty_state(message: str) -> None:
    st.info(message + " Adjust the filters in the sidebar or use Reset filters.", icon=":material/filter_alt_off:")


def _flash() -> None:
    msg = st.session_state.pop("flash", None)
    if msg:
        st.toast(msg, icon=":material/check_circle:")


# --------------------------------------------------------------------------- Overview

def _kpi(key: str, label: str, value: str, help: str, caption: str) -> None:
    with st.container(border=True, key=key):
        st.metric(label, value, help=help)
        st.caption(caption)


def _program_chart(ctx: Ctx, pid: str, ymax: float) -> go.Figure:
    """One small-multiple panel: monthly actual bars in the program colour against
    a dashed budget line, on a y-axis shared by every panel. Overspend months
    carry a text label so the warning never relies on colour alone."""
    months = list(ctx.report.months["month"])
    d = ctx.report.bva[ctx.report.bva["program_id"] == pid].set_index("month").reindex(months)
    labels = [pd.Timestamp(f"{m}-01").strftime("%b") for m in months]
    actual, budget = d["actual_cents"].fillna(0) / 100, d["budget_cents"].fillna(0) / 100
    variance_pct = [fmt_pct(v) for v in d["variance_pct"]]
    fig = go.Figure()
    fig.add_bar(x=labels, y=actual, marker_color=ctx.colors[pid], name="Actual",
                customdata=list(zip(budget, d["variance_cents"].fillna(0) / 100, variance_pct)),
                hovertemplate="<b>%{x}</b><br>Actual: CA$%{y:,.2f}<br>Budget: CA$%{customdata[0]:,.2f}"
                              "<br>Variance: CA$%{customdata[1]:,.2f} (%{customdata[2]})<extra></extra>")
    fig.add_scatter(x=labels, y=budget, mode="lines+markers", name="Budget",
                    line=dict(color=ui.TEXT, width=1.5, dash="dash"), marker=dict(size=5, color=ui.TEXT),
                    hoverinfo="skip")
    over = list(d["variance_cents"].fillna(0) > 0)
    fig.add_scatter(x=[l for l, o in zip(labels, over) if o],
                    y=[max(a, b) for a, b, o in zip(actual, budget, over) if o],
                    text=[t for t, o in zip(variance_pct, over) if o], mode="text", textposition="top center",
                    textfont=dict(size=11, color="#991B1B"), hoverinfo="skip", cliponaxis=False)
    fig.update_layout(
        title=dict(text=html.escape(ctx.names[pid]), x=0, xanchor="left", font=dict(size=14, color=ui.TEXT)),
        height=230, margin=dict(l=44, r=6, t=36, b=4), showlegend=False, bargap=0.3,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", font=dict(family=FONT, color=ui.TEXT, size=12),
        hoverlabel=dict(font_family=FONT),
    )
    fig.update_yaxes(range=[0, ymax], gridcolor=ui.BORDER, zeroline=False, tickprefix="$", tickformat="~s", nticks=4, automargin=True)
    fig.update_xaxes(showgrid=False, tickfont=dict(size=11), fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    return fig


def _bva_charts(ctx: Ctx) -> None:
    bva = ctx.report.bva
    ymax = max(bva["actual_cents"].max(), bva["budget_cents"].max()) / 100 * 1.22
    pids = list(ctx.report.scope.program_ids)
    for i in range(0, len(pids), 2):
        cols = st.columns(2, gap="small")
        for col, pid in zip(cols, pids[i:i + 2]):
            with col:
                st.plotly_chart(_program_chart(ctx, pid, ymax), config={"displayModeBar": False},
                                width="stretch", key=f"chart_{pid}")


def overview(ctx: Ctx) -> None:
    r = ctx.report
    ui.heading("Overview", "Budget versus actual spend for the selected programs and months.")
    if r.bva.empty:
        _empty_state("No budget or spend matches the current filters.")
        return
    t = r.totals
    util = "N/A" if t["utilization"] is None else f"{t['utilization']:.1%}"
    high = int((r.exceptions["status"].ne("Resolved") & r.exceptions["severity"].eq("High")).sum())

    cols = st.container(key="kpis").columns(4)
    with cols[0]:
        _kpi("card_budget", "Budget", fmt_cad_whole(t["budget_cents"]),
             "Sum of approved monthly program budgets in scope.", f"{len(r.bva)} program-months")
    with cols[1]:
        _kpi("card_actual", "Actual spend", fmt_cad_whole(t["actual_cents"]),
             "Sum of recorded expenses in scope, including expenses flagged in Reconciliation.",
             f"{util} of budget used")
    with cols[2]:
        over = t["remaining_cents"] < 0
        _kpi("card_remaining", "Remaining budget", fmt_cad_whole(t["remaining_cents"]),
             "Budget minus actual. A negative value means spend exceeds budget.",
             f"Over budget by {fmt_cad_whole(-t['remaining_cents'])}" if over else "Unspent budget in scope")
    with cols[3]:
        _kpi("card_exceptions", "Open exceptions", str(r.open_exceptions),
             "Reconciliation exceptions with status Open or Under review.",
             f"{high} high severity")

    left, right = st.columns([2, 1], gap="medium")
    with left, st.container(border=True, key="card_chart"):
        ui.heading("Monthly budget vs actual",
                   "Bars: actual spend (CAD). Dashed line: monthly budget. Red labels mark overspend months with variance %, N/A where the budget is zero. Panels share one scale.")
        _bva_charts(ctx)
    with right, st.container(border=True, key="card_findings"):
        ui.heading("Findings", "Calculated from the filtered data.")
        items = "".join(f"<li>{html.escape(f)}</li>" for f in r.findings)
        st.html(f'<ul class="pft-findings">{items}</ul>')

    with st.container(border=True, key="card_variance"):
        ui.heading("Program variance",
                   "Variance = actual - budget; positive means overspend. Variance % is N/A where budget is zero.")
        df = r.programs.copy()
        df["status"] = ["No budget" if b == 0 else ("Over budget" if v > 0 else "Within budget")
                        for b, v in zip(df["budget_cents"], df["variance_cents"])]
        df["variance_pct_text"] = df["variance_pct"].map(fmt_pct)
        df = ui.cents_to_dollars(df, ["budget_cents", "actual_cents", "variance_cents", "remaining_cents"])
        df = df[["program", "budget_cents", "actual_cents", "variance_cents", "variance_pct_text",
                 "remaining_cents", "txn_count", "status"]]
        st.dataframe(
            ui.style_badges(df, ["status"]), hide_index=True, width="stretch",
            column_config={
                "program": st.column_config.TextColumn("Program", pinned=True),
                "budget_cents": ui.money("Budget (CAD)"),
                "actual_cents": ui.money("Actual (CAD)"),
                "variance_cents": ui.money("Variance (CAD)", "Actual minus budget. Positive = overspend."),
                "variance_pct_text": ui.right_text("Variance %", "Variance / budget. N/A when budget is zero."),
                "remaining_cents": ui.money("Remaining (CAD)", "Budget minus actual."),
                "txn_count": st.column_config.NumberColumn("Expenses", alignment="right"),
                "status": st.column_config.TextColumn("Status"),
            },
        )
        with st.expander("Program-month detail"):
            d = r.bva.copy()
            d["month"] = d["month"].map(month_name)
            d["variance_pct_text"] = d["variance_pct"].map(fmt_pct)
            d = ui.cents_to_dollars(d, ["budget_cents", "actual_cents", "variance_cents", "remaining_cents"])
            st.dataframe(
                d[["program", "month", "budget_cents", "actual_cents", "variance_cents", "variance_pct_text",
                   "remaining_cents", "txn_count"]],
                hide_index=True, width="stretch",
                column_config={
                    "program": "Program", "month": "Month",
                    "budget_cents": ui.money("Budget (CAD)"), "actual_cents": ui.money("Actual (CAD)"),
                    "variance_cents": ui.money("Variance (CAD)"),
                    "variance_pct_text": ui.right_text("Variance %"),
                    "remaining_cents": ui.money("Remaining (CAD)"),
                    "txn_count": st.column_config.NumberColumn("Expenses", alignment="right"),
                },
            )


# --------------------------------------------------------------------------- Reconciliation

def _supporting_records(ctx: Ctx, exc: pd.Series) -> None:
    match = recon.match_table(ctx.frames)
    txn_ids = [t for t in exc["related_txns"].split(", ") if t]
    txns = match[match["txn_id"].isin(txn_ids)].copy()

    st.markdown("**Expenses**")
    t = ui.cents_to_dollars(txns, ["amount_cents", "receipt_total_cents", "difference_cents"])
    t["po_id"] = t["po_id"].fillna("No PO referenced")
    t["vendor"] = t["vendor_name"] + " (" + t["vendor_id"] + ")"
    st.dataframe(
        t[["txn_id", "txn_date", "vendor", "po_id", "amount_cents", "receipt_count",
           "receipt_total_cents", "difference_cents", "support_status"]],
        hide_index=True, width="stretch",
        column_config={
            "txn_id": "Expense ID", "txn_date": "Date", "vendor": "Vendor",
            "po_id": "PO", "amount_cents": ui.money("Recorded (CAD)"),
            "receipt_count": st.column_config.NumberColumn("Receipts", alignment="right"),
            "receipt_total_cents": ui.money("Receipts total (CAD)", "Sum of all receipts matched to the expense."),
            "difference_cents": ui.money("Recorded - receipts (CAD)", "Positive: part of the expense has no receipt. Negative: receipts exceed the recorded amount."),
            "support_status": "Support status",
        },
    )

    rec = ctx.frames["receipts"]
    if exc["rule"] == "DUPLICATE_RECEIPT":
        rec = rec[rec["receipt_id"] == exc["record_id"]]
    else:
        rec = rec[rec["txn_id"].isin(txn_ids)]
    st.markdown("**Receipts**")
    if rec.empty:
        st.caption("No receipts are attached to these expenses.")
    else:
        rec = ui.cents_to_dollars(rec, ["amount_cents"])
        st.dataframe(
            rec[["receipt_id", "txn_id", "receipt_date", "receipt_type", "amount_cents", "file_ref"]],
            hide_index=True, width="stretch",
            column_config={"receipt_id": "Receipt ID", "txn_id": "Expense ID", "receipt_date": "Date",
                           "receipt_type": st.column_config.TextColumn("Type", help="partial = instalment or deposit invoice"),
                           "amount_cents": ui.money("Amount (CAD)"), "file_ref": "File reference"},
        )

    po_ids = set(txns["po_id"].dropna())
    if exc["record_type"] == "Purchase order":
        po_ids.add(exc["record_id"])
    if po_ids:
        pos = ctx.frames["purchase_orders"][ctx.frames["purchase_orders"]["po_id"].isin(po_ids)].copy()
        spend = match.groupby("po_id")["amount_cents"].sum()
        pos["spent_cents"] = pos["po_id"].map(spend).fillna(0)
        pos["po_remaining_cents"] = pos["amount_cents"] - pos["spent_cents"]
        pos = ui.cents_to_dollars(pos, ["amount_cents", "spent_cents", "po_remaining_cents"])
        st.markdown("**Purchase orders**")
        st.dataframe(
            pos[["po_id", "vendor_id", "issue_date", "description", "amount_cents", "spent_cents", "po_remaining_cents"]],
            hide_index=True, width="stretch",
            column_config={"po_id": "PO", "vendor_id": "Vendor ID", "issue_date": "Issued",
                           "description": "Description", "amount_cents": ui.money("Approved (CAD)"),
                           "spent_cents": ui.money("Spent to date (CAD)"),
                           "po_remaining_cents": ui.money("PO remaining (CAD)", "Negative = spend exceeds the PO.")},
        )


def reconciliation(ctx: Ctx) -> None:
    _flash()
    r = ctx.report
    ui.heading("Reconciliation",
               "Expenses matched to purchase orders and receipts by ID. Exceptions are flagged for review and never auto-corrected.")
    match = recon.match_table(ctx.frames)
    scoped = match[match["program_id"].isin(r.scope.program_ids) & match["month"].isin(r.scope.months)]
    if scoped.empty:
        _empty_state("No expenses match the current filters.")
        return
    exc = r.exceptions
    open_exc = exc[exc["status"] != "Resolved"]
    matched = int((scoped["support_status"] == "Matched").sum())

    cols = st.container(key="kpis").columns(4)
    with cols[0]:
        _kpi("card_matched", "Fully supported", f"{matched} of {len(scoped)}",
             "Expenses whose summed receipts equal the recorded amount.", "expenses in scope")
    for col, (cat, key, cap) in zip(cols[1:], [
        (recon.FINANCIAL, "card_fin", "Amounts disagree or a receipt is reused"),
        (recon.CONTROL, "card_ctl", "Unapproved vendor or spend above PO"),
        (recon.SUPPORT, "card_sup", "Receipt absent or partial; not a proven error"),
    ]):
        with col:
            _kpi(key, cat, str(int((open_exc["category"] == cat).sum())),
                 f"Open {cat.lower()} exceptions in scope.", cap)

    with st.container(border=True, key="card_exc_table"):
        ui.heading("Exceptions", "Select a row to see the supporting records and record a review.")
        if exc.empty:
            st.success("No reconciliation exceptions for the current filters.", icon=":material/task_alt:")
            return
        view = exc.copy()
        view["program"] = view["program_id"].map(ctx.names)
        view["month"] = view["month"].map(month_name)
        view = ui.cents_to_dollars(view, ["difference_cents"])
        view = view[["severity", "rule_label", "category", "record_id", "program", "month",
                     "difference_cents", "status"]]
        event = st.dataframe(
            ui.style_badges(view, ["severity", "status"]), hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row", key="exc_table", placeholder="N/A",
            column_config={
                "severity": st.column_config.TextColumn("Severity", help="High: possible financial error or control breach. Medium: missing support."),
                "rule_label": "Rule", "category": "Category", "record_id": "Record",
                "program": "Program", "month": "Month",
                "difference_cents": ui.money("Difference (CAD)", "Recorded minus supported or approved amount."),
                "status": "Status",
            },
        )
        with st.expander("Rule definitions"):
            for code, (label, cat, sev) in recon.RULES.items():
                st.markdown(f"**{label}** ({sev}, {cat.lower()}): {recon.RULE_HELP[code]}")

    rows = event.selection.rows if event and event.selection else []
    sel = exc.iloc[rows[0] if rows else 0]
    with st.container(border=True, key="card_exc_detail"):
        ui.heading(f"{sel['rule_label']}: {sel['record_id']}",
                   "Showing the first exception. Select a row above to change." if not rows else None)
        ui.kv_list([
            ("Severity", ui.badge(sel["severity"])),
            ("Category", ui.badge(sel["category"])),
            ("Status", ui.badge(sel["status"])),
            ("Program", ctx.names.get(sel["program_id"], sel["program_id"])),
            ("Month", month_name(sel["month"])),
            ("Recorded", fmt_cad(sel["recorded_cents"])),
            ("Supported / approved", "Not applicable" if pd.isna(sel["supported_cents"]) else fmt_cad(sel["supported_cents"])),
            ("Explanation", sel["explanation"]),
        ])
        _supporting_records(ctx, sel)

        st.markdown("**Review**")
        with st.form(f"review_{sel['exception_id']}", border=False):
            c1, c2 = st.columns([1, 2])
            status = c1.selectbox("Review status", recon.STATUSES, index=recon.STATUSES.index(sel["status"]),
                                  help="Recording a status does not change the underlying financial data.")
            note = c2.text_input("Review note", value=sel["note"], max_chars=300,
                                 placeholder="e.g. Requested balance receipt from vendor")
            if st.form_submit_button("Save review", type="primary"):
                n = ctl.update_exception(ctx.conn, sel["exception_id"], status, note)
                st.session_state["flash"] = f"Saved review for {sel['record_id']}." if n else "No changes to save."
                st.rerun()
        hist = ctl.history(ctx.conn, "exception", sel["exception_id"])
        if not hist.empty:
            st.markdown("**Review history**")
            _history_table(hist)


def _history_table(hist: pd.DataFrame) -> None:
    st.dataframe(
        hist[["changed_at", "entity_id", "field", "old_value", "new_value", "changed_by"]],
        hide_index=True, width="stretch",
        column_config={"changed_at": "Changed (UTC)", "entity_id": "Record", "field": "Field",
                       "old_value": "From", "new_value": "To", "changed_by": "By"},
    )


# --------------------------------------------------------------------------- Controls

def controls(ctx: Ctx) -> None:
    _flash()
    r = ctx.report
    ui.heading("Controls & Actions",
               "Control evidence checklist for organization-wide controls and selected programs, by due month.")
    st.warning("Demo workflow only. This checklist records statuses and notes in a local SQLite file; "
               "it is not a certified internal-control system and stores no real evidence files.",
               icon=":material/info:")
    df = r.controls.copy()
    if df.empty:
        _empty_state("No controls are due in the selected months.")
        return
    df["due_state"] = ["Done" if s == "Complete" else ("Overdue" if d < REPORT_AS_OF else "Due")
                       for s, d in zip(df["status"], df["due_date"])]

    cols = st.container(key="kpis").columns(4)
    counts = df["status"].value_counts()
    for col, (label, key, value, help) in zip(cols, [
        ("Complete", "card_c1", int(counts.get("Complete", 0)), "Controls marked Complete."),
        ("In progress", "card_c2", int(counts.get("In progress", 0)), "Controls marked In progress."),
        ("Needs follow-up", "card_c3", int(counts.get("Needs follow-up", 0)), "Controls where an issue was found."),
        ("Overdue", "card_c4", int((df["due_state"] == "Overdue").sum()),
         f"Not complete and due before the reporting date {REPORT_AS_OF}."),
    ]):
        with col:
            _kpi(key, label, str(value), help, f"of {len(df)} controls in scope")

    with st.container(border=True, key="card_ctl_table"):
        ui.heading("Checklist")
        st.dataframe(
            ui.style_badges(df[["control_id", "name", "scope", "evidence_ref", "owner", "due_date",
                                "due_state", "status", "notes"]], ["status", "due_state"]),
            hide_index=True, width="stretch",
            column_config={
                "control_id": st.column_config.TextColumn("ID", pinned=True), "name": "Control",
                "scope": "Scope", "evidence_ref": st.column_config.TextColumn("Evidence reference", help="Fictional document identifier"),
                "owner": "Owner", "due_date": "Due date",
                "due_state": st.column_config.TextColumn("Due", help=f"Overdue = not complete and due before {REPORT_AS_OF}"),
                "status": "Status", "notes": "Notes",
            },
        )

    with st.container(border=True, key="card_ctl_update"):
        ui.heading("Update a control", "Changes are saved to SQLite with a timestamped history entry.")
        options = list(df["control_id"])
        cid = st.selectbox("Control", options, format_func=lambda c: f"{c}  {df.set_index('control_id').loc[c, 'name']}",
                           key="ctl_pick")
        row = df.set_index("control_id").loc[cid]
        st.caption(row["description"])
        with st.form(f"ctl_form_{cid}", border=False):
            c1, c2 = st.columns([1, 2])
            status = c1.selectbox("Status", ctl.CONTROL_STATUSES, index=ctl.CONTROL_STATUSES.index(row["status"]))
            notes = c2.text_area("Notes", value=row["notes"], max_chars=500, height=80)
            if st.form_submit_button("Save update", type="primary"):
                n = ctl.update_control(ctx.conn, cid, status, notes)
                st.session_state["flash"] = f"Saved {n} change(s) to {cid}." if n else "No changes to save."
                st.rerun()

    with st.container(border=True, key="card_ctl_hist"):
        ui.heading("Change history", "Most recent first. All times UTC.")
        hist = ctl.history(ctx.conn, "control")
        hist = hist[hist["entity_id"].isin(df["control_id"])]
        if hist.empty:
            st.caption("No changes recorded yet for controls in scope.")
        else:
            _history_table(hist)


# --------------------------------------------------------------------------- ESG

def esg(ctx: Ctx) -> None:
    r = ctx.report
    ui.heading("ESG Data",
               "Synthetic operational indicators with data-quality checks. Not audited impact data and not evidence of compliance with any reporting framework.")
    df = r.esg.copy()
    if df.empty:
        _empty_state("No ESG records match the current filters.")
        return
    flagged = df[df["flag_count"] > 0]
    cols = st.container(key="kpis").columns(4)
    for col, (label, key, value, help, cap) in zip(cols, [
        ("Records", "card_e1", len(df), "Indicator values in scope. Organization-wide rows are always included.", "in scope"),
        ("Flagged records", "card_e2", len(flagged), "Records with at least one data-quality flag.", "need follow-up"),
        ("Missing values", "card_e3", int(df["value"].isna().sum()), "Blank values are kept blank, never treated as zero.", "left blank, not zero"),
        ("Verified", "card_e4", int((df["verification_status"] == "Verified").sum()), "Internal review status only.", "internal review, not audit"),
    ]):
        with col:
            _kpi(key, label, str(value), help, cap)

    with st.container(border=True, key="card_esg_flags"):
        ui.heading("Data-quality flags", "Missing values, missing sources and units that differ from the indicator definition. Units are not converted.")
        if flagged.empty:
            st.success("No data-quality issues in scope.", icon=":material/task_alt:")
        else:
            f = flagged.copy()
            f["period"] = f["period"].map(month_name)
            f["value_text"] = f["value"].map(lambda v: "Missing" if pd.isna(v) else f"{v:,.1f}".rstrip("0").rstrip("."))
            st.dataframe(
                f[["name", "scope", "period", "value_text", "unit", "source", "issues"]],
                hide_index=True, width="stretch", placeholder="Missing",
                column_config={"name": "Indicator", "scope": "Scope", "period": "Period",
                               "value_text": ui.right_text("Value"), "unit": "Unit",
                               "source": "Source", "issues": "Flags"},
            )

    with st.container(border=True, key="card_esg_all"):
        ui.heading("All records")
        a = df.copy()
        a["period"] = a["period"].map(month_name)
        st.dataframe(
            ui.style_badges(a[["name", "scope", "period", "value", "unit", "source", "owner",
                               "verification_status", "issues"]], ["verification_status"]),
            hide_index=True, width="stretch", placeholder="Missing",
            column_config={"name": "Indicator", "scope": "Scope", "period": "Period",
                           "value": st.column_config.NumberColumn("Value", format="localized", alignment="right",
                                                                  help="Blank = missing value"),
                           "unit": "Unit", "source": "Source", "owner": "Owner",
                           "verification_status": "Verification", "issues": "Flags"},
        )

    with st.container(border=True, key="card_esg_defs"):
        ui.heading("Indicator definitions")
        st.dataframe(ctx.frames["esg_indicators"][["indicator_id", "name", "definition", "expected_unit", "owner"]],
                     hide_index=True, width="stretch",
                     column_config={"indicator_id": "ID", "name": "Indicator", "definition": "Definition",
                                    "expected_unit": "Unit", "owner": "Owner"})
