"""
Streamlit reviewer UI.

Run with: streamlit run src/reviewer_ui.py

Shows three views:
  1. Needs Review  — flagged cases awaiting human validation
  2. All Incoming  — full queue with status filters
  3. Historical    — the validated seed + growth-loop cases
"""
from __future__ import annotations

import os
import sys

import streamlit as st
import pandas as pd
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml
from src.db_client import DBClient

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

db = DBClient(cfg["db"]["path"])

st.set_page_config(page_title="Document Acceptance Review", layout="wide")
st.title("Document Acceptance Review")

tab_review, tab_all, tab_hist = st.tabs(["🔴 Needs Review", "📋 All Incoming", "📚 Historical"])

# ------------------------------------------------------------------
# Tab 1: Needs Review
# ------------------------------------------------------------------
with tab_review:
    rows = db.read_incoming()
    flagged = [r for r in rows if r.get("needs_review") == 1 and not r.get("validated_by")]

    if not flagged:
        st.success("No cases pending review.")
    else:
        st.write(f"**{len(flagged)} case(s) awaiting validation**")

        for case in flagged:
            with st.expander(
                f"🔍 {case['case_id']} — {case.get('flag_reason', '')} | {case.get('decision', '')} ({case.get('reason_code', '')})",
                expanded=False,
            ):
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader("Case Attributes")
                    attr_fields = [
                        "document_type", "owner_name", "owner_id", "property_id",
                        "property_type", "area_sqm", "address", "city",
                        "notarized", "owner_signature", "liens_present", "registration_date",
                    ]
                    for f in attr_fields:
                        val = case.get(f, "")
                        if val not in (None, ""):
                            st.text(f"{f}: {val}")

                with col2:
                    st.subheader("Decision")
                    st.markdown(f"**Decision:** {case.get('decision', '')} / {case.get('reason_code', '')}")
                    st.markdown(f"**Flag reason:** `{case.get('flag_reason', '')}`")
                    nn = case.get("nn_distance")
                    if nn is not None:
                        st.markdown(f"**NN distance:** `{float(nn):.4f}`")
                    st.markdown("---")
                    st.markdown(f"**EN:** {case.get('recommendation_en', '')}")
                    st.markdown(f"**AR:** {case.get('recommendation_ar', '')}")
                    retrieved = case.get("retrieved_case_ids", "")
                    if retrieved:
                        st.markdown(f"**Nearest neighbours:** `{retrieved}`")

                st.markdown("---")
                reviewer_id = st.text_input(
                    "Your reviewer ID (e.g. employee number or name)",
                    key=f"reviewer_{case['case_id']}",
                    placeholder="e.g. EMP-042",
                )
                col_approve, col_skip = st.columns([1, 4])
                with col_approve:
                    if st.button("✅ Validate", key=f"validate_{case['case_id']}"):
                        if not reviewer_id.strip():
                            st.error("Enter your reviewer ID first.")
                        else:
                            db.write_recommendation(case["case_id"], {"validated_by": reviewer_id.strip()})
                            st.success(f"Validated by {reviewer_id}. Growth loop will pick this up on next poll.")
                            st.rerun()

# ------------------------------------------------------------------
# Tab 2: All Incoming
# ------------------------------------------------------------------
with tab_all:
    rows = db.read_incoming()
    if not rows:
        st.info("No incoming cases yet.")
    else:
        df = pd.DataFrame(rows)

        status_filter = st.multiselect(
            "Filter by status",
            options=df["status"].unique().tolist(),
            default=df["status"].unique().tolist(),
        )
        df = df[df["status"].isin(status_filter)]

        needs_review_only = st.checkbox("Show needs_review only")
        if needs_review_only:
            df = df[df["needs_review"] == 1]

        display_cols = [
            "case_id", "status", "decision", "reason_code",
            "flag_reason", "needs_review", "validated_by", "nn_distance", "processed_at",
        ]
        st.dataframe(df[[c for c in display_cols if c in df.columns]], use_container_width=True)

        st.download_button(
            "Download CSV",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"incoming_cases_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )

# ------------------------------------------------------------------
# Tab 3: Historical
# ------------------------------------------------------------------
with tab_hist:
    rows = db.read_historical()
    if not rows:
        st.info("No historical cases yet. Run scripts/seed_db.py first.")
    else:
        df = pd.DataFrame(rows)
        st.write(f"**{len(df)} validated historical cases**")

        decision_filter = st.multiselect(
            "Filter by decision",
            options=df["decision"].unique().tolist() if "decision" in df.columns else [],
            default=df["decision"].unique().tolist() if "decision" in df.columns else [],
        )
        if decision_filter:
            df = df[df["decision"].isin(decision_filter)]

        st.dataframe(df, use_container_width=True)
