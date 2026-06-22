# Document Acceptance RAG — Implementation Plan

## What this system does

Novelty detection with a human-in-the-loop growth loop:

> Embed an incoming case → measure distance to nearest historical neighbours → if unlike anything seen before, **flag for human** → if human validates, **append to historical set and reindex** → "known" region grows, future flagging tightens.

Three invariants govern the design:
1. **Decisions are deterministic.** The rule engine decides accept/reject. Authoritative and auditable.
2. **Flagging is statistical.** Novelty = measured embedding distance, not a model's self-report.
3. **Growth is human-gated.** A case enters the historical dataset only after a human validates it.

The LLM (Qwen) does exactly one thing: produce bilingual explanations. It does not decide and does not flag.

---

## Architecture

```
flowchart LR
  subgraph sheets [GoogleSheets]
    HistTab[Historical_Cases]
    InTab[Incoming_Cases]
    RulesTab[Acceptance_Rules]
  end

  subgraph onprem [OnPremBackend]
    Poller[SheetPoller]
    Rules[RuleEngine]
    Embed[EmbeddingService_bge_m3]
    Chroma[(ChromaDB_versioned)]
    Novelty[NoveltyDetector]
    Qwen[Qwen_Ollama_explainer]
    Review[ReviewFlagger]
    Growth[GrowthLoop_humanGated]
  end

  HistTab -->|validated only| Embed
  Embed --> Chroma
  Poller -->|new row| Rules
  Rules -->|decision + reason_code| Novelty
  Chroma -->|nearest-neighbour distance| Novelty
  Novelty -->|decision + flag| Qwen
  Qwen -->|bilingual explanation| Review
  Review -->|write columns| InTab
  RulesTab --> Rules
  InTab -->|human validates flagged case| Growth
  Growth -->|append + reindex| HistTab
```

**Per-case data flow:**
1. Poller detects row with empty recommendation columns.
2. **Rule engine** evaluates deterministic criteria → decision + `reason_code`.
3. **No-rule-fired gate** — if no rule matched and not a clean accept, flag immediately.
4. **Novelty detector** embeds case attributes, finds k nearest historical neighbours, flags if mean distance exceeds calibrated percentile threshold.
5. **Qwen** produces bilingual explanation (and short reviewer note for flagged cases).
6. Backend writes decision + explanation + `needs_review` + provenance columns back to Sheets.
7. Human reviews flagged rows; only on human validation is case appended to `Historical_Cases` and reindex triggered.

---

## Two Gates

| Gate | Question | Opened by | Never opened by |
|------|----------|-----------|-----------------|
| **Flag gate** | Does a human need to look at this? | "No rule fired" OR embedding-distance novelty | anything else |
| **Grow gate** | Does this case enter the historical dataset? | **Human validation only** | rule engine, LLM, low distance, any judge |

---

## Data Schema

### Tab: `Historical_Cases`

| Column | Arabic header | Type | Notes |
|--------|---------------|------|-------|
| `case_id` | معرف الحالة | string | HIST-001 … |
| `document_type` | نوع المستند | enum | صك ملكية، عقد إيجار، توكيل |
| `owner_name` | اسم المالك | string | |
| `owner_id` | رقم هوية المالك | string | |
| `property_id` | رقم العقار | string | |
| `property_type` | نوع العقار | enum | شقة، فيلا، أرض |
| `area_sqm` | المساحة | number | |
| `address` | العنوان | string | |
| `city` | المدينة | string | |
| `notarized` | موثق | boolean | نعم/لا |
| `owner_signature` | توقيع المالك | boolean | |
| `liens_present` | رهون/قيود | boolean | |
| `registration_date` | تاريخ التسجيل | date | |
| `decision` | القرار | enum | Accepted / Rejected |
| `reason_code` | رمز السبب | enum | see acceptance rules |
| `recommendation_en` | التوصية EN | text | bilingual |
| `recommendation_ar` | التوصية AR | text | |
| `source` | المصدر | enum | `validated` only |
| `added_at` | تاريخ الإضافة | date | |
| `index_version` | إصدار الفهرس | string | reindex snapshot |

### Tab: `Incoming_Cases`

Same attribute columns plus output columns:

| Column | Purpose |
|--------|---------|
| `decision` | Accepted / Rejected |
| `reason_code` | Machine-readable reason |
| `recommendation_en` | English explanation |
| `recommendation_ar` | Arabic explanation |
| `retrieved_case_ids` | Comma-sep HIST IDs (nearest neighbours) |
| `nn_distance` | Mean distance to k nearest neighbours |
| `flag_reason` | `none` / `no_rule_fired` / `novel_pattern` |
| `needs_review` | TRUE if either flag gate fired |
| `validated_by` | Reviewer ID (set by human) |
| `processed_at` | ISO timestamp |
| `status` | pending / processing / done / error |

### Acceptance Rules (10 reason codes)

| reason_code | Rule | Decision |
|-------------|------|----------|
| `MEETS_CRITERIA` | All required fields present and all checks pass | Accepted |
| `MISSING_OWNER_NAME` | `owner_name` empty | Rejected |
| `MISSING_PROPERTY_ID` | `property_id` empty | Rejected |
| `MISSING_OWNER_SIGNATURE` | `owner_signature = false` | Rejected |
| `NOT_NOTARIZED` | `notarized = false` for صك ملكية | Rejected |
| `LIEN_PRESENT` | `liens_present = true` | Rejected |
| `INCOMPLETE_ADDRESS` | `address` or `city` empty | Rejected |
| `INVALID_AREA` | `area_sqm` missing or ≤ 0 | Rejected |
| `OWNER_ID_MISMATCH` | `owner_id` non-numeric or wrong length | Rejected |
| `EXPIRED_REGISTRATION` | `registration_date` older than configurable window | Rejected |

---

## Recommendation JSON Template

```json
{
  "decision": "Rejected",
  "decision_ar": "مرفوض",
  "reason_code": "MISSING_OWNER_SIGNATURE",
  "recommendation_en": "The document lacks the owner's signature, so it fails validation.",
  "recommendation_ar": "يفتقر المستند إلى توقيع المالك، مما يجعله غير صالح للتحقق."
}
```

---

## Project Structure

```
document-acceptance-rag/
├── config.yaml
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── generate_synthetic_cases.py
│   └── seed_chroma.py
├── src/
│   ├── main.py              # FastAPI + background poller
│   ├── sheets_client.py     # Google Sheets API read/write
│   ├── rule_engine.py       # deterministic decision (authoritative)
│   ├── embeddings.py        # bge-m3 multilingual
│   ├── vector_store.py      # ChromaDB wrapper, versioned collections
│   ├── novelty.py           # k-NN distance + percentile calibration
│   ├── llm.py               # Ollama Qwen client (explanation only)
│   ├── recommender.py       # rule → novelty → explain → write-back
│   ├── review_flagger.py    # combines no-rule-fired + novelty signals
│   └── growth_loop.py       # human-gated append + reindex + versioning
└── prompts/
    └── recommendation.txt
```

### Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Decision | Deterministic rule engine | Authoritative, auditable, no hallucination |
| Embeddings | `BAAI/bge-m3` | Strong noisy-Arabic similarity, longer sequences |
| Vector DB | ChromaDB (local, versioned) | Simple, no external service, rollback support |
| LLM | Qwen 3 via Ollama (`qwen3:8b`) | On-prem, strong Arabic, explanation only |
| API | FastAPI | `/process`, `/reindex`, `/health`, `/calibration` |
| Sheets | Google Sheets API v4 + service account | Backend-only access |

---

## Novelty Detection Details

**Embed attributes only** — never `decision` or `reason_code`. An incoming case has no decision yet; including labels causes distribution mismatch.

**k-NN mean distance** with k=3–5 (not k=1) for robustness against synthetic near-duplicates.

**Adaptive threshold** (never hardcoded):
1. For every historical case, compute mean distance to its k nearest neighbours within the set.
2. Set novelty threshold at the 95th percentile of that distribution (configurable).
3. Recalibrate at every reindex over validated data only.
4. Expose via `GET /calibration`.

**Two senses of novelty:**
- **Novel reason** — no rule fired and not a clean accept. Caught deterministically.
- **Novel pattern** — known reason code fired but attribute combination unlike anything historical. Caught by distance detector.

---

## Implementation Phases

### Phase 1 — Foundation (Week 1)
- [x] `plan.md` — this document
- [ ] Project scaffold (FastAPI, config.yaml, requirements.txt, .gitignore)
- [ ] `rule_engine.py` with all 10 reason codes
- [ ] `scripts/generate_synthetic_cases.py` — 500 diverse Arabic cases
- [ ] Google Sheets template + `sheets_client.py`

### Phase 2 — Novelty Detection (Week 1–2)
- [ ] `embeddings.py` with bge-m3
- [ ] `vector_store.py` — ChromaDB versioned collections
- [ ] `scripts/seed_chroma.py` — seed from Historical_Cases CSV
- [ ] `novelty.py` — k-NN mean distance + percentile calibration
- [ ] Spot-check retrieval quality, inspect distance distribution

### Phase 3 — Explanation + Orchestration (Week 2)
- [ ] `llm.py` — Ollama Qwen client, bilingual JSON output
- [ ] `prompts/recommendation.txt`
- [ ] `recommender.py` — rule → novelty → explain → write-back
- [ ] `review_flagger.py` — combines both flag signals

### Phase 4 — Growth Loop + Pilot (Week 2–3)
- [ ] `growth_loop.py` — human-gated append, versioning, reindex
- [ ] `main.py` — background poller + all endpoints
- [ ] Process 20–50 test incoming rows; calibrate percentile
- [ ] Operator guide for handling `needs_review`, validating, growth loop

---

## Growth-Loop Guardrails

- **Validated-only.** Never auto-append system's own confident accepts.
- **Versioned index.** Each reindex is a timestamped Chroma snapshot. Roll back on bad batches.
- **Flag-rate monitoring.** Log novel-flag rate per reindex. Spike or collapse signals miscalibration.

---

## Expected Behaviour at Launch

Front-loaded false-flag rate is **expected**. Real cases look novel simply because the synthetic generator didn't cover their natural variety. This is the safe failure direction: over-flagging routes to humans, who validate and grow the set, which lowers future flags. The loop self-corrects.

---

## Prerequisites (Operator)

- Windows/Linux, 16 GB+ RAM (GPU recommended for `qwen3:8b` latency)
- [Ollama](https://ollama.com) installed + `qwen3:8b` pulled
- Python 3.11+
- Google Cloud project with Sheets API enabled + service account JSON at `credentials/google-service-account.json`
