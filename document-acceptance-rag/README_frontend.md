# Reviewer Console — Frontend

A bilingual (Arabic-primary) Streamlit console for the Document Acceptance system.

## What it does

Six pages, navigated from the sidebar:

| Page | Arabic | Purpose |
|------|--------|---------|
| Dashboard | لوحة التحكم | System status, decision/rejection charts, recent activity, flag-rate alert |
| Review Queue | المراجعة البشرية | Validate flagged cases — attributes (offending field highlighted), bilingual explanation, **nearest historical cases**, approve/reject-for-growth, override |
| Submit Case | إضافة حالة | Insert a case and show the **5 most similar historical cases** after processing |
| All Incoming | الحالات الواردة | Filter/search/export every incoming case |
| Historical | المجموعة التاريخية | Read-only browse of the validated knowledge base, with charts |
| Calibration | المعايرة والفهرسة | Novelty threshold, **distance histogram with the threshold line**, reindex control |
| Rules | قواعد القبول | Read-only reference of the 10 authoritative rules |

## Design choices

- **Pragmatic hybrid data flow:** reads come straight from SQLite (every page works even if the API is down); only compute actions (process a case, reindex) call the FastAPI service. The offline banner appears automatically when `/health` is unreachable.
- **5 similar cases:** the novelty detector already stores the `k` nearest historical case IDs (nearest-first) on each processed case. The Submit and Review pages look those IDs up in the historical set and render them as cards, so the reviewer can judge "does this case actually look like its neighbours?".
- **Charts:** plotly when installed, automatically falling back to altair, then native Streamlit charts — a missing plotly install can never crash a page.
- **Reviewer columns** (`reviewed`, `approved_for_growth`, `reviewer_notes`, `override_decision`, `override_reason`) are added with an idempotent migration inside the UI, so `db_client.py` is never modified.

## Setup

```bash
pip install -r requirements.txt        # includes plotly (optional but recommended)
```

`plotly` is optional. If your environment can't install it, the app still runs with altair charts.

## Run

The backend (for processing/reindex) and the UI run separately.

```bash
# Terminal 1 — backend
uvicorn src.main:app --reload

# Terminal 2 — UI
streamlit run src/reviewer_ui.py
```

Open http://localhost:8501.

## Configuration

`frontend_config.yaml`:

```yaml
backend_url: "http://localhost:8000"
display:
  neighbours_k: 5      # how many similar cases to show
  flag_rate_high: 0.80 # dashboard warns above this
  flag_rate_low: 0.05  # dashboard warns below this
```

The backend URL can also be overridden with the `BACKEND_URL` environment variable.

## Notes / current limitations

- Per-version reindex history and per-neighbour distances are not stored by the
  backend yet, so the calibration page plots the live distribution of processed
  cases' mean distances against the current threshold (the key diagnostic) rather
  than a per-version trend.
- Enter your **Reviewer ID** once in the sidebar; it persists across pages for the session.
