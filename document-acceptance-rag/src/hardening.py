"""
Hardening loop — logs every adjudication judgment and promotes recurring
patterns to learned rules once the promote_after threshold is reached.

Pattern signature = (document_type, property_type, verdict).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ADJUDICATION_LOG_DDL = """
CREATE TABLE IF NOT EXISTS adjudication_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         TEXT,
    source          TEXT,
    verdict         TEXT,
    confidence      REAL,
    reason          TEXT,
    rationale_en    TEXT,
    criteria_scores TEXT,
    document_type   TEXT,
    property_type   TEXT,
    logged_at       TEXT
)
"""

LEARNED_RULES_DDL = """
CREATE TABLE IF NOT EXISTS learned_rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_type   TEXT,
    property_type   TEXT,
    verdict         TEXT,
    sample_count    INTEGER,
    promoted_at     TEXT,
    active          INTEGER DEFAULT 1
)
"""


class HardeningLoop:
    def __init__(self, db_client, promote_after: int = 3):
        self.db = db_client
        self.promote_after = promote_after
        self._ensure_tables()

    def _ensure_tables(self):
        with self.db._conn() as con:
            con.execute(ADJUDICATION_LOG_DDL)
            con.execute(LEARNED_RULES_DDL)

    def record(self, case: Dict[str, Any], result) -> None:
        """Log one adjudication result and check if promotion is due."""
        with self.db._conn() as con:
            con.execute(
                """INSERT INTO adjudication_log
                   (case_id, source, verdict, confidence, reason, rationale_en,
                    criteria_scores, document_type, property_type, logged_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [
                    case.get("case_id"),
                    result.source,
                    result.verdict,
                    result.confidence,
                    result.reason,
                    result.rationale_en,
                    json.dumps(result.criteria_scores),
                    case.get("document_type"),
                    case.get("property_type"),
                    datetime.utcnow().isoformat(),
                ],
            )

        self._maybe_promote(case.get("document_type"), case.get("property_type"), result.verdict)

    def _maybe_promote(self, doc_type: str, prop_type: str, verdict: str) -> None:
        if verdict == "ESCALATE":
            return
        with self.db._conn() as con:
            # Count consistent high-confidence verdicts for this signature
            row = con.execute(
                """SELECT COUNT(*) FROM adjudication_log
                   WHERE document_type=? AND property_type=? AND verdict=?
                     AND source='llm' AND confidence >= 0.85""",
                [doc_type, prop_type, verdict],
            ).fetchone()
            count = row[0] if row else 0

            if count < self.promote_after:
                return

            # Check not already promoted
            exists = con.execute(
                """SELECT 1 FROM learned_rules
                   WHERE document_type=? AND property_type=? AND verdict=? AND active=1""",
                [doc_type, prop_type, verdict],
            ).fetchone()
            if exists:
                return

            con.execute(
                """INSERT INTO learned_rules
                   (document_type, property_type, verdict, sample_count, promoted_at, active)
                   VALUES (?,?,?,?,?,1)""",
                [doc_type, prop_type, verdict, count, datetime.utcnow().isoformat()],
            )
            logger.info("Hardening: promoted (%s, %s) → %s after %d judgments",
                        doc_type, prop_type, verdict, count)

    def check_learned(self, case: Dict[str, Any]):
        """Return a learned rule verdict for this case, or None if no rule applies."""
        with self.db._conn() as con:
            row = con.execute(
                """SELECT verdict FROM learned_rules
                   WHERE document_type=? AND property_type=? AND active=1
                   LIMIT 1""",
                [case.get("document_type"), case.get("property_type")],
            ).fetchone()
        return row[0] if row else None

    def list_learned_rules(self) -> List[Dict]:
        with self.db._conn() as con:
            rows = con.execute(
                "SELECT * FROM learned_rules ORDER BY promoted_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
