"""
Deterministic rule engine — the authoritative decision gate.

Rules are evaluated in priority order. The first matching rejection rule wins.
If all checks pass, the case is accepted with MEETS_CRITERIA.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"


class ReasonCode(str, Enum):
    MEETS_CRITERIA = "MEETS_CRITERIA"
    MISSING_OWNER_NAME = "MISSING_OWNER_NAME"
    MISSING_PROPERTY_ID = "MISSING_PROPERTY_ID"
    MISSING_OWNER_SIGNATURE = "MISSING_OWNER_SIGNATURE"
    NOT_NOTARIZED = "NOT_NOTARIZED"
    LIEN_PRESENT = "LIEN_PRESENT"
    INCOMPLETE_ADDRESS = "INCOMPLETE_ADDRESS"
    INVALID_AREA = "INVALID_AREA"
    OWNER_ID_MISMATCH = "OWNER_ID_MISMATCH"
    EXPIRED_REGISTRATION = "EXPIRED_REGISTRATION"


# Document types that require notarization
NOTARIZED_REQUIRED_TYPES = {"صك ملكية"}

# Saudi national/resident ID: exactly 10 digits starting with 1 (national) or 2 (resident)
OWNER_ID_PATTERN = re.compile(r'^[12]\d{9}$')


@dataclass
class Case:
    case_id: str
    document_type: str
    owner_name: str
    owner_id: str
    property_id: str
    property_type: str
    area_sqm: Optional[float]
    address: str
    city: str
    notarized: bool
    owner_signature: bool
    liens_present: bool
    registration_date: Optional[date]


@dataclass
class RuleResult:
    decision: Decision
    reason_code: ReasonCode
    rule_fired: bool  # False means no rejection rule matched (clean accept)


def evaluate(case: Case, max_registration_age_years: int = 10) -> RuleResult:
    """Evaluate deterministic rules in priority order. First match wins."""

    if not (case.owner_name or "").strip():
        return RuleResult(Decision.REJECTED, ReasonCode.MISSING_OWNER_NAME, True)

    if not (case.property_id or "").strip():
        return RuleResult(Decision.REJECTED, ReasonCode.MISSING_PROPERTY_ID, True)

    if not case.owner_signature:
        return RuleResult(Decision.REJECTED, ReasonCode.MISSING_OWNER_SIGNATURE, True)

    if case.document_type in NOTARIZED_REQUIRED_TYPES and not case.notarized:
        return RuleResult(Decision.REJECTED, ReasonCode.NOT_NOTARIZED, True)

    if case.liens_present:
        return RuleResult(Decision.REJECTED, ReasonCode.LIEN_PRESENT, True)

    if not (case.address or "").strip() or not (case.city or "").strip():
        return RuleResult(Decision.REJECTED, ReasonCode.INCOMPLETE_ADDRESS, True)

    if case.area_sqm is None or case.area_sqm <= 0:
        return RuleResult(Decision.REJECTED, ReasonCode.INVALID_AREA, True)

    owner_id_str = (case.owner_id or "").strip()
    if not OWNER_ID_PATTERN.match(owner_id_str):
        return RuleResult(Decision.REJECTED, ReasonCode.OWNER_ID_MISMATCH, True)

    if case.registration_date is not None:
        today = date.today()
        age_years = (today - case.registration_date).days / 365.25
        if age_years > max_registration_age_years:
            return RuleResult(Decision.REJECTED, ReasonCode.EXPIRED_REGISTRATION, True)

    return RuleResult(Decision.ACCEPTED, ReasonCode.MEETS_CRITERIA, True)
