"""
Document Acceptance — Reviewer Console (Streamlit).

Run with:  streamlit run src/reviewer_ui.py

A full multi-page console:
  • Dashboard      — KPIs, decision/reason charts, novelty distribution
  • Review Queue   — rich bilingual cards for human validation
  • Submit Case    — form that inserts a case and triggers processing
  • Case Explorer  — filterable table of every incoming case
  • Historical     — the validated knowledge base
Backend health / calibration / reindex are driven through the FastAPI service.
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
except Exception:  # pragma: no cover
    _HAS_ALT = False

try:
    import httpx
    _HAS_HTTPX = True
except Exception:  # pragma: no cover
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
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ------------------------------------------------------------------
# Styling
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1400px; }
      h1, h2, h3 { font-family: 'Segoe UI', system-ui, sans-serif; }
      div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #1e2a4a 0%, #2d3e63 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px; padding: 18px 20px;
        box-shadow: 0 4px 14px rgba(0,0,0,0.18);
      }
      div[data-testid="stMetric"] label p { color: #aab6d3 !important; font-weight: 600; }
      div[data-testid="stMetricValue"] { color: #ffffff; font-size: 2rem; }
      .ar-text {
        direction: rtl; text-align: right; font-size: 1.05rem;
        background: rgba(80,120,200,0.10); padding: 10px 14px;
        border-radius: 10px; border-right: 3px solid #5b8def;
      }
      .en-text {
        background: rgba(120,200,140,0.08); padding: 10px 14px;
        border-radius: 10px; border-left: 3px solid #4caf7d;
      }
      .badge {
        display: inline-block; padding: 3px 12px; border-radius: 999px;
        font-size: 0.8rem; font-weight: 700; letter-spacing: 0.3px;
      }
      .badge-accept { background: #1b5e20; color: #c8f7d4; }
      .badge-reject { background: #7f1d1d; color: #ffd4d4; }
      .badge-flag   { background: #7a5b00; color: #ffe9a8; }
      .pill { font-family: ui-monospace, monospace; background: rgba(255,255,255,0.07);
              padding: 2px 8px; border-radius: 6px; font-size: 0.82rem; }
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


def decision_badge(decision: str) -> str:
    d = (decision or "").lower()
    if d == "accepted":
        return '<span class="badge badge-accept">✓ ACCEPTED</span>'
    if d == "rejected":
        return '<span class="badge badge-reject">✕ REJECTED</span>'
    return f'<span class="badge badge-flag">{decision or "—"}</span>'


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


# ------------------------------------------------------------------
# Sidebar — branding, navigation, live system status
# ------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🏛️ Document Acceptance")
    st.caption("Bilingual review console")

    page = st.radio(
        "Navigate",
        ["📊 Dashboard", "🔴 Review Queue", "➕ Submit Case", "📋 Case Explorer", "📚 Historical"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("### System status")
    health = api_get("/health")
    if health:
        st.success("Backend online")
        st.metric("Indexed cases", health.get("chroma_count", "—"))
        st.caption(f"Version: `{health.get('active_version', '—')}`")
    else:
        st.error("Backend offline")
        st.caption("Start it with `uvicorn src.main:app`")

    calib = api_get("/calibration")
    if calib and "threshold" in calib:
        st.metric("Novelty threshold", f"{calib['threshold']:.4f}")

    st.markdown("---")
    if st.button("🔄 Reindex + recalibrate", use_container_width=True):
        with st.spinner("Rebuilding ChromaDB from historical cases…"):
            res, err = api_post("/reindex")
        if err:
            st.error(f"Reindex failed: {err}")
        else:
            st.success("Reindexed.")
            st.json(res)
    if st.button("⚙️ Process pending now", use_container_width=True):
        with st.spinner("Processing pending cases…"):
            res, err = api_post("/process")
        if err:
            st.error(f"Process failed: {err}")
        else:
            st.success(f"Processed {res.get('processed', 0)} case(s).")


# ==================================================================
# PAGE: Dashboard
# ==================================================================
if page == "📊 Dashboard":
    st.title("📊 Operations Dashboard")
    df = load_incoming()

    if df.empty:
        st.info("No cases processed yet. Submit a case or run the seeder.")
    else:
        total = len(df)
        done = int((df.get("status") == "done").sum()) if "status" in df else 0
        pending = int((df.get("status") == "pending").sum()) if "status" in df else 0
        flagged = int((df.get("needs_review") == 1).sum()) if "needs_review" in df else 0
        awaiting = int(((df.get("needs_review") == 1) & (df.get("validated_by").isna() | (df.get("validated_by") == ""))).sum()) if "needs_review" in df else 0
        accepted = int((df.get("decision") == "Accepted").sum()) if "decision" in df else 0
        rejected = int((df.get("decision") == "Rejected").sum()) if "decision" in df else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total cases", total)
        c2.metric("Processed", done)
        c3.metric("Pending", pending)
        c4.metric("Accepted", accepted)
        c5.metric("Awaiting review", awaiting)

        st.markdown("---")
        col_a, col_b = st.columns(2)

        with col_a:
            st.subheader("Decisions")
            if "decision" in df and df["decision"].notna().any():
                dc = df["decision"].fillna("(unprocessed)").value_counts().reset_index()
                dc.columns = ["decision", "count"]
                if _HAS_ALT:
                    chart = alt.Chart(dc).mark_arc(innerRadius=60).encode(
                        theta="count:Q",
                        color=alt.Color("decision:N", scale=alt.Scale(
                            domain=["Accepted", "Rejected", "(unprocessed)"],
                            range=["#4caf7d", "#e15554", "#888"])),
                        tooltip=["decision", "count"],
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.bar_chart(dc.set_index("decision"))
            else:
                st.caption("No decisions yet.")

        with col_b:
            st.subheader("Rejection reasons")
            rej = df[df.get("decision") == "Rejected"] if "decision" in df else pd.DataFrame()
            if not rej.empty and "reason_code" in rej:
                rc = rej["reason_code"].value_counts().reset_index()
                rc.columns = ["reason_code", "count"]
                if _HAS_ALT:
                    chart = alt.Chart(rc).mark_bar().encode(
                        x="count:Q",
                        y=alt.Y("reason_code:N", sort="-x"),
                        color=alt.value("#e15554"),
                        tooltip=["reason_code", "count"],
                    )
                    st.altair_chart(chart, use_container_width=True)
                else:
                    st.bar_chart(rc.set_index("reason_code"))
            else:
                st.caption("No rejections yet.")

        st.markdown("---")
        st.subheader("Novelty distance distribution")
        if "nn_distance" in df and df["nn_distance"].notna().any():
            nd = df[["case_id", "nn_distance"]].dropna()
            thr = calib.get("threshold") if calib else None
            if _HAS_ALT:
                base = alt.Chart(nd).mark_bar(opacity=0.8).encode(
                    x=alt.X("nn_distance:Q", bin=alt.Bin(maxbins=30), title="NN distance"),
                    y=alt.Y("count()", title="cases"),
                    color=alt.value("#5b8def"),
                )
                if thr:
                    rule = alt.Chart(pd.DataFrame({"t": [thr]})).mark_rule(
                        color="#ffb300", strokeDash=[6, 4], size=2).encode(x="t:Q")
                    st.altair_chart(base + rule, use_container_width=True)
                    st.caption(f"Dashed line = novelty threshold ({thr:.4f}). Cases to the right are flagged as novel.")
                else:
                    st.altair_chart(base, use_container_width=True)
            else:
                st.bar_chart(nd.set_index("case_id"))
        else:
            st.caption("No novelty scores yet.")


# ==================================================================
# PAGE: Review Queue
# ==================================================================
elif page == "🔴 Review Queue":
    st.title("🔴 Review Queue")
    df = load_incoming()
    rows = df.to_dict("records") if not df.empty else []
    flagged = [r for r in rows if r.get("needs_review") == 1 and not r.get("validated_by")]

    if not flagged:
        st.success("🎉 Nothing in the queue — all flagged cases have been validated.")
    else:
        st.caption(f"{len(flagged)} case(s) awaiting human validation")
        for case in flagged:
            header = f"🔍 {case['case_id']}  ·  {case.get('decision','')} ({case.get('reason_code','')})  ·  flag: {case.get('flag_reason','')}"
            with st.expander(header, expanded=False):
                top = st.container()
                with top:
                    st.markdown(decision_badge(case.get("decision", "")), unsafe_allow_html=True)

                col1, col2 = st.columns([1, 1])
                with col1:
                    st.markdown("##### Case attributes")
                    attrs = {f: case.get(f) for f in ATTR_FIELDS if case.get(f) not in (None, "")}
                    st.table(pd.DataFrame(list(attrs.items()), columns=["field", "value"]))

                with col2:
                    st.markdown("##### Decision context")
                    st.markdown(f"**Reason code:** <span class='pill'>{case.get('reason_code','')}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Flag reason:** <span class='pill'>{case.get('flag_reason','')}</span>", unsafe_allow_html=True)
                    nn = case.get("nn_distance")
                    if nn is not None:
                        st.markdown(f"**NN distance:** <span class='pill'>{float(nn):.4f}</span>", unsafe_allow_html=True)
                    retrieved = case.get("retrieved_case_ids", "")
                    if retrieved:
                        st.markdown(f"**Nearest neighbours:** <span class='pill'>{retrieved}</span>", unsafe_allow_html=True)

                    st.markdown("**Explanation (EN)**")
                    st.markdown(f"<div class='en-text'>{case.get('recommendation_en','—')}</div>", unsafe_allow_html=True)
                    st.markdown("**التوضيح (AR)**")
                    st.markdown(f"<div class='ar-text'>{case.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)

                st.markdown("---")
                reviewer_id = st.text_input(
                    "Reviewer ID", key=f"rev_{case['case_id']}", placeholder="e.g. EMP-042"
                )
                b1, b2, _ = st.columns([1, 1, 3])
                with b1:
                    if st.button("✅ Validate", key=f"val_{case['case_id']}", use_container_width=True):
                        if not reviewer_id.strip():
                            st.error("Enter your reviewer ID first.")
                        else:
                            db.write_recommendation(case["case_id"], {"validated_by": reviewer_id.strip()})
                            st.success(f"Validated by {reviewer_id}. Growth loop will append it on next poll.")
                            st.rerun()


# ==================================================================
# PAGE: Submit Case
# ==================================================================
elif page == "➕ Submit Case":
    st.title("➕ Submit a New Case")
    st.caption("Insert a case into the queue and (optionally) process it immediately.")

    with st.form("new_case"):
        c1, c2, c3 = st.columns(3)
        with c1:
            case_id = st.text_input("Case ID *", placeholder="CASE-1001")
            document_type = st.text_input("Document type", value="عقد بيع")
            owner_name = st.text_input("Owner name", value="")
            owner_id = st.text_input("Owner ID (10 digits, 1/2…)", value="")
        with c2:
            property_id = st.text_input("Property ID", value="")
            property_type = st.text_input("Property type", value="apartment")
            area_sqm = st.number_input("Area (sqm)", min_value=0.0, value=100.0, step=10.0)
            registration_date = st.date_input("Registration date", value=date(2022, 1, 1))
        with c3:
            address = st.text_input("Address", value="")
            city = st.text_input("City", value="Riyadh")
            notarized = st.checkbox("Notarized", value=True)
            owner_signature = st.checkbox("Owner signature", value=True)
            liens_present = st.checkbox("Liens present", value=False)

        process_now = st.checkbox("Process immediately after insert", value=True)
        submitted = st.form_submit_button("➕ Insert case", use_container_width=True)

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
            st.success(f"Inserted {case_id}.")
            if process_now:
                with st.spinner("Processing through rule engine + novelty + Qwen…"):
                    res, err = api_post(f"/process?case_id={case_id.strip()}")
                if err:
                    st.warning(f"Inserted, but processing failed: {err}")
                elif res and res.get("results"):
                    out = res["results"][0]
                    st.markdown(decision_badge(out.get("decision", "")), unsafe_allow_html=True)
                    st.markdown(f"**Reason:** <span class='pill'>{out.get('reason_code','')}</span>", unsafe_allow_html=True)
                    st.markdown(f"<div class='en-text'>{out.get('recommendation_en','—')}</div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='ar-text'>{out.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)
                    if out.get("needs_review"):
                        st.warning("⚠️ This case was flagged and is now in the Review Queue.")
                else:
                    st.info("Processed — check the Case Explorer.")


# ==================================================================
# PAGE: Case Explorer
# ==================================================================
elif page == "📋 Case Explorer":
    st.title("📋 Case Explorer")
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
            search = st.text_input("Search case ID / owner")

        view = df.copy()
        if status_filter and "status" in view:
            view = view[view["status"].isin(status_filter)]
        if decision_filter and "decision" in view:
            view = view[view["decision"].isin(decision_filter)]
        if st.checkbox("Needs review only") and "needs_review" in view:
            view = view[view["needs_review"] == 1]
        if search:
            mask = pd.Series(False, index=view.index)
            for col in ("case_id", "owner_name"):
                if col in view:
                    mask = mask | view[col].astype(str).str.contains(search, case=False, na=False)
            view = view[mask]

        st.caption(f"{len(view)} case(s)")
        display_cols = [
            "case_id", "status", "decision", "reason_code", "flag_reason",
            "needs_review", "validated_by", "nn_distance", "processed_at",
        ]
        st.dataframe(
            view[[c for c in display_cols if c in view.columns]],
            use_container_width=True, hide_index=True,
        )
        st.download_button(
            "⬇️ Download CSV",
            view.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"incoming_cases_{datetime.now():%Y%m%d}.csv",
            mime="text/csv",
        )


# ==================================================================
# PAGE: Historical
# ==================================================================
elif page == "📚 Historical":
    st.title("📚 Historical Knowledge Base")
    df = load_historical()
    if df.empty:
        st.info("No historical cases yet. Run `python scripts/seed_db.py`.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total cases", len(df))
        if "decision" in df:
            c2.metric("Accepted", int((df["decision"] == "Accepted").sum()))
            c3.metric("Rejected", int((df["decision"] == "Rejected").sum()))

        st.markdown("---")
        col_a, col_b = st.columns(2)
        with col_a:
            if "city" in df and df["city"].notna().any():
                st.subheader("By city")
                cc = df["city"].value_counts().head(12).reset_index()
                cc.columns = ["city", "count"]
                if _HAS_ALT:
                    st.altair_chart(
                        alt.Chart(cc).mark_bar(color="#5b8def").encode(
                            x="count:Q", y=alt.Y("city:N", sort="-x"), tooltip=["city", "count"]),
                        use_container_width=True,
                    )
                else:
                    st.bar_chart(cc.set_index("city"))
        with col_b:
            if "property_type" in df and df["property_type"].notna().any():
                st.subheader("By property type")
                pc = df["property_type"].value_counts().reset_index()
                pc.columns = ["property_type", "count"]
                if _HAS_ALT:
                    st.altair_chart(
                        alt.Chart(pc).mark_arc(innerRadius=50).encode(
                            theta="count:Q", color="property_type:N", tooltip=["property_type", "count"]),
                        use_container_width=True,
                    )
                else:
                    st.bar_chart(pc.set_index("property_type"))

        st.markdown("---")
        decisions = df["decision"].dropna().unique().tolist() if "decision" in df else []
        dfilter = st.multiselect("Filter by decision", decisions, default=decisions)
        view = df[df["decision"].isin(dfilter)] if dfilter and "decision" in df else df
        st.dataframe(view, use_container_width=True, hide_index=True)
