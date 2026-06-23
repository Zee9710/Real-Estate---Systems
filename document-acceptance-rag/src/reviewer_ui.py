"""
Document Acceptance — Reviewer Console (Streamlit).

Run with:  streamlit run src/reviewer_ui.py

Architecture (pragmatic hybrid):
  • Browsing/reads come straight from the SQLite DB via DBClient, so every
    page works even if the FastAPI service is momentarily down.
  • Compute actions (process a case, reindex) go through the FastAPI service.
  • Review / override / growth decisions are written to incoming_cases via
    DBClient. The few extra reviewer columns are added with an idempotent,
    UI-side migration so we never have to touch db_client.py.

Charts use plotly when available and fall back to altair, then to native
Streamlit charts — so a missing plotly install can never crash the page.

The console is in English. Arabic calligraphy appears on the landing page
as a decorative brand element only.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, date

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import yaml

# --- optional chart backends (graceful degradation) ----------------
try:
    import plotly.express as px
    import plotly.graph_objects as go
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

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
# Config
# ------------------------------------------------------------------
CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")
with open(CONFIG_PATH) as f:
    cfg = yaml.safe_load(f)

# Frontend-specific config (optional file).
FE_CFG = {"backend_url": "http://localhost:8000",
          "display": {"neighbours_k": 5, "flag_rate_high": 0.80, "flag_rate_low": 0.05}}
if os.path.exists("frontend_config.yaml"):
    with open("frontend_config.yaml") as f:
        loaded = yaml.safe_load(f) or {}
        FE_CFG.update(loaded)

API_BASE = os.environ.get("BACKEND_URL", FE_CFG.get("backend_url", "http://localhost:8000"))
NEIGHBOURS_K = FE_CFG.get("display", {}).get("neighbours_k", 5)
FLAG_HIGH = FE_CFG.get("display", {}).get("flag_rate_high", 0.80)
FLAG_LOW = FE_CFG.get("display", {}).get("flag_rate_low", 0.05)

db = DBClient(cfg["db"]["path"])

st.set_page_config(page_title="Document Acceptance System", layout="wide", initial_sidebar_state="expanded")

# Colours — emerald green brand family (NAVY kept as the name for the primary accent)
NAVY, GREEN, RED, AMBER, GREY = "#059669", "#10b981", "#ef4444", "#f59e0b", "#94a3b8"
PALETTE = ["#065f46", "#059669", "#10b981", "#34d399", "#14b8a6", "#6ee7b7", "#0d9488"]


# ------------------------------------------------------------------
# One-time, idempotent schema top-up (kept out of db_client.py on purpose)
# ------------------------------------------------------------------
def ensure_reviewer_columns():
    extra = [
        ("reviewed", "INTEGER DEFAULT 0"),
        ("approved_for_growth", "INTEGER"),
        ("reviewer_notes", "TEXT"),
        ("override_decision", "TEXT"),
        ("override_reason", "TEXT"),
    ]
    with db._conn() as con:
        for col, typ in extra:
            try:
                con.execute(f"ALTER TABLE incoming_cases ADD COLUMN {col} {typ}")
            except Exception:
                pass


ensure_reviewer_columns()

# ------------------------------------------------------------------
# Minimal CSS — only what native theming can't express
# ------------------------------------------------------------------
st.markdown(
    """
    <style>
      .block-container { padding-top: 1.6rem; max-width: 1450px; }

      /* ---- Hero header ---- */
      .hero {
        background: linear-gradient(110deg, #065f46 0%, #059669 50%, #10b981 100%);
        border-radius: 16px; padding: 20px 26px; margin-bottom: 22px;
        color: #fff; box-shadow: 0 10px 30px -10px rgba(5,150,105,0.55);
      }
      .hero h2 { margin: 0; font-size: 1.35rem; font-weight: 700; color: #fff; }
      .hero p  { margin: 4px 0 0 0; font-size: 0.85rem; color: #d1fae5; }

      /* ---- Sidebar: emerald gradient fill ---- */
      section[data-testid="stSidebar"] > div {
        background: linear-gradient(180deg, #065f46 0%, #047857 60%, #059669 100%);
      }
      section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label:hover {
        background: rgba(255,255,255,0.10); border-radius: 8px;
      }
      /* On the emerald sidebar, render gradient labels as solid light text */
      section[data-testid="stSidebar"] .caption-label {
        background: none !important; -webkit-text-fill-color: #a7f3d0 !important; color: #a7f3d0 !important;
      }

      /* ---- Metric cards get colour + lift ---- */
      div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #d1fae5;
        border-left: 5px solid #059669;
        border-radius: 12px; padding: 16px 18px;
        box-shadow: 0 4px 14px -8px rgba(6,95,70,0.25);
        transition: transform .12s ease, box-shadow .12s ease;
      }
      div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 22px -10px rgba(6,95,70,0.4);
      }
      div[data-testid="stMetricValue"] { color:#064e3b; font-weight:700; }
      div[data-testid="stMetricLabel"] p { color:#059669 !important; font-weight:600; }

      /* Rotate emerald shades of metric cards across a row */
      div[data-testid="column"]:nth-child(5n+1) div[data-testid="stMetric"] { border-left-color:#065f46; }
      div[data-testid="column"]:nth-child(5n+2) div[data-testid="stMetric"] { border-left-color:#059669; }
      div[data-testid="column"]:nth-child(5n+3) div[data-testid="stMetric"] { border-left-color:#10b981; }
      div[data-testid="column"]:nth-child(5n+4) div[data-testid="stMetric"] { border-left-color:#34d399; }
      div[data-testid="column"]:nth-child(5n+5) div[data-testid="stMetric"] { border-left-color:#047857; }

      /* ---- Bordered containers as soft cards ---- */
      div[data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 14px !important;
        box-shadow: 0 2px 10px -6px rgba(6,95,70,0.18);
      }

      /* ---- Badges (richer, pill-shaped) ---- */
      .badge { display:inline-block; padding:4px 14px; border-radius:999px;
               font-size:0.72rem; font-weight:700; letter-spacing:0.04em; text-transform:uppercase; }
      .badge-accept  { background:linear-gradient(135deg,#6ee7b7,#34d399); color:#064e3b; }
      .badge-reject  { background:linear-gradient(135deg,#fecaca,#fca5a5); color:#7f1d1d; }
      .badge-flag    { background:linear-gradient(135deg,#fde68a,#fcd34d); color:#78350f; }
      .badge-pending { background:linear-gradient(135deg,#e2e8f0,#cbd5e1); color:#334155; }

      /* ---- Explanation panels ---- */
      .panel-ar { direction:rtl; text-align:right;
                  background:linear-gradient(95deg,#d1fae5,#f0fdf4); border-right:4px solid #059669;
                  padding:13px 17px; border-radius:10px 0 0 10px; font-size:1.02rem; line-height:1.85; color:#0f291f; }
      .panel-en { background:linear-gradient(265deg,#ecfdf5,#f0fdf4); border-left:4px solid #10b981;
                  padding:13px 17px; border-radius:0 10px 10px 0; font-size:0.95rem; line-height:1.6;
                  color:#0f291f; margin-bottom:10px; }

      /* ---- Arabic calligraphy landing block ---- */
      .arabic-calli {
        text-align: center; direction: rtl;
        font-family: 'Scheherazade New', 'Amiri', 'Noto Naskh Arabic', serif;
        font-size: clamp(2.4rem, 5vw, 3.6rem);
        line-height: 1.55;
        color: #ffffff;
        font-weight: 700;
        padding: 14px 20px 10px;
        letter-spacing: 0.02em;
        background: rgba(0,0,0,0.28);
        border-radius: 12px;
        display: inline-block;
        text-shadow: 0 2px 8px rgba(0,0,0,0.6);
      }
      .arabic-sub {
        text-align: center;
        font-size: 0.78rem; letter-spacing: 0.18em; text-transform: uppercase;
        color: #6ee7b7; font-weight: 600; margin-top: 2px;
      }
      .landing-divider {
        border: none; border-top: 1px solid #d1fae5; margin: 18px auto; width: 60%;
      }

      /* ---- Pills / keys ---- */
      .pill { font-family:ui-monospace,monospace; background:#d1fae5; color:#065f46; padding:2px 9px;
              border-radius:6px; font-size:0.82rem; border:1px solid #6ee7b7; }
      .kv-key { color:#475569; font-size:0.82rem; }
      .kv-key-hot { color:#dc2626; font-weight:700; font-size:0.82rem; }
      .caption-label { font-size:0.7rem; font-weight:700; letter-spacing:0.09em;
                       text-transform:uppercase;
                       background:linear-gradient(90deg,#065f46,#10b981);
                       -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
      .rtl { direction:rtl; text-align:right; }

      /* ---- Buttons ---- */
      .stButton > button {
        border-radius: 9px; font-weight: 600;
        transition: transform .1s ease, box-shadow .1s ease;
      }
      .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 6px 16px -8px rgba(5,150,105,0.6); }
    </style>
    """,
    unsafe_allow_html=True,
)


# ------------------------------------------------------------------
# Arabic labels + static rule reference
# ------------------------------------------------------------------
FIELD_LABELS = {
    "case_id": "Case ID",
    "document_type": "Document type",
    "owner_name": "Owner name",
    "owner_id": "Owner ID",
    "property_id": "Property ID",
    "property_type": "Property type",
    "area_sqm": "Area (sqm)",
    "address": "Address",
    "city": "City",
    "notarized": "Notarized",
    "owner_signature": "Owner signature",
    "liens_present": "Liens present",
    "registration_date": "Registration date",
}
ATTR_FIELDS = list(FIELD_LABELS.keys())

# Which attribute a reason_code points at — used to highlight the offending field.
REASON_TO_FIELD = {
    "MISSING_OWNER_NAME": "owner_name",
    "MISSING_PROPERTY_ID": "property_id",
    "MISSING_OWNER_SIGNATURE": "owner_signature",
    "NOT_NOTARIZED": "notarized",
    "LIEN_PRESENT": "liens_present",
    "INCOMPLETE_ADDRESS": "address",
    "INVALID_AREA": "area_sqm",
    "OWNER_ID_MISMATCH": "owner_id",
    "EXPIRED_REGISTRATION": "registration_date",
}

RULES = [
    ("MEETS_CRITERIA", "All checks pass", "Accepted"),
    ("MISSING_OWNER_NAME", "owner_name is empty", "Rejected"),
    ("MISSING_PROPERTY_ID", "property_id is empty", "Rejected"),
    ("MISSING_OWNER_SIGNATURE", "owner_signature = false", "Rejected"),
    ("NOT_NOTARIZED", "Not notarized (title deed only)", "Rejected"),
    ("LIEN_PRESENT", "liens_present = true", "Rejected"),
    ("INCOMPLETE_ADDRESS", "address or city is empty", "Rejected"),
    ("INVALID_AREA", "area_sqm missing or ≤ 0", "Rejected"),
    ("OWNER_ID_MISMATCH", "owner_id wrong format or length", "Rejected"),
    ("EXPIRED_REGISTRATION", "registration_date too old", "Rejected"),
]


# ------------------------------------------------------------------
# API + data helpers
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


@st.cache_data(ttl=5)
def load_incoming() -> pd.DataFrame:
    rows = db.read_incoming()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


@st.cache_data(ttl=5)
def load_historical() -> pd.DataFrame:
    rows = db.read_historical()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def refresh():
    load_incoming.clear()
    load_historical.clear()


def badge(decision: str) -> str:
    d = (decision or "").lower()
    if d == "accepted":
        return '<span class="badge badge-accept">Accepted</span>'
    if d == "rejected":
        return '<span class="badge badge-reject">Rejected</span>'
    return '<span class="badge badge-pending">Pending</span>'


def page_header(title: str, subtitle: str = ""):
    """Gradient hero header used at the top of every page."""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(f"<div class='hero'><h2>{title}</h2>{sub}</div>", unsafe_allow_html=True)


def _lookup_historical(ids: list[str]) -> dict:
    hist = load_historical()
    if hist.empty:
        return {}
    by_id = {r["case_id"]: r for r in hist.to_dict("records")}
    return {i: by_id[i] for i in ids if i in by_id}


def get_neighbours(retrieved_ids: str, case_id: str | None = None) -> list[dict]:
    """Return nearest historical neighbours (nearest first) with full attributes.

    Prefers the live /neighbours endpoint so we get each neighbour's individual
    distance; falls back to the IDs stored on the case (no per-neighbour distance)
    when the backend is unreachable."""
    live = api_get(f"/cases/incoming/{case_id}/neighbours?k={NEIGHBOURS_K}") if case_id else None
    if live and live.get("neighbours"):
        pairs = [(n["case_id"], n.get("distance")) for n in live["neighbours"]]
    elif retrieved_ids:
        pairs = [(x.strip(), None) for x in str(retrieved_ids).split(",") if x.strip()]
    else:
        return []
    hist = _lookup_historical([cid for cid, _ in pairs])
    out = []
    for cid, dist in pairs:
        row = dict(hist.get(cid, {"case_id": cid}))
        row["_distance"] = dist
        out.append(row)
    return out


def threshold_bar(distance: float, threshold: float):
    """Horizontal bar showing where a case's mean distance sits vs the threshold."""
    if not _HAS_PLOTLY:
        ratio = min(distance / threshold, 2.0) if threshold else 0
        st.progress(min(ratio / 2.0, 1.0))
        st.caption(f"Distance {distance:.4f}  ·  Threshold {threshold:.4f}")
        return
    axis_max = max(distance, threshold) * 1.4 or 1.0
    color = RED if distance > threshold else GREEN
    fig = go.Figure()
    fig.add_trace(go.Bar(x=[distance], y=["distance"], orientation="h",
                         marker_color=color, width=0.5, hoverinfo="x"))
    fig.add_vline(x=threshold, line_dash="dash", line_color=AMBER, line_width=2,
                  annotation_text=f"Threshold {threshold:.4f}", annotation_position="top")
    fig.update_layout(height=110, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis=dict(range=[0, axis_max], title="Mean NN distance"),
                      yaxis=dict(showticklabels=False), showlegend=False,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)


# ----- chart helpers (plotly → altair → native) ---------------------
def chart_donut(df_counts: pd.DataFrame, name_col: str, val_col: str, color_map=None):
    if _HAS_PLOTLY:
        fig = px.pie(df_counts, names=name_col, values=val_col, hole=0.58,
                     color=name_col, color_discrete_map=color_map,
                     color_discrete_sequence=PALETTE)
        fig.update_traces(textposition="outside", textinfo="label+value")
        fig.update_layout(height=250, margin=dict(l=0, r=0, t=10, b=10),
                          showlegend=True, paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    elif _HAS_ALT:
        ch = alt.Chart(df_counts).mark_arc(innerRadius=55, outerRadius=90).encode(
            theta=f"{val_col}:Q", color=f"{name_col}:N", tooltip=[name_col, val_col]
        ).properties(height=250).configure_view(strokeWidth=0).configure(background="transparent")
        st.altair_chart(ch, use_container_width=True)
    else:
        st.bar_chart(df_counts.set_index(name_col))


def chart_hbar(df_counts: pd.DataFrame, cat_col: str, val_col: str, color=NAVY):
    if _HAS_PLOTLY:
        fig = px.bar(df_counts.sort_values(val_col), x=val_col, y=cat_col, orientation="h")
        fig.update_traces(marker_color=color)
        fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=10),
                          xaxis_title="Cases", yaxis_title=None,
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    elif _HAS_ALT:
        ch = alt.Chart(df_counts).mark_bar(color=color).encode(
            x=alt.X(f"{val_col}:Q", title="Cases"),
            y=alt.Y(f"{cat_col}:N", sort="-x", title=None), tooltip=[cat_col, val_col]
        ).properties(height=260).configure_view(strokeWidth=0).configure(background="transparent")
        st.altair_chart(ch, use_container_width=True)
    else:
        st.bar_chart(df_counts.set_index(cat_col))


def chart_hist(series: pd.Series, threshold: float | None, title: str):
    data = pd.DataFrame({"d": series.dropna().values})
    if _HAS_PLOTLY:
        fig = px.histogram(data, x="d", nbins=30)
        fig.update_traces(marker_color=NAVY, opacity=0.8)
        if threshold:
            fig.add_vline(x=threshold, line_dash="dash", line_color=AMBER, line_width=2,
                          annotation_text=f"Threshold {threshold:.4f}")
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=10),
                          xaxis_title=title, yaxis_title="Cases",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)
    elif _HAS_ALT:
        base = alt.Chart(data).mark_bar(color=NAVY, opacity=0.8).encode(
            x=alt.X("d:Q", bin=alt.Bin(maxbins=30), title=title), y=alt.Y("count()", title="cases"))
        if threshold:
            rule = alt.Chart(pd.DataFrame({"t": [threshold]})).mark_rule(
                color=AMBER, strokeDash=[5, 4], size=2).encode(x="t:Q")
            base = base + rule
        st.altair_chart(base.properties(height=300).configure_view(strokeWidth=0).configure(
            background="transparent"), use_container_width=True)
    else:
        st.bar_chart(data)


def render_attributes(case: dict, hot_field: str | None = None):
    """Key/value attribute list with the rule-triggering field highlighted red."""
    rows = []
    for f in ATTR_FIELDS:
        val = case.get(f)
        if val in (None, ""):
            continue
        if f in ("notarized", "owner_signature", "liens_present"):
            val = "Yes" if str(val) in ("1", "True", "true") else "No"
        key_cls = "kv-key-hot" if f == hot_field else "kv-key"
        flag = " ⚠️" if f == hot_field else ""
        rows.append(
            f"<div style='display:flex;justify-content:space-between;padding:4px 0;"
            f"border-bottom:1px solid #f1f5f9;'>"
            f"<span class='{key_cls}'>{FIELD_LABELS[f]}{flag}</span>"
            f"<span style='font-weight:600;color:#1e293b;'>{val}</span></div>"
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def render_neighbours(neighbours: list[dict]):
    """Compact card list of similar historical cases (nearest first), each with
    its individual distance so the reviewer can judge how close each match is."""
    if not neighbours:
        st.caption("No similar historical cases recorded.")
        return
    for rank, nb in enumerate(neighbours, 1):
        with st.container(border=True):
            c = st.columns([2, 2, 2, 2, 3])
            c[0].markdown(f"**#{rank} · {nb.get('case_id','')}**")
            dist = nb.get("_distance")
            c[1].markdown(
                f"<span class='pill'>d = {dist:.4f}</span>" if dist is not None else "<span class='pill'>d = —</span>",
                unsafe_allow_html=True,
            )
            c[2].markdown(badge(nb.get("decision", "")), unsafe_allow_html=True)
            c[3].markdown(f"<span class='pill'>{nb.get('reason_code','')}</span>", unsafe_allow_html=True)
            c[4].caption(f"{nb.get('document_type','')} · {nb.get('property_type','')} · {nb.get('city','')}")


# ==================================================================
# Sidebar — navigation + live status + persistent reviewer ID
# ==================================================================
health = api_get("/health")
calib = api_get("/calibration")

if "reviewer_id" not in st.session_state:
    st.session_state.reviewer_id = ""

with st.sidebar:
    st.markdown(
        "<div style='padding:8px 0;'>"
        "<div style='font-size:1.05rem;font-weight:700;color:#ffffff;'>Document Acceptance</div>"
        "<div style='font-size:0.72rem;color:#a7f3d0;'>Reviewer Console</div>"
        "</div>",
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "Dashboard",
            "Review Queue",
            "Submit Case",
            "All Incoming",
            "Historical",
            "Calibration",
            "Rules",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("<span class='caption-label'>System Status</span>", unsafe_allow_html=True)
    if health:
        st.markdown("<span style='color:#22c55e;font-weight:600;font-size:0.84rem;'>● Online</span>",
                    unsafe_allow_html=True)
        st.metric("Indexed cases", health.get("chroma_count", "—"))
        st.caption(f"Version: {health.get('active_version', '—')}")
    else:
        st.markdown("<span style='color:#ef4444;font-weight:600;font-size:0.84rem;'>● Offline</span>",
                    unsafe_allow_html=True)
    if calib and "threshold" in calib:
        st.metric("Novelty threshold", f"{calib['threshold']:.4f}")

    st.divider()
    st.session_state.reviewer_id = st.text_input(
        "Reviewer ID", value=st.session_state.reviewer_id, placeholder="EMP-042"
    )
    if st.button("Refresh data", use_container_width=True):
        refresh()
        st.rerun()

# Persistent banner if the explanation backend is unreachable.
if not health:
    st.warning("Backend is unreachable. Browsing still works; processing and reindex are disabled.")


# ==================================================================
# PAGE: Dashboard  (Arabic calligraphy landing block)
# ==================================================================
if page == "Dashboard":
    # ---- Arabic calligraphy brand block ----
    st.markdown(
        """
        <div style='background:linear-gradient(110deg,#022c22 0%,#065f46 45%,#047857 100%);
                    border-radius:20px;padding:32px 28px 24px;margin-bottom:28px;
                    box-shadow:0 12px 36px -12px rgba(2,44,34,0.65);text-align:center;'>
          <div class='arabic-calli'>نِظَامُ قَبُولِ الْمُسْتَنَدَاتِ الْعَقَارِيَّة</div>
          <hr class='landing-divider'/>
          <div class='arabic-sub'>Document Acceptance System &nbsp;·&nbsp; Reviewer Console</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    page_header("Dashboard", "System overview — decisions, flagged cases, recent activity")
    df = load_incoming()
    if df.empty:
        st.info("No cases yet. Add one from the Submit Case page.")
    else:
        total = len(df)
        done = int((df["status"] == "done").sum()) if "status" in df else 0
        pending = int((df["status"] == "pending").sum()) if "status" in df else 0
        accepted = int((df["decision"] == "Accepted").sum()) if "decision" in df else 0
        rejected = int((df["decision"] == "Rejected").sum()) if "decision" in df else 0
        flagged = int((df["needs_review"] == 1).sum()) if "needs_review" in df else 0
        flag_rate = (flagged / done) if done else 0.0

        m = st.columns(5)
        m[0].metric("Total", total)
        m[1].metric("Accepted", accepted)
        m[2].metric("Rejected", rejected)
        m[3].metric("Flagged", flagged)
        m[4].metric("Pending", pending)

        if done and (flag_rate > FLAG_HIGH or flag_rate < FLAG_LOW):
            st.warning(f"Flag rate {flag_rate:.0%} is outside the expected range — calibration may need attention.")

        st.write("")
        col_a, col_b = st.columns(2)
        with col_a:
            with st.container(border=True):
                st.markdown("**Decision breakdown**")
                if "decision" in df and df["decision"].notna().any():
                    dc = df["decision"].fillna("Pending").value_counts().reset_index()
                    dc.columns = ["decision", "count"]
                    chart_donut(dc, "decision", "count",
                                color_map={"Accepted": GREEN, "Rejected": RED, "Pending": GREY})
                else:
                    st.caption("No decisions yet.")
        with col_b:
            with st.container(border=True):
                st.markdown("**Rejection reasons**")
                rej = df[df["decision"] == "Rejected"] if "decision" in df else pd.DataFrame()
                if not rej.empty and "reason_code" in rej.columns:
                    rc = rej["reason_code"].value_counts().reset_index()
                    rc.columns = ["reason_code", "count"]
                    chart_hbar(rc, "reason_code", "count", color=RED)
                else:
                    st.caption("No rejections yet.")

        st.write("")
        with st.container(border=True):
            st.markdown("**Recent activity**")
            recent_cols = [c for c in ["case_id", "decision", "flag_reason", "processed_at"] if c in df.columns]
            recent = df.sort_values("processed_at", ascending=False, na_position="last").head(10)
            st.dataframe(recent[recent_cols], hide_index=True, use_container_width=True)


# ==================================================================
# PAGE: Review Queue
# ==================================================================
elif page == "Review Queue":
    page_header("Review Queue", "Validate flagged cases and approve or reject for growth")
    df = load_incoming()
    rows = df.to_dict("records") if not df.empty else []
    queue = [r for r in rows if r.get("needs_review") == 1 and not r.get("reviewed")]

    # Filter bar
    f1, f2 = st.columns(2)
    flag_opts = ["All", "no_rule_fired", "novel_pattern"]
    flag_sel = f1.selectbox("Flag reason", flag_opts)
    doc_types = sorted({r.get("document_type", "") for r in queue if r.get("document_type")})
    doc_sel = f2.multiselect("Document type", doc_types, default=doc_types)

    if flag_sel != "All":
        queue = [r for r in queue if r.get("flag_reason") == flag_sel]
    if doc_sel:
        queue = [r for r in queue if r.get("document_type") in doc_sel]

    st.caption(f"{len(queue)} case(s) awaiting review")

    if not queue:
        st.success("No cases pending review.")

    threshold = (calib or {}).get("threshold", 0.0)

    for case in queue:
        cid = case["case_id"]
        title = f"{cid} · {case.get('document_type','')} · {case.get('reason_code','')} · flag: {case.get('flag_reason','')}"
        with st.expander(title, expanded=False):
            left, right = st.columns([1, 1])

            with left:
                st.markdown("<span class='caption-label'>Case attributes</span>", unsafe_allow_html=True)
                hot = REASON_TO_FIELD.get(case.get("reason_code", ""))
                render_attributes(case, hot_field=hot)

            with right:
                st.markdown("<span class='caption-label'>System output</span>", unsafe_allow_html=True)
                st.markdown(badge(case.get("decision", "")), unsafe_allow_html=True)
                st.markdown(
                    f"<br>Reason <span class='pill'>{case.get('reason_code','')}</span> "
                    f"&nbsp; Flag <span class='pill'>{case.get('flag_reason','')}</span>",
                    unsafe_allow_html=True,
                )
                st.markdown(f"<div class='panel-ar'>{case.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='panel-en'>{case.get('recommendation_en','—')}</div>", unsafe_allow_html=True)

            st.markdown("<span class='caption-label'>Nearest historical cases</span>", unsafe_allow_html=True)
            nn = case.get("nn_distance")
            if nn is not None and threshold:
                threshold_bar(float(nn), float(threshold))
            render_neighbours(get_neighbours(case.get("retrieved_case_ids", ""), case_id=cid))

            st.divider()
            # ---- review actions ----
            st.markdown("<span class='caption-label'>Review action</span>", unsafe_allow_html=True)
            decision_growth = st.radio(
                "Decision",
                ["Approve for growth", "Reject from growth"],
                key=f"grow_{cid}", horizontal=True, label_visibility="collapsed",
            )
            notes = st.text_area("Notes (optional)", key=f"notes_{cid}")

            with st.expander("Override system decision"):
                ov_decision = st.selectbox(
                    "New decision", ["— no override —", "Accepted", "Rejected"],
                    key=f"ovd_{cid}",
                )
                ov_reason = st.text_input("Override reason", key=f"ovr_{cid}")

            if st.button("Submit review", key=f"submit_{cid}", use_container_width=True):
                reviewer = st.session_state.reviewer_id.strip()
                if not reviewer:
                    st.error("Enter your Reviewer ID in the sidebar first.")
                elif ov_decision != "— no override —" and not ov_reason.strip():
                    st.error("Override reason is required when overriding the decision.")
                else:
                    approve = decision_growth == "Approve for growth"
                    updates = {
                        "reviewed": 1,
                        "approved_for_growth": 1 if approve else 0,
                        "reviewer_notes": notes.strip(),
                        "status": "done",
                    }
                    # growth loop only appends rows that have validated_by set
                    if approve:
                        updates["validated_by"] = reviewer
                    if ov_decision != "— no override —":
                        updates["decision"] = ov_decision
                        updates["override_decision"] = ov_decision
                        updates["override_reason"] = ov_reason.strip()
                    db.write_recommendation(cid, updates)
                    refresh()
                    st.success(f"Review saved for {cid} by {reviewer}.")
                    st.rerun()


# ==================================================================
# PAGE: Submit Case  (with 5 most-similar historical cases)
# ==================================================================
elif page == "Submit Case":
    page_header("Submit Case", "Insert a new case and see the most similar historical cases after processing")

    with st.form("new_case"):
        c1, c2, c3 = st.columns(3)
        with c1:
            case_id = st.text_input(FIELD_LABELS["case_id"] + " *", placeholder="CASE-1001")
            document_type = st.selectbox(FIELD_LABELS["document_type"], ["title_deed", "lease_contract", "power_of_attorney", "sale_contract"])
            owner_name = st.text_input(FIELD_LABELS["owner_name"])
            owner_id = st.text_input(FIELD_LABELS["owner_id"], placeholder="10-digit national ID")
        with c2:
            property_id = st.text_input(FIELD_LABELS["property_id"])
            property_type = st.selectbox(FIELD_LABELS["property_type"], ["apartment", "villa", "land", "commercial"])
            area_sqm = st.number_input(FIELD_LABELS["area_sqm"], min_value=0.0, value=100.0, step=10.0)
            registration_date = st.date_input(FIELD_LABELS["registration_date"], value=date(2022, 1, 1))
        with c3:
            address = st.text_input(FIELD_LABELS["address"])
            city = st.text_input(FIELD_LABELS["city"], value="Riyadh")
            notarized = st.checkbox(FIELD_LABELS["notarized"], value=True)
            owner_signature = st.checkbox(FIELD_LABELS["owner_signature"], value=True)
            liens_present = st.checkbox(FIELD_LABELS["liens_present"], value=False)
        submitted = st.form_submit_button("Insert & process", use_container_width=True)

    if submitted:
        if not case_id.strip():
            st.error("Case ID is required.")
        elif not health:
            st.error("Backend is offline — cannot process.")
        else:
            row = {
                "case_id": case_id.strip(), "document_type": document_type, "owner_name": owner_name,
                "owner_id": owner_id, "property_id": property_id, "property_type": property_type,
                "area_sqm": float(area_sqm), "address": address, "city": city,
                "notarized": 1 if notarized else 0, "owner_signature": 1 if owner_signature else 0,
                "liens_present": 1 if liens_present else 0,
                "registration_date": registration_date.isoformat(), "status": "pending",
            }
            db.upsert_incoming(row)
            with st.spinner("Processing through rule engine and novelty detector…"):
                res, err = api_post(f"/process?case_id={case_id.strip()}")
            refresh()
            if err:
                st.warning(f"Case inserted but processing failed: {err}")
            elif res and res.get("results"):
                out = res["results"][0]
                st.markdown(badge(out.get("decision", "")), unsafe_allow_html=True)
                st.markdown(f"<br>Reason <span class='pill'>{out.get('reason_code','')}</span>",
                            unsafe_allow_html=True)
                st.markdown(f"<div class='panel-ar'>{out.get('recommendation_ar','—')}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='panel-en'>{out.get('recommendation_en','—')}</div>", unsafe_allow_html=True)

                st.divider()
                st.markdown(f"#### Top {NEIGHBOURS_K} similar historical cases")
                threshold = (calib or {}).get("threshold", 0.0)
                nn = out.get("nn_distance")
                if nn is not None and threshold:
                    threshold_bar(float(nn), float(threshold))
                render_neighbours(get_neighbours(out.get("retrieved_case_ids", ""), case_id=case_id.strip()))
                if out.get("needs_review"):
                    st.info("This case has been flagged and added to the Review Queue.")


# ==================================================================
# PAGE: All Incoming
# ==================================================================
elif page == "All Incoming":
    page_header("All Incoming Cases", "Filter, search, and export every incoming case")
    df = load_incoming()
    if df.empty:
        st.info("No incoming cases yet.")
    else:
        f = st.columns(4)
        statuses = df["status"].dropna().unique().tolist() if "status" in df else []
        decisions = df["decision"].dropna().unique().tolist() if "decision" in df else []
        doc_types = df["document_type"].dropna().unique().tolist() if "document_type" in df else []
        s_sel = f[0].multiselect("Status", statuses, default=statuses)
        d_sel = f[1].multiselect("Decision", decisions, default=decisions)
        t_sel = f[2].multiselect("Document type", doc_types, default=doc_types)
        search = f[3].text_input("Search case ID / owner")

        view = df.copy()
        if s_sel and "status" in view:
            view = view[view["status"].isin(s_sel)]
        if d_sel and "decision" in view:
            view = view[view["decision"].isin(d_sel)]
        if t_sel and "document_type" in view:
            view = view[view["document_type"].isin(t_sel)]
        if st.checkbox("Flagged only") and "needs_review" in view:
            view = view[view["needs_review"] == 1]
        if search:
            mask = pd.Series(False, index=view.index)
            for col in ("case_id", "owner_name"):
                if col in view:
                    mask = mask | view[col].astype(str).str.contains(search, case=False, na=False)
            view = view[mask]

        st.caption(f"{len(view)} case(s)")
        cols = ["case_id", "document_type", "owner_name", "decision", "reason_code",
                "flag_reason", "needs_review", "processed_at", "validated_by"]
        present = [c for c in cols if c in view.columns]
        st.dataframe(
            view[present], hide_index=True, use_container_width=True,
            column_config={
                "needs_review": st.column_config.CheckboxColumn("Flagged"),
                "processed_at": st.column_config.DatetimeColumn("Processed at"),
            },
        )
        st.download_button("Download CSV",
                           view.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"incoming_{datetime.now():%Y%m%d}.csv", mime="text/csv")


# ==================================================================
# PAGE: Historical
# ==================================================================
elif page == "Historical":
    page_header("Historical Cases", "Read-only browse of the validated knowledge base")
    df = load_historical()
    if df.empty:
        st.info("No historical cases. Run scripts/seed_db.py.")
    else:
        m = st.columns(3)
        m[0].metric("Total", len(df))
        m[1].metric("Index version", (health or {}).get("active_version", "—"))
        if "decision" in df:
            m[2].metric("Accepted", int((df["decision"] == "Accepted").sum()))

        st.write("")
        col_a, col_b = st.columns(2)
        with col_a:
            with st.container(border=True):
                st.markdown("**By city**")
                if "city" in df and df["city"].notna().any():
                    cc = df["city"].value_counts().head(12).reset_index()
                    cc.columns = ["city", "count"]
                    chart_hbar(cc, "city", "count")
        with col_b:
            with st.container(border=True):
                st.markdown("**By property type**")
                if "property_type" in df and df["property_type"].notna().any():
                    pc = df["property_type"].value_counts().reset_index()
                    pc.columns = ["property_type", "count"]
                    chart_donut(pc, "property_type", "count")

        st.write("")
        f = st.columns(3)
        doc_types = df["document_type"].dropna().unique().tolist() if "document_type" in df else []
        cities = df["city"].dropna().unique().tolist() if "city" in df else []
        decisions = df["decision"].dropna().unique().tolist() if "decision" in df else []
        t_sel = f[0].multiselect("Document type", doc_types, default=doc_types)
        c_sel = f[1].multiselect("City", cities, default=cities)
        d_sel = f[2].multiselect("Decision", decisions, default=decisions)

        view = df.copy()
        if t_sel and "document_type" in view:
            view = view[view["document_type"].isin(t_sel)]
        if c_sel and "city" in view:
            view = view[view["city"].isin(c_sel)]
        if d_sel and "decision" in view:
            view = view[view["decision"].isin(d_sel)]

        st.caption(f"{len(view)} case(s) — read-only")
        st.dataframe(view, hide_index=True, use_container_width=True)


# ==================================================================
# PAGE: Calibration & Indexing
# ==================================================================
elif page == "Calibration":
    page_header("Calibration & Indexing", "Monitor novelty threshold and rebuild the vector index")
    df = load_incoming()

    threshold = (calib or {}).get("threshold")
    m = st.columns(4)
    m[0].metric("Novelty threshold", f"{threshold:.4f}" if threshold else "—")
    m[1].metric("Percentile", (calib or {}).get("percentile", cfg["novelty"]["threshold_percentile"]))
    if not df.empty and "needs_review" in df and "status" in df:
        done = int((df["status"] == "done").sum())
        flagged = int((df["needs_review"] == 1).sum())
        m[2].metric("Flag rate", f"{(flagged/done):.0%}" if done else "—")
        m[3].metric("Processed", done)

    st.write("")
    with st.container(border=True):
        st.markdown("**Novelty distance distribution**")
        if not df.empty and "nn_distance" in df and df["nn_distance"].notna().any():
            chart_hist(df["nn_distance"], threshold, "Mean NN distance")
            st.caption("Amber line = threshold. Cases to its right are flagged as novel.")
        else:
            st.caption("No distance data yet — process some cases first.")

    st.write("")
    with st.container(border=True):
        st.markdown("**Reindex**")
        st.caption("Auto-reindex happens automatically when validated cases are added via the Review Queue.")
        confirm = st.checkbox("Confirm manual reindex")
        if st.button("Reindex now", disabled=not confirm, use_container_width=True):
            with st.spinner("Rebuilding vector index…"):
                res, err = api_post("/reindex")
            if err:
                st.error(f"Reindex failed: {err}")
            else:
                st.success(f"Reindex complete. Version: {res.get('version','—')}")
                st.json(res)


# ==================================================================
# PAGE: Rules reference
# ==================================================================
elif page == "Rules":
    page_header("Acceptance Rules", "10 deterministic rules — authoritative, the LLM only explains, never decides")
    st.info("These rules run first on every case. The AI explanation is generated after the rule decision is already made.")
    rules_df = pd.DataFrame(RULES, columns=["Reason code", "Rule", "Decision"])
    st.dataframe(rules_df, hide_index=True, use_container_width=True)
