"""
Ollama Qwen client — explanation only.

Qwen produces bilingual JSON. It does NOT decide and does NOT flag.
The rule engine's decision and reason_code are passed verbatim; Qwen
explains them in free text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class Explanation:
    decision: str
    decision_ar: str
    reason_code: str
    recommendation_en: str
    recommendation_ar: str
    reviewer_note_en: Optional[str] = None
    reviewer_note_ar: Optional[str] = None


class QwenClient:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:8b", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def explain(
        self,
        case_dict: dict,
        decision: str,
        decision_ar: str,
        reason_code: str,
        needs_review: bool,
        flag_reason: str,
        retrieved_ids: list[str],
        prompt_template: str,
    ) -> Explanation:
        if needs_review:
            reviewer_note_instruction = (
                ',\n  "reviewer_note_en": "<brief note for the human reviewer in English>",'
                '\n  "reviewer_note_ar": "<brief note for the human reviewer in Arabic>"'
            )
            flagged_instruction = (
                "5. Because needs_review is true, add reviewer_note_en and reviewer_note_ar "
                "to explain what the reviewer should check."
            )
        else:
            reviewer_note_instruction = ""
            flagged_instruction = ""

        prompt = prompt_template.format(
            case_json=json.dumps(case_dict, ensure_ascii=False, indent=2),
            decision=decision,
            decision_ar=decision_ar,
            reason_code=reason_code,
            needs_review=needs_review,
            flag_reason=flag_reason,
            retrieved_ids=", ".join(retrieved_ids) if retrieved_ids else "none",
            reviewer_note_instruction=reviewer_note_instruction,
            flagged_instruction=flagged_instruction,
        )

        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False},
            timeout=self.timeout,
        )
        response.raise_for_status()
        raw = response.json()["response"].strip()

        return self._parse(raw, decision, decision_ar, reason_code)

    def _parse(self, raw: str, decision: str, decision_ar: str, reason_code: str) -> Explanation:
        # Extract JSON block from response
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return self._fallback(decision, decision_ar, reason_code)
        try:
            data = json.loads(match.group())
            return Explanation(
                decision=data.get("decision", decision),
                decision_ar=data.get("decision_ar", decision_ar),
                reason_code=data.get("reason_code", reason_code),
                recommendation_en=data.get("recommendation_en", ""),
                recommendation_ar=data.get("recommendation_ar", ""),
                reviewer_note_en=data.get("reviewer_note_en"),
                reviewer_note_ar=data.get("reviewer_note_ar"),
            )
        except (json.JSONDecodeError, KeyError):
            return self._fallback(decision, decision_ar, reason_code)

    @staticmethod
    def _fallback(decision: str, decision_ar: str, reason_code: str) -> Explanation:
        return Explanation(
            decision=decision,
            decision_ar=decision_ar,
            reason_code=reason_code,
            recommendation_en=f"Decision: {decision}. Reason: {reason_code}.",
            recommendation_ar=f"القرار: {decision_ar}. السبب: {reason_code}.",
        )
