"""
SQLite database client — replaces Google Sheets.

Two tables:
  historical_cases  — validated seed + growth-loop appends
  incoming_cases    — queue of cases to process + output columns
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH_DEFAULT = "data/cases.db"

HISTORICAL_DDL = """
CREATE TABLE IF NOT EXISTS historical_cases (
    case_id            TEXT PRIMARY KEY,
    document_type      TEXT,
    owner_name         TEXT,
    owner_id           TEXT,
    property_id        TEXT,
    property_type      TEXT,
    area_sqm           REAL,
    address            TEXT,
    city               TEXT,
    notarized          INTEGER,
    owner_signature    INTEGER,
    liens_present      INTEGER,
    registration_date  TEXT,
    decision           TEXT,
    reason_code        TEXT,
    recommendation_en  TEXT,
    recommendation_ar  TEXT,
    source             TEXT DEFAULT 'validated',
    added_at           TEXT,
    index_version      TEXT
)
"""

INCOMING_DDL = """
CREATE TABLE IF NOT EXISTS incoming_cases (
    case_id            TEXT PRIMARY KEY,
    document_type      TEXT,
    owner_name         TEXT,
    owner_id           TEXT,
    property_id        TEXT,
    property_type      TEXT,
    area_sqm           REAL,
    address            TEXT,
    city               TEXT,
    notarized          INTEGER,
    owner_signature    INTEGER,
    liens_present      INTEGER,
    registration_date  TEXT,
    -- output columns
    decision           TEXT,
    reason_code        TEXT,
    recommendation_en  TEXT,
    recommendation_ar  TEXT,
    retrieved_case_ids TEXT,
    nn_distance        REAL,
    flag_reason        TEXT,
    needs_review       INTEGER DEFAULT 0,
    validated_by       TEXT,
    processed_at       TEXT,
    status             TEXT DEFAULT 'pending'
)
"""


class DBClient:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _init_db(self):
        with self._conn() as con:
            con.execute(HISTORICAL_DDL)
            con.execute(INCOMING_DDL)
            for col, typ in [
                ("source_appended", "INTEGER DEFAULT 0"),
                ("adj_confidence", "REAL"),
            ]:
                try:
                    con.execute(f"ALTER TABLE incoming_cases ADD COLUMN {col} {typ}")
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Historical
    # ------------------------------------------------------------------

    def read_historical(self) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM historical_cases").fetchall()
        return [dict(r) for r in rows]

    def append_historical(self, row: Dict[str, Any]):
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        values = [row[c] for c in cols]
        with self._conn() as con:
            con.execute(
                f"INSERT OR REPLACE INTO historical_cases ({col_names}) VALUES ({placeholders})",
                values,
            )

    def seed_historical(self, rows: List[Dict[str, Any]]):
        """Bulk insert; skip duplicates."""
        for row in rows:
            self.append_historical(row)

    # ------------------------------------------------------------------
    # Incoming
    # ------------------------------------------------------------------

    def read_incoming(self) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM incoming_cases").fetchall()
        return [dict(r) for r in rows]

    def get_pending_rows(self) -> List[Dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM incoming_cases WHERE status = 'pending' OR decision IS NULL OR decision = ''"
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_incoming(self, row: Dict[str, Any]):
        """Insert or replace a full incoming row."""
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        col_names = ", ".join(cols)
        values = [row[c] for c in cols]
        with self._conn() as con:
            con.execute(
                f"INSERT OR REPLACE INTO incoming_cases ({col_names}) VALUES ({placeholders})",
                values,
            )

    def write_recommendation(self, case_id: str, updates: Dict[str, Any]):
        """Update specific output columns for a case."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [case_id]
        with self._conn() as con:
            con.execute(
                f"UPDATE incoming_cases SET {set_clause} WHERE case_id = ?",
                values,
            )

    def get_validated_rows(self) -> List[Dict[str, Any]]:
        """Rows that a human has validated (validated_by set, needs_review=1, status=done)."""
        with self._conn() as con:
            rows = con.execute(
                """SELECT * FROM incoming_cases
                   WHERE needs_review = 1
                     AND (validated_by IS NOT NULL AND validated_by != '')
                     AND status = 'done'
                     AND (source_appended IS NULL OR source_appended = 0)""",
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_appended(self, case_id: str):
        """Prevent re-appending after growth loop processes a validated row."""
        with self._conn() as con:
            # Add column if missing (idempotent migration)
            try:
                con.execute("ALTER TABLE incoming_cases ADD COLUMN source_appended INTEGER DEFAULT 0")
            except Exception:
                pass
            con.execute(
                "UPDATE incoming_cases SET source_appended = 1 WHERE case_id = ?",
                [case_id],
            )
