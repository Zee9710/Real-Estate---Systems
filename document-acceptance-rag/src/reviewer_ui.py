"""
Document Acceptance — Reviewer Console (Streamlit).

Run with:  streamlit run src/reviewer_ui.py

Design approach: native Streamlit theming (.streamlit/config.toml) plus native
bordered containers, st.metric and st.column_config. CSS injection is limited to
the few things Streamlit cannot express natively (RTL Arabic, inline badges).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

try:
    import altair as alt
    _HAS_ALT = True
except Exception:
    _HAS_ALT = False

try:
    import httpx
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

from src.db_client import DBClient

# ------------------------------------------------------------------
# Config + clients
# ------------------------------------------------------------------
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

db = DBClient(cfg["db"]["path"])
API_BASE = os.environ.get("API_BASE", "http://localhost:8000")

st.set_page_config(
    page_title="Document Acceptance Console",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Minimal CSS — only for what native theming can't express.
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1400px; }
      .badge {
        display: inline-block; padding: 3px 12px; border-radius: 6px;
        font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .badge-accept  { background: #dcfce7; color: #166534; }
      .badge-reject  { background: #fee2e2; color: #991b1b; }
      .badge-pending { background: #e0e7ff; color: #3730a3; }
      .panel-ar {
        direction: rtl; text-align: right; background: #f8fafc;
        border-right: 3px solid #1e3a8a; padding: 12px 16px;
        border-radius: 8px 0 0 8px; font-size: 1.02rem; line-height: 1.85;
        color: #1e293b;
      }
      .panel-en {
        background: #f8fafc; border-left: 3px solid #16a34a;
        padding: 12px 16px; border-radius: 0 8px 8px 0;
        font-size: 0.95rem; line-height: 1.6; color: #1e293b; margin-bottom: 10px;
      }
      .pill {
        font-family: ui-monospace, monospace; background: #f1f5f9;
        color: #475569; padding: 2px 8px; border-radius: 5px;
        font-size: 0.82rem; border: 1px solid #e2e8f0;
      }
      .caption-label {
        font-size: 0.7rem; font-weight: 600; letter-spacing: 0.08em;
        text-transform: uppercase; color: #94a3b8;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def api_get(path: str):
    if not _HAS_HTTPX:
        return None
    try:
        r = httpx.get(f"{API_BASE}{path}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def api_post(path: str):
    if not _HAS_HTTPX:
        return None, "httpx not installed"
    try:
        r = httpx.post(f"{API_BASE}{path}", timeout=600)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def badge(decision: str) -> str:
    d = (decision or "").lower()
    if d == "accepted":
        return '<span class="badge badge-accept">Accepted</span>'
    if d == "rejected":
        return '<span class="badge badge-reject">Rejected</span>'
    return '<span class="badge badge-pending">Pending</span>'


def load_incoming() -> pd.DataFrame:
    rows = db.read_incoming()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def load_historical() -> pd.DataFrame:
    rows = db.read_historical()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def alt_theme(chart):
    """Apply consistent transparent background + no view border."""
    return chart.configure_view(strokeWidth=0).configure(background="transparent")


ATTR_FIELDS = [
    "document_type", "owner_name", "owner_id", "property_id",
    "property_type", "area_sqm", "address", "city",
    "notarized", "owner_signature", "liens_present", "registration_date",
]

NAVY = "#1e3a8a"
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#f59e0b"
PALETTE = ["#1e3a8a", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"]


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<div style='padding:10px 0 4px 0;'>"
        "<div style='font-size:1.1rem;font-weight:700;color:#f8fafc;'>Document Acceptance</div>"
        "<div style='font-size:0.74rem;color:#64748b;'>Reviewer Console</div></div>",
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigation",
        ["Dashboard", "Review Queue", "Submit Case", "Case Explorer", "Historical"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("<span class='caption-label'>System Status</span>", unsafe_allow_html=True)

    health = api_get("/health")
    if health:
        st.markdown(
            "<span style='color:#22c55e;font-size:0.84rem;font-weight:600;'>● Online</span>",
            unsafe_allow_html=True,
        )
        st.metric("Indexed cases", health.get("chroma_count", "—"))
    else:
        st.markdown(
            "<span style='color:#ef4444;font-size:0.84rem;font-weight:600;'>● Offline</span>",
            unsafe_allow_html=True,
        )
        st.caption("Start: uvicorn src.main:app")

    calib = api_get("/calibration")
    if calib and "threshold" in calib:
        st.metric("Novelty threshold", f"{calib['threshold']:.4f}")

    st.divider()
    if st.button("Reindex & Recalibrate", use_container_width=True):
        with st.spinner("Rebuilding index…"):
            _, err = api_post("/reindex")
        st.error(f"Failed: {err}") if err else st.success("Reindex complete.")
    if st.button("Process Pending Now", use_container_width=True):
        with st.spinner("Processing…"):
            res, err = api_post("/process")
        st.error(f"Failed: {err}") if err else st.success(
            f"Processed {res.get('processed', 0) if res else 0} case(s)."
        )


# ==================================================================
# DASHBOARD
# ==================================================================
if page == "Dashboard":
    st.subheader("Dashboard")
    st.caption("Live summary of all incoming cases and processing status")

    df = load_incoming()
    if df.empty:
        st.info("No cases processed yet. Use Submit Case or run the seeder.")
    else:
        total = len(df)
        done = int((df["status"] == "done").sum()) if "status" in df else 0
        pending = int((df["status"] == "pending").sum()) if "status" in df else 0
        accepted = int((df["decision"] == "Accepted").sum()) if "decision" in df else 0
        awaiting = int(
            ((df["needs_review"] == 1) & (df["validated_by"].isna() | (df["validated_by"] == ""))).sum()
        ) if "needs_review" in df and "validated_by" in df else 0

        m = st.columns(5)
        m[0].metric("Total Cases", total)
        m[1].metric("Processed", done)
        m[2].metric("Pending", pending)
        m[3].metric("Accepted", accepted)
        m[4].metric("Awaiting Review", awaiting, delta=None)

        st.write("")
        col_a, col_b = st.columns(2)

        with col_a:
            with st.container(border=True):
                st.markdown("**Decision breakdown**")
                if "decision" in df and df["decision"].notna().any():
                    dc = df["decision"].fillna("Unprocessed").value_counts().reset_index()
                    dc.columns = ["decision", "count"]
                    if _HAS_ALT:
                        cmap = {"Accepted": GREEN, "Rejected": RED, "Unprocessed": "#cbd5e1"}
                        chart = alt.Chart(dc).mark_arc(innerRadius=55, outerRadius=90).encode(
                            theta="count:Q",
                            color=alt.Color("decision:N", scale=alt.Scale(
                                domain=list(cmap), range=list(cmap.values())),
                                legend=alt.Legend(orient="right")),
                            tooltip=["decision:N", "count:Q"],
                        ).properties(height=230)
                        st.altair_chart(alt_theme(chart), use_container_width=True)
                    else:
                        st.bar_chart(dc.set_index("decision"))
                else:
                    st.caption("No decisions yet.")

        with col_b:
            with st.container(border=True):
                st.markdown("**Rejection reasons**")
                rej = df[df["decision"] == "Rejected"] if "decision" in df else pd.DataFrame()
                if not rej.empty and "reason_code" in rej.columns:
                    rc = rej["reason_code"].value_counts().reset_index()
                    rc.columns = ["reason_code", "count"]
                    if _HAS_ALT:
                        chart = alt.Chart(rc).mark_bar(
                            cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color=RED).encode(
                            x=alt.X("count:Q", title="Cases"),
                            y=alt.Y("reason_code:N", sort="-x", title=None),
                            tooltip=["reason_code:N", "count:Q"],
                        ).properties(height=230)
                        st.altair_chart(alt_theme(chart), use_container_width=True)
                    else:
                        st.bar_chart(rc.set_index("reason_code"))
                else:
                    st.caption("No rejections yet.")

        st.write("")
        with st.container(border=True):
            st.markdown("**Novelty distance distribution**")
            if "nn_distance" in df and df["nn_distance"].notna().any():
                nd = df[["nn_distance"]].dropna()
                thr = calib.get("threshold") if calib else None
                if _HAS_ALT:
                    base = alt.Chart(nd).mark_bar(color=NAVY, opacity=0.8).encode(
                        x=alt.X("nn_distance:Q", bin=alt.Bin(maxbins=30), title="Nearest-neighbour distance"),
                        y=alt.Y("count()", title="Cases"),
                    )
                    layers = base
                    if thr:
                        rule = alt.Chart(pd.DataFrame({"t": [thr]})).mark_rule(
                            color=AMBER, strokeDash=[5, 4], size=2).encode(x="t:Q")
                        layers = base + rule
                    st.altair_chart(alt_theme(layers.properties(height=190)), use_container_width=True)
                    if thr:
                        st.caption(f"Amber line marks the novelty threshold ({thr:.4f}); cases to the right are flagged.")
                else:
                    st.bar_chart(nd)
            else:
                st.caption("No novelty scores yet.")


# ==================================================================
# REVIEW QUEUE
# ==================================================================
elif page == "Review Queue":
    st.subheader("Review Queue")
    st.caption("Cases flagged for human validation by the rule engine or novelty detector")

    df = load_incoming()
    rows = df.to_dict("records") if not df.empty else []
    flagged = [r for r in rows if r.get("needs_review") == 1 and not r.get("validated_by")]

    if not flagged:
        st.success("No cases pending review.")
    else:
        st.caption(f"{len(flagged)} case(s) awaiting validation")
        for case in flagged:
            with st.container(border=True):
                head = st.columns([3, 1])
                head[0].markdown(f"**{case['case_id']}**")
                head[1].markdown(badge(case.get("decision", "")), unsafe_allow_html=True)

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("<span class='caption-label'>Case attributes</span>", unsafe_allow_html=True)
                    attrs = {f: case.get(f) for f in ATTR_FIELDS if case.get(f) not in (None, "")}
                    st.dataframe(
                        pd.DataFrame(list(attrs.items()), columns=["Field", "Value"]),
                        hide_index=True, use_container_width=True,
                    )
                with col2:
                    st.markdown("<span class='caption-label'>Decision context</span>", unsafe_allow_html=True)
                    st.markdown(
                        f"Reason &nbsp;<span class='pill'>{case.get('reason_code','')}</span> "
                        f"&nbsp; Flag &nbsp;<span class='pill'>{case.get('flag_reason','')}</span>",
                        unsafe_allow_html=True,
                    )
                    nn = case.get("nn_distance")
                    if nn is not None:
                        st.markdown(f"Distance &nbsp;<span class='pill'>{float(nn):.4f}</span>", unsafe_allow_html=True)
                    retrieved = case.get("retrieved_case_ids", "")
                    if retrieved:
                        st.markdown(f"Nearest &nbsp;<span class='pill'>{retrieved}</span>", unsafe_allow_html=True)
                    st.write("")
                    st.markdown(f"<div class='panel-en'>{case.get('recommendation_en','—')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='panel-ar'>{case.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)

                rev_col, btn_col = st.columns([2, 1])
                reviewer_id = rev_col.text_input(
                    "Reviewer ID", key=f"rev_{case['case_id']}", placeholder="e.g. EMP-042",
                    label_visibility="collapsed",
                )
                if btn_col.button("Validate", key=f"val_{case['case_id']}", use_container_width=True):
                    if not reviewer_id.strip():
                        st.error("Enter your reviewer ID first.")
                    else:
                        db.write_recommendation(case["case_id"], {"validated_by": reviewer_id.strip()})
                        st.success(f"Validated by {reviewer_id}.")
                        st.rerun()


# ==================================================================
# SUBMIT CASE
# ==================================================================
elif page == "Submit Case":
    st.subheader("Submit Case")
    st.caption("Insert a new case into the processing queue")

    with st.form("new_case"):
        c1, c2, c3 = st.columns(3)
        with c1:
            case_id = st.text_input("Case ID *", placeholder="CASE-1001")
            document_type = st.text_input("Document type", value="عقد بيع")
            owner_name = st.text_input("Owner name")
            owner_id = st.text_input("Owner national ID (10 digits)")
        with c2:
            property_id = st.text_input("Property ID")
            property_type = st.text_input("Property type", value="apartment")
            area_sqm = st.number_input("Area (sqm)", min_value=0.0, value=100.0, step=10.0)
            registration_date = st.date_input("Registration date", value=date(2022, 1, 1))
        with c3:
            address = st.text_input("Address")
            city = st.text_input("City", value="Riyadh")
            notarized = st.checkbox("Notarized", value=True)
            owner_signature = st.checkbox("Owner signature present", value=True)
            liens_present = st.checkbox("Liens present", value=False)

        process_now = st.checkbox("Process immediately after insert", value=True)
        submitted = st.form_submit_button("Submit Case", use_container_width=True)

    if submitted:
        if not case_id.strip():
            st.error("Case ID is required.")
        else:
            row = {
                "case_id": case_id.strip(),
                "document_type": document_type,
                "owner_name": owner_name,
                "owner_id": owner_id,
                "property_id": property_id,
                "property_type": property_type,
                "area_sqm": float(area_sqm),
                "address": address,
                "city": city,
                "notarized": 1 if notarized else 0,
                "owner_signature": 1 if owner_signature else 0,
                "liens_present": 1 if liens_present else 0,
                "registration_date": registration_date.isoformat(),
                "status": "pending",
            }
            db.upsert_incoming(row)
            st.success(f"Case {case_id} inserted.")
            if process_now:
                with st.spinner("Running rule engine, novelty detection and explanation…"):
                    res, err = api_post(f"/process?case_id={case_id.strip()}")
                if err:
                    st.warning(f"Inserted, but processing failed: {err}")
                elif res and res.get("results"):
                    out = res["results"][0]
                    with st.container(border=True):
                        st.markdown(badge(out.get("decision", "")), unsafe_allow_html=True)
                        st.markdown(f"<br>Reason &nbsp;<span class='pill'>{out.get('reason_code','')}</span>", unsafe_allow_html=True)
                        st.markdown(f"<div class='panel-en'>{out.get('recommendation_en','—')}</div>", unsafe_allow_html=True)
                        st.markdown(f"<div class='panel-ar'>{out.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)
                        if out.get("needs_review"):
                            st.info("Case flagged and added to the Review Queue.")
                else:
                    st.info("Case processed. Check the Case Explorer.")


# ==================================================================
# CASE EXPLORER
# ==================================================================
elif page == "Case Explorer":
    st.subheader("Case Explorer")
    st.caption("Search, filter and export incoming cases")

    df = load_incoming()
    if df.empty:
        st.info("No incoming cases yet.")
    else:
        f1, f2, f3 = st.columns(3)
        statuses = df["status"].dropna().unique().tolist() if "status" in df else []
        decisions = df["decision"].dropna().unique().tolist() if "decision" in df else []
        status_filter = f1.multiselect("Status", statuses, default=statuses)
        decision_filter = f2.multiselect("Decision", decisions, default=decisions)
        search = f3.text_input("Search case ID or owner name")

        view = df.copy()
        if status_filter and "status" in view:
            view = view[view["status"].isin(status_filter)]
        if decision_filter and "decision" in view:
            view = view[view["decision"].isin(decision_filter)]
        if st.checkbox("Show flagged cases only") and "needs_review" in view:
            view = view[view["needs_review"] == 1]
        if search:
            mask = pd.Series(False, index=view.index)
            for col in ("case_id", "owner_name"):
                if col in view:
                    mask = mask | view[col].astype(str).str.contains(search, case=False, na=False)
            view = view[mask]

        st.caption(f"{len(view)} case(s) shown")
        display_cols = [
            "case_id", "status", "decision", "reason_code", "flag_reason",
            "needs_review", "validated_by", "nn_distance", "processed_at",
        ]
        present = [c for c in display_cols if c in view.columns]
        st.dataframe(
            view[present],
            use_container_width=True,
            hide_index=True,
            column_config={
                "case_id": st.column_config.TextColumn("Case ID"),
                "decision": st.column_config.TextColumn("Decision"),
                "reason_code": st.column_config.TextColumn("Reason"),
                "needs_review": st.column_config.CheckboxColumn("Flagged"),
                "nn_distance": st.column_config.NumberColumn("NN dist.", format="%.4f"),
                "processed_at": st.column_config.DatetimeColumn("Processed"),
            },
        )
        st.download_button(
            "Export as CSV",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"incoming_cases_{datetime.now():%Y%m%d}.csv",
            mime="text/csv",
        )


# ==================================================================
# HISTORICAL
# ==================================================================
elif page == "Historical":
    st.subheader("Historical Knowledge Base")
    st.caption("Validated cases used for embedding retrieval and novelty calibration")

    df = load_historical()
    if df.empty:
        st.info("No historical cases yet. Run scripts/seed_db.py.")
    else:
        m = st.columns(3)
        m[0].metric("Total Cases", len(df))
        if "decision" in df:
            m[1].metric("Accepted", int((df["decision"] == "Accepted").sum()))
            m[2].metric("Rejected", int((df["decision"] == "Rejected").sum()))

        st.write("")
        col_a, col_b = st.columns(2)
        with col_a:
            with st.container(border=True):
                st.markdown("**Cases by city**")
                if "city" in df and df["city"].notna().any():
                    cc = df["city"].value_counts().head(12).reset_index()
                    cc.columns = ["city", "count"]
                    if _HAS_ALT:
                        chart = alt.Chart(cc).mark_bar(
                            cornerRadiusTopRight=3, cornerRadiusBottomRight=3, color=NAVY).encode(
                            x=alt.X("count:Q", title="Cases"),
                            y=alt.Y("city:N", sort="-x", title=None),
                            tooltip=["city:N", "count:Q"],
                        ).properties(height=270)
                        st.altair_chart(alt_theme(chart), use_container_width=True)
                    else:
                        st.bar_chart(cc.set_index("city"))
        with col_b:
            with st.container(border=True):
                st.markdown("**Cases by property type**")
                if "property_type" in df and df["property_type"].notna().any():
                    pc = df["property_type"].value_counts().reset_index()
                    pc.columns = ["property_type", "count"]
                    if _HAS_ALT:
                        chart = alt.Chart(pc).mark_arc(innerRadius=55, outerRadius=90).encode(
                            theta="count:Q",
                            color=alt.Color("property_type:N", scale=alt.Scale(range=PALETTE),
                                            legend=alt.Legend(orient="right")),
                            tooltip=["property_type:N", "count:Q"],
                        ).properties(height=270)
                        st.altair_chart(alt_theme(chart), use_container_width=True)
                    else:
                        st.bar_chart(pc.set_index("property_type"))

        st.write("")
        if "decision" in df:
            decisions = df["decision"].dropna().unique().tolist()
            dfilter = st.multiselect("Filter by decision", decisions, default=decisions)
            view = df[df["decision"].isin(dfilter)] if dfilter else df
        else:
            view = df
        st.dataframe(view, use_container_width=True, hide_index=True)
