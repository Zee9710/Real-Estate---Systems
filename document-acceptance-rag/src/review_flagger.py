"""
Review flagger — combines the two flag signals.

Flag gate 1 (novel reason): no rule fired AND not a clean accept.
Flag gate 2 (novel pattern): embedding distance exceeds calibrated threshold.

The LLM does not open either gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FlagReason(str, Enum):
    NONE = "none"
    NO_RULE_FIRED = "no_rule_fired"
    NOVEL_PATTERN = "novel_pattern"


@dataclass
class FlagResult:
    needs_review: bool
    flag_reason: FlagReason


def evaluate_flags(
    rule_fired: bool,
    decision: str,
    is_novel_pattern: bool,
) -> FlagResult:
    """
    rule_fired: True if any deterministic rule matched (including MEETS_CRITERIA).
    decision:   'Accepted' or 'Rejected' from the rule engine.
    is_novel_pattern: True if novelty detector exceeded threshold.
    """
    # Gate 1: no rule fired AND it's not a clean accept
    if not rule_fired and decision != "Accepted":
        return FlagResult(needs_review=True, flag_reason=FlagReason.NO_RULE_FIRED)

    # Gate 2: attribute pattern is unlike anything historical
    if is_novel_pattern:
        return FlagResult(needs_review=True, flag_reason=FlagReason.NOVEL_PATTERN)

    return FlagResult(needs_review=False, flag_reason=FlagReason.NONE)
