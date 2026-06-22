"""
End-to-end orchestrator: rule → novelty → explain → write-back.

Order of operations (per case):
1. Parse input row.
2. Rule engine → decision + reason_code.
3. Novelty detector → nn_distance + is_novel_pattern.
4. Review flagger → needs_review + flag_reason.
5. Qwen → bilingual explanation.
6. Write all output columns back to incoming_cases.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

from .db_client import DBClient
from .embeddings import EmbeddingService
from .llm import QwenClient
from .novelty import NoveltyDetector
from .review_flagger import evaluate_flags
from .rule_engine import Case, evaluate as rule_evaluate
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

DECISION_AR = {
    "Accepted": "مقبول",
    "Rejected": "مرفوض",
}


def _parse_bool(val: Any) -> bool:
    if isinstance(val, (bool, int)):
        return bool(val)
    s = str(val).strip().lower()
    return s in ("true", "1", "yes", "نعم", "صح")


def _parse_date(val: Any) -> Optional[date]:
    if not val or str(val).strip() == "":
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(val).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(val: Any) -> Optional[float]:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def row_to_case(row: Dict[str, Any]) -> Case:
    return Case(
        case_id=row.get("case_id", ""),
        document_type=row.get("document_type", ""),
        owner_name=row.get("owner_name", ""),
        owner_id=row.get("owner_id", ""),
        property_id=row.get("property_id", ""),
        property_type=row.get("property_type", ""),
        area_sqm=_parse_float(row.get("area_sqm")),
        address=row.get("address", ""),
        city=row.get("city", ""),
        notarized=_parse_bool(row.get("notarized", False)),
        owner_signature=_parse_bool(row.get("owner_signature", False)),
        liens_present=_parse_bool(row.get("liens_present", False)),
        registration_date=_parse_date(row.get("registration_date")),
    )


class Recommender:
    def __init__(
        self,
        db: DBClient,
        embedding_service: EmbeddingService,
        vector_store: VectorStore,
        novelty_detector: NoveltyDetector,
        qwen: QwenClient,
        prompt_template: str,
        max_registration_age_years: int = 10,
    ):
        self.db = db
        self.embeddings = embedding_service
        self.store = vector_store
        self.novelty = novelty_detector
        self.qwen = qwen
        self.prompt_template = prompt_template
        self.max_reg_age = max_registration_age_years

    def process_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        case_id = row.get("case_id", "UNKNOWN")

        self.db.write_recommendation(case_id, {"status": "processing"})

        try:
            case = row_to_case(row)

            rule_result = rule_evaluate(case, self.max_reg_age)
            decision = rule_result.decision.value
            reason_code = rule_result.reason_code.value
            decision_ar = DECISION_AR.get(decision, decision)

            novelty_result = self.novelty.check(row)

            flag_result = evaluate_flags(
                rule_fired=rule_result.rule_fired,
                decision=decision,
                is_novel_pattern=novelty_result.is_novel,
            )

            explanation = self.qwen.explain(
                case_dict=row,
                decision=decision,
                decision_ar=decision_ar,
                reason_code=reason_code,
                needs_review=flag_result.needs_review,
                flag_reason=flag_result.flag_reason.value,
                retrieved_ids=novelty_result.retrieved_ids,
                prompt_template=self.prompt_template,
            )

            output = {
                "decision": decision,
                "reason_code": reason_code,
                "recommendation_en": explanation.recommendation_en,
                "recommendation_ar": explanation.recommendation_ar,
                "retrieved_case_ids": ", ".join(novelty_result.retrieved_ids),
                "nn_distance": round(novelty_result.nn_distance, 4),
                "flag_reason": flag_result.flag_reason.value,
                "needs_review": 1 if flag_result.needs_review else 0,
                "processed_at": datetime.utcnow().isoformat(),
                "status": "done",
            }

            self.db.write_recommendation(case_id, output)
            logger.info("Processed %s → %s (%s)", case_id, decision, reason_code)
            return output

        except Exception as e:
            logger.error("Error processing %s: %s", case_id, e, exc_info=True)
            self.db.write_recommendation(
                case_id,
                {"status": "error", "processed_at": datetime.utcnow().isoformat()},
            )
            raise
