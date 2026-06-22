"""
Document Acceptance — Reviewer Console (Streamlit).

Run with:  streamlit run src/reviewer_ui.py
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
    page_icon="assets/favicon.png" if os.path.exists("assets/favicon.png") else None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# Design system
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

      html, body, [class*="css"] {
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif;
      }

      .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1400px;
      }

      /* Metric cards */
      div[data-testid="stMetric"] {
        background: #0f1117;
        border: 1px solid #1e2433;
        border-radius: 10px;
        padding: 20px 22px;
      }
      div[data-testid="stMetric"] label p {
        color: #6b7694 !important;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      div[data-testid="stMetricValue"] {
        color: #e8eaf2;
        font-size: 1.9rem;
        font-weight: 700;
      }

      /* Status badges */
      .badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 4px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }
      .badge-accept { background: #052e16; color: #86efac; border: 1px solid #166534; }
      .badge-reject { background: #2d0a0a; color: #fca5a5; border: 1px solid #7f1d1d; }
      .badge-pending { background: #1a1a2e; color: #93c5fd; border: 1px solid #1e3a5f; }

      /* Explanation panels */
      .panel-en {
        background: #0b1a13;
        border-left: 3px solid #22c55e;
        padding: 12px 16px;
        border-radius: 0 8px 8px 0;
        margin-bottom: 10px;
        font-size: 0.95rem;
        line-height: 1.6;
        color: #d1fae5;
      }
      .panel-ar {
        direction: rtl;
        text-align: right;
        background: #0d1525;
        border-right: 3px solid #3b82f6;
        padding: 12px 16px;
        border-radius: 8px 0 0 8px;
        font-size: 1rem;
        line-height: 1.8;
        color: #bfdbfe;
      }

      /* Monospace pill */
      .pill {
        font-family: ui-monospace, 'Cascadia Code', monospace;
        background: #1a1d2e;
        color: #94a3b8;
        padding: 2px 9px;
        border-radius: 5px;
        font-size: 0.82rem;
        border: 1px solid #2a2d3e;
      }

      /* Section divider */
      .section-rule {
        border: none;
        border-top: 1px solid #1e2433;
        margin: 1.5rem 0;
      }

      /* Sidebar tweaks */
      section[data-testid="stSidebar"] {
        background: #090c14;
        border-right: 1px solid #1e2433;
      }
      section[data-testid="stSidebar"] .stRadio label {
        font-size: 0.88rem;
        color: #8a94b0;
      }

      /* Page title style */
      .page-title {
        font-size: 1.45rem;
        font-weight: 700;
        color: #e2e8f0;
        margin-bottom: 0.15rem;
        letter-spacing: -0.01em;
      }
      .page-sub {
        font-size: 0.82rem;
        color: #4b5675;
        margin-bottom: 1.6rem;
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


ATTR_FIELDS = [
    "document_type", "owner_name", "owner_id", "property_id",
    "property_type", "area_sqm", "address", "city",
    "notarized", "owner_signature", "liens_present", "registration_date",
]

CHART_COLORS = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"]


# ------------------------------------------------------------------
# Sidebar
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        "<div style='padding: 18px 0 6px 0;'>"
        "<span style='font-size:1.15rem;font-weight:700;color:#e2e8f0;letter-spacing:-0.01em;'>"
        "Document Acceptance</span><br>"
        "<span style='font-size:0.75rem;color:#4b5675;'>Reviewer Console</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["Dashboard", "Review Queue", "Submit Case", "Case Explorer", "Historical"],
        label_visibility="collapsed",
    )

    st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)
    st.markdown(
        "<span style='font-size:0.7rem;font-weight:600;letter-spacing:0.08em;"
        "text-transform:uppercase;color:#4b5675;'>System Status</span>",
        unsafe_allow_html=True,
    )

    health = api_get("/health")
    if health:
        st.markdown(
            "<span style='color:#22c55e;font-size:0.82rem;font-weight:600;'>● Backend online</span>",
            unsafe_allow_html=True,
        )
        st.metric("Indexed cases", health.get("chroma_count", "—"))
        st.caption(f"Version: {health.get('active_version', '—')}")
    else:
        st.markdown(
            "<span style='color:#ef4444;font-size:0.82rem;font-weight:600;'>● Backend offline</span>",
            unsafe_allow_html=True,
        )

    calib = api_get("/calibration")
    if calib and "threshold" in calib:
        st.metric("Novelty threshold", f"{calib['threshold']:.4f}")

    st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)

    if st.button("Reindex & Recalibrate", use_container_width=True):
        with st.spinner("Rebuilding index from historical cases…"):
            res, err = api_post("/reindex")
        if err:
            st.error(f"Failed: {err}")
        else:
            st.success("Reindex complete.")

    if st.button("Process Pending Now", use_container_width=True):
        with st.spinner("Processing pending cases…"):
            res, err = api_post("/process")
        if err:
            st.error(f"Failed: {err}")
        else:
            n = res.get("processed", 0) if res else 0
            st.success(f"Processed {n} case(s).")


# ==================================================================
# DASHBOARD
# ==================================================================
if page == "Dashboard":
    st.markdown("<div class='page-title'>Dashboard</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-sub'>Live summary of all incoming cases and processing status</div>", unsafe_allow_html=True)

    df = load_incoming()

    if df.empty:
        st.info("No cases processed yet. Insert a case using Submit Case or run the seeder.")
    else:
        total = len(df)
        done = int((df["status"] == "done").sum()) if "status" in df else 0
        pending = int((df["status"] == "pending").sum()) if "status" in df else 0
        accepted = int((df["decision"] == "Accepted").sum()) if "decision" in df else 0
        rejected = int((df["decision"] == "Rejected").sum()) if "decision" in df else 0
        awaiting = int(
            ((df["needs_review"] == 1) & (df["validated_by"].isna() | (df["validated_by"] == ""))).sum()
        ) if "needs_review" in df and "validated_by" in df else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Cases", total)
        c2.metric("Processed", done)
        c3.metric("Pending", pending)
        c4.metric("Accepted", accepted)
        c5.metric("Awaiting Review", awaiting)

        st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**Decision breakdown**")
            if "decision" in df and df["decision"].notna().any():
                dc = df["decision"].fillna("Unprocessed").value_counts().reset_index()
                dc.columns = ["decision", "count"]
                if _HAS_ALT:
                    color_map = {"Accepted": "#22c55e", "Rejected": "#ef4444", "Unprocessed": "#374151"}
                    chart = (
                        alt.Chart(dc)
                        .mark_arc(innerRadius=55, outerRadius=90)
                        .encode(
                            theta=alt.Theta("count:Q"),
                            color=alt.Color(
                                "decision:N",
                                scale=alt.Scale(
                                    domain=list(color_map.keys()),
                                    range=list(color_map.values()),
                                ),
                                legend=alt.Legend(orient="right"),
                            ),
                            tooltip=["decision:N", "count:Q"],
                        )
                        .properties(height=220)
                        .configure_view(strokeWidth=0)
                        .configure(background="transparent")
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.bar_chart(dc.set_index("decision"))

        with col_b:
            st.markdown("**Rejection reasons**")
            rej = df[df["decision"] == "Rejected"] if "decision" in df else pd.DataFrame()
            if not rej.empty and "reason_code" in rej.columns:
                rc = rej["reason_code"].value_counts().reset_index()
                rc.columns = ["reason_code", "count"]
                if _HAS_ALT:
                    chart = (
                        alt.Chart(rc)
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
                        .encode(
                            x=alt.X("count:Q", title="Cases"),
                            y=alt.Y("reason_code:N", sort="-x", title=None),
                            color=alt.value("#ef4444"),
                            tooltip=["reason_code:N", "count:Q"],
                        )
                        .properties(height=220)
                        .configure_view(strokeWidth=0)
                        .configure(background="transparent")
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.bar_chart(rc.set_index("reason_code"))
            else:
                st.caption("No rejection data yet.")

        st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)
        st.markdown("**Novelty distance distribution**")
        if "nn_distance" in df and df["nn_distance"].notna().any():
            nd = df[["nn_distance"]].dropna()
            thr = calib.get("threshold") if calib else None
            if _HAS_ALT:
                base = (
                    alt.Chart(nd)
                    .mark_bar(color="#3b82f6", opacity=0.75)
                    .encode(
                        x=alt.X("nn_distance:Q", bin=alt.Bin(maxbins=30), title="Nearest-neighbour distance"),
                        y=alt.Y("count()", title="Cases"),
                        tooltip=["count()"],
                    )
                )
                layers = base
                if thr:
                    rule = (
                        alt.Chart(pd.DataFrame({"t": [thr]}))
                        .mark_rule(color="#f59e0b", strokeDash=[5, 4], size=2)
                        .encode(x="t:Q")
                    )
                    layers = base + rule
                st.altair_chart(
                    layers.properties(height=180)
                    .configure_view(strokeWidth=0)
                    .configure(background="transparent"),
                    use_container_width=True,
                )
                if thr:
                    st.caption(f"Amber line = novelty threshold ({thr:.4f}). Cases right of the line are flagged as novel.")
            else:
                st.bar_chart(nd)
        else:
            st.caption("No novelty scores recorded yet.")


# ==================================================================
# REVIEW QUEUE
# ==================================================================
elif page == "Review Queue":
    st.markdown("<div class='page-title'>Review Queue</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-sub'>Cases flagged by the novelty detector or rule engine that require human validation</div>", unsafe_allow_html=True)

    df = load_incoming()
    rows = df.to_dict("records") if not df.empty else []
    flagged = [r for r in rows if r.get("needs_review") == 1 and not r.get("validated_by")]

    if not flagged:
        st.success("No cases pending review.")
    else:
        st.caption(f"{len(flagged)} case(s) awaiting validation")

        for case in flagged:
            label = f"{case['case_id']}  —  {case.get('decision', '')}  ·  {case.get('reason_code', '')}  ·  {case.get('flag_reason', '')}"
            with st.expander(label, expanded=False):
                st.markdown(badge(case.get("decision", "")), unsafe_allow_html=True)
                st.markdown("<br>", unsafe_allow_html=True)

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("**Case attributes**")
                    attrs = {f: case.get(f) for f in ATTR_FIELDS if case.get(f) not in (None, "")}
                    st.table(pd.DataFrame(list(attrs.items()), columns=["Field", "Value"]))

                with col2:
                    st.markdown("**Decision context**")
                    st.markdown(
                        f"Reason code &nbsp; <span class='pill'>{case.get('reason_code', '')}</span><br>"
                        f"Flag reason &nbsp;&nbsp; <span class='pill'>{case.get('flag_reason', '')}</span>",
                        unsafe_allow_html=True,
                    )
                    nn = case.get("nn_distance")
                    if nn is not None:
                        st.markdown(f"NN distance &nbsp;&nbsp; <span class='pill'>{float(nn):.4f}</span>", unsafe_allow_html=True)
                    retrieved = case.get("retrieved_case_ids", "")
                    if retrieved:
                        st.markdown(f"Nearest cases &nbsp; <span class='pill'>{retrieved}</span>", unsafe_allow_html=True)

                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("**Explanation**")
                    st.markdown(f"<div class='panel-en'>{case.get('recommendation_en', '—')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='panel-ar'>{case.get('recommendation_ar', '—')}</div>", unsafe_allow_html=True)

                st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)
                reviewer_id = st.text_input(
                    "Reviewer ID", key=f"rev_{case['case_id']}", placeholder="e.g. EMP-042"
                )
                b1, b2, _ = st.columns([1, 1, 4])
                with b1:
                    if st.button("Validate", key=f"val_{case['case_id']}", use_container_width=True):
                        if not reviewer_id.strip():
                            st.error("Enter your reviewer ID first.")
                        else:
                            db.write_recommendation(case["case_id"], {"validated_by": reviewer_id.strip()})
                            st.success(f"Validated by {reviewer_id}. Will be promoted to historical on next poll.")
                            st.rerun()


# ==================================================================
# SUBMIT CASE
# ==================================================================
elif page == "Submit Case":
    st.markdown("<div class='page-title'>Submit Case</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-sub'>Insert a new case into the processing queue</div>", unsafe_allow_html=True)

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
                    st.markdown(badge(out.get("decision", "")), unsafe_allow_html=True)
                    st.markdown(f"<br>Reason code &nbsp; <span class='pill'>{out.get('reason_code','')}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div class='panel-en'>{out.get('recommendation_en', '—')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='panel-ar'>{out.get('recommendation_ar', '—')}</div>", unsafe_allow_html=True)
                    if out.get("needs_review"):
                        st.info("Case has been flagged and added to the Review Queue.")
                else:
                    st.info("Case processed. Check the Case Explorer for results.")


# ==================================================================
# CASE EXPLORER
# ==================================================================
elif page == "Case Explorer":
    st.markdown("<div class='page-title'>Case Explorer</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-sub'>Search, filter and export incoming cases</div>", unsafe_allow_html=True)

    df = load_incoming()
    if df.empty:
        st.info("No incoming cases yet.")
    else:
        f1, f2, f3 = st.columns(3)
        with f1:
            statuses = df["status"].dropna().unique().tolist() if "status" in df else []
            status_filter = st.multiselect("Status", statuses, default=statuses)
        with f2:
            decisions = df["decision"].dropna().unique().tolist() if "decision" in df else []
            decision_filter = st.multiselect("Decision", decisions, default=decisions)
        with f3:
            search = st.text_input("Search case ID or owner name")

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
        st.dataframe(
            view[[c for c in display_cols if c in view.columns]],
            use_container_width=True,
            hide_index=True,
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
    st.markdown("<div class='page-title'>Historical Knowledge Base</div>", unsafe_allow_html=True)
    st.markdown("<div class='page-sub'>Validated cases used for embedding retrieval and novelty calibration</div>", unsafe_allow_html=True)

    df = load_historical()
    if df.empty:
        st.info("No historical cases yet. Run scripts/seed_db.py.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Cases", len(df))
        if "decision" in df:
            c2.metric("Accepted", int((df["decision"] == "Accepted").sum()))
            c3.metric("Rejected", int((df["decision"] == "Rejected").sum()))

        st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)

        col_a, col_b = st.columns(2)
        with col_a:
            if "city" in df and df["city"].notna().any():
                st.markdown("**Cases by city**")
                cc = df["city"].value_counts().head(12).reset_index()
                cc.columns = ["city", "count"]
                if _HAS_ALT:
                    st.altair_chart(
                        alt.Chart(cc)
                        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4, color="#3b82f6")
                        .encode(
                            x=alt.X("count:Q", title="Cases"),
                            y=alt.Y("city:N", sort="-x", title=None),
                            tooltip=["city:N", "count:Q"],
                        )
                        .properties(height=260)
                        .configure_view(strokeWidth=0)
                        .configure(background="transparent"),
                        use_container_width=True,
                    )
                else:
                    st.bar_chart(cc.set_index("city"))

        with col_b:
            if "property_type" in df and df["property_type"].notna().any():
                st.markdown("**Cases by property type**")
                pc = df["property_type"].value_counts().reset_index()
                pc.columns = ["property_type", "count"]
                if _HAS_ALT:
                    st.altair_chart(
                        alt.Chart(pc)
                        .mark_arc(innerRadius=55, outerRadius=90)
                        .encode(
                            theta=alt.Theta("count:Q"),
                            color=alt.Color(
                                "property_type:N",
                                scale=alt.Scale(range=CHART_COLORS),
                                legend=alt.Legend(orient="right"),
                            ),
                            tooltip=["property_type:N", "count:Q"],
                        )
                        .properties(height=260)
                        .configure_view(strokeWidth=0)
                        .configure(background="transparent"),
                        use_container_width=True,
                    )
                else:
                    st.bar_chart(pc.set_index("property_type"))

        st.markdown("<hr class='section-rule'>", unsafe_allow_html=True)
        if "decision" in df:
            decisions = df["decision"].dropna().unique().tolist()
            dfilter = st.multiselect("Filter by decision", decisions, default=decisions)
            view = df[df["decision"].isin(dfilter)] if dfilter else df
        else:
            view = df

        st.dataframe(view, use_container_width=True, hide_index=True)
