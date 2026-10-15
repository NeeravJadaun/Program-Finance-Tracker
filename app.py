"""Program Finance Tracker - Streamlit entry point.

Run:  streamlit run app.py
The database is created and seeded with synthetic data on first run.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from pft import db, pages, ui
from pft.data import Scope, all_months, load_frames, month_name
from pft.export import workbook_bytes
from pft.report import build_report
from pft.seed import ensure_database

st.set_page_config(page_title="Program Finance Tracker", page_icon=":material/account_balance:",
                   layout="wide", initial_sidebar_state="auto")
ui.inject_css()

ensure_database()
conn = db.connect()
frames = load_frames(conn)
programs = frames["programs"]
names = dict(zip(programs["program_id"], programs["name"]))
colors = dict(zip(programs["program_id"], programs["color"]))
months = all_months(frames)


# ---------------------------------------------------------------- filters
st.session_state["filter_defaults"] = (list(programs["program_id"]), (months[0], months[-1]))


nav = st.navigation([
    st.Page(lambda: pages.overview(ctx), title="Overview", icon=":material/space_dashboard:",
            url_path="overview", default=True),
    st.Page(lambda: pages.reconciliation(ctx), title="Reconciliation", icon=":material/rule:",
            url_path="reconciliation"),
    st.Page(lambda: pages.controls(ctx), title="Controls & Actions", icon=":material/fact_check:",
            url_path="controls"),
    st.Page(lambda: pages.esg(ctx), title="ESG Data", icon=":material/eco:", url_path="esg"),
])

with st.sidebar:
    st.markdown("**Filters**")
    # Defaults are passed as values (not pre-set in session state) so the slider stays in range mode.
    picked_programs = st.multiselect(
        "Programs", options=list(programs["program_id"]), default=list(programs["program_id"]),
        format_func=names.get, key="f_programs", placeholder="Select programs",
        help="Applies to every page and to the Excel download.")
    start, end = st.select_slider(
        "Months", options=months, value=(months[0], months[-1]), format_func=month_name, key="f_months",
        help="Inclusive month range. Applies to every page and to the Excel download.")
    st.button("Reset filters", on_click=ui.reset_filters, icon=":material/restart_alt:", width="stretch")
    st.caption("Synthetic data for demonstration. Fictional programs, vendors and amounts.")

selected = tuple(p for p in programs["program_id"] if p in picked_programs)
scope = Scope(selected, tuple(m for m in months if start <= m <= end))
report = build_report(frames, scope)
ctx = pages.Ctx(conn=conn, frames=frames, report=report, names=names, colors=colors)


# ---------------------------------------------------------------- header
head, action = st.columns([2, 1], vertical_alignment="center")
with head:
    st.html(
        '<div><p class="pft-title">Program Finance Tracker '
        f'{ui.badge("Synthetic demo", "teal")}</p>'
        f'<p class="pft-sub">Reporting period: <b>{report.months_label}</b> &nbsp;|&nbsp; '
        f'{report.programs_label}</p></div>'
    )
with action:
    st.download_button(
        "Download Excel", data=workbook_bytes(report, names) if scope.program_ids else b"",
        file_name=f"program-finance-{date.today().isoformat()}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        icon=":material/download:", type="primary", on_click="ignore", width="stretch",
        disabled=not scope.program_ids,
        help="Workbook for the current filters: Summary, Budget vs Actual, Reconciliation Exceptions, "
             "Control Evidence, ESG Data and Data Dictionary.",
    )

if not scope.program_ids:
    ui.empty_state("No programs selected.")
else:
    nav.run()
