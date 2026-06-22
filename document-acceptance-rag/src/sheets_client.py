"""
Google Sheets API v4 client.

Reads Historical_Cases, Incoming_Cases, Acceptance_Rules.
Writes recommendation + provenance columns to Incoming_Cases.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Column headers — must match the sheet exactly
INCOMING_STATUS_COL = "status"
INCOMING_VALIDATED_BY_COL = "validated_by"


class SheetsClient:
    def __init__(self, spreadsheet_id: str, credentials_path: str):
        self.spreadsheet_id = spreadsheet_id
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=SCOPES
        )
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)
        self._sheet = self.service.spreadsheets()

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def _read_tab(self, tab: str) -> List[Dict[str, Any]]:
        result = self._sheet.values().get(
            spreadsheetId=self.spreadsheet_id, range=tab
        ).execute()
        rows = result.get("values", [])
        if not rows:
            return []
        headers = rows[0]
        return [
            {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
            for row in rows[1:]
        ]

    def read_historical(self, tab: str) -> List[Dict[str, Any]]:
        return self._read_tab(tab)

    def read_incoming(self, tab: str) -> List[Dict[str, Any]]:
        return self._read_tab(tab)

    def read_rules(self, tab: str) -> List[Dict[str, Any]]:
        return self._read_tab(tab)

    def get_pending_rows(self, tab: str) -> List[Dict[str, Any]]:
        rows = self.read_incoming(tab)
        return [
            r for r in rows
            if r.get(INCOMING_STATUS_COL, "").lower() in ("pending", "")
            or not r.get("decision", "").strip()
        ]

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _get_headers(self, tab: str) -> List[str]:
        result = self._sheet.values().get(
            spreadsheetId=self.spreadsheet_id, range=f"{tab}!1:1"
        ).execute()
        rows = result.get("values", [])
        return rows[0] if rows else []

    def _find_row_index(self, tab: str, case_id: str, id_col: str = "case_id") -> Optional[int]:
        """Returns 1-based row index in the sheet (row 1 = headers)."""
        rows = self._read_tab(tab)
        for i, row in enumerate(rows):
            if row.get(id_col) == case_id:
                return i + 2  # +1 for header, +1 for 1-based indexing
        return None

    def write_recommendation(
        self,
        tab: str,
        case_id: str,
        updates: Dict[str, Any],
    ):
        """Update specific columns for a case row identified by case_id."""
        headers = self._get_headers(tab)
        row_index = self._find_row_index(tab, case_id)
        if row_index is None:
            raise ValueError(f"case_id {case_id!r} not found in tab {tab!r}")

        for col_name, value in updates.items():
            if col_name not in headers:
                continue
            col_index = headers.index(col_name)
            col_letter = _col_letter(col_index)
            cell_range = f"{tab}!{col_letter}{row_index}"
            self._sheet.values().update(
                spreadsheetId=self.spreadsheet_id,
                range=cell_range,
                valueInputOption="RAW",
                body={"values": [[str(value) if value is not None else ""]]},
            ).execute()

    def append_historical(self, tab: str, row: Dict[str, Any]):
        """Append a validated case to the Historical_Cases tab."""
        headers = self._get_headers(tab)
        values = [str(row.get(h, "") or "") for h in headers]
        self._sheet.values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A:A",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": [values]},
        ).execute()


def _col_letter(index: int) -> str:
    """Convert 0-based column index to spreadsheet letter (A, B, …, Z, AA, …)."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
