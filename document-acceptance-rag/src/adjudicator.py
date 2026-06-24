"""
Adjudicator — runs on novel cases before human escalation.

Step 1: bounds check (deterministic, no LLM).
Step 2: LLM judge against rubric criteria → verdict + confidence.

Returns AdjudicationResult. Caller decides what to do with it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml


@dataclass
class AdjudicationResult:
    source: str          # "bounds" | "llm" | "escalate"
    verdict: str         # "ACCEPT" | "REJECT" | "ESCALATE"
    confidence: float    # 0..1
    reason: str          # human-readable
    rationale_en: str
    rationale_ar: str
    criteria_scores: List[Dict] = field(default_factory=list)
    bound_violated: Optional[str] = None


class Adjudicator:
    def __init__(self, config: Dict[str, Any], ollama_base: str, model: str, timeout: int):
        self.cfg = config.get("adjudication", {})
        self.hardening_cfg = config.get("hardening", {})
        self.enabled = self.cfg.get("enabled", False)
        self.accept_gate = self.cfg.get("auto_accept_confidence", 0.85)
        self.reject_gate = self.cfg.get("auto_reject_confidence", 0.85)
        self.ollama_base = ollama_base.rstrip("/")
        self.model = model
        self.timeout = timeout

        rubric_path = self.cfg.get("rubric_path", "rubric.yaml")
        self.rubric = yaml.safe_load(Path(rubric_path).read_text(encoding="utf-8"))
        self.prompt_template = Path("prompts/adjudicator.txt").read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    def adjudicate(self, case: Dict[str, Any], neighbours: List[Dict]) -> AdjudicationResult:
        if not self.enabled:
            return AdjudicationResult("escalate", "ESCALATE", 0.0,
                                      "Adjudicator disabled", "", "")

        # Step 1 — deterministic bounds
        bound_result = self._check_bounds(case)
        if bound_result:
            return bound_result

        # Step 2 — LLM judge
        return self._llm_judge(case, neighbours)

    # ------------------------------------------------------------------
    def _check_bounds(self, case: Dict[str, Any]) -> Optional[AdjudicationResult]:
        bounds = self.rubric.get("bounds", {})

        # Area plausibility
        area_rules = bounds.get("area_sqm", {})
        ptype = (case.get("property_type") or "").lower()
        limits = area_rules.get(ptype) or area_rules.get(case.get("property_type")) or area_rules.get("default")
        if limits:
            try:
                area = float(case.get("area_sqm") or 0)
                lo, hi = limits
                if not (lo <= area <= hi):
                    msg = f"area_sqm {area} outside plausible range {lo}–{hi} for '{ptype}'"
                    return AdjudicationResult(
                        source="bounds", verdict="REJECT", confidence=1.0,
                        reason="BOUND_AREA_IMPLAUSIBLE",
                        rationale_en=f"Rejected by plausibility check: {msg}.",
                        rationale_ar=f"رُفض بسبب فحص المعقولية: {msg}.",
                        bound_violated="BOUND_AREA_IMPLAUSIBLE",
                    )
            except (TypeError, ValueError):
                pass

        # City allow-list (only enforced when non-empty)
        valid_cities = [c.lower() for c in bounds.get("valid_cities", []) if c]
        if valid_cities:
            city = (case.get("city") or "").lower()
            if city not in valid_cities:
                return AdjudicationResult(
                    source="bounds", verdict="REJECT", confidence=1.0,
                    reason="BOUND_CITY_UNKNOWN",
                    rationale_en=f"City '{case.get('city')}' is not in the approved city list.",
                    rationale_ar=f"المدينة '{case.get('city')}' غير موجودة في قائمة المدن المعتمدة.",
                    bound_violated="BOUND_CITY_UNKNOWN",
                )
        return None

    # ------------------------------------------------------------------
    def _llm_judge(self, case: Dict[str, Any], neighbours: List[Dict]) -> AdjudicationResult:
        criteria_text = "\n".join(
            f"{c['id']}: {c['text']}" for c in self.rubric.get("criteria", [])
        )
        neighbours_text = "\n".join(
            f"- {n.get('case_id','?')}: {n.get('property_type','')} {n.get('area_sqm','')}sqm {n.get('city','')}"
            for n in (neighbours or [])[:3]
        ) or "none"

        prompt = self.prompt_template.format(
            criteria_text=criteria_text,
            case_json=json.dumps(case, ensure_ascii=False, indent=2),
            neighbours_text=neighbours_text,
        )

        try:
            r = httpx.post(
                f"{self.ollama_base}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
            )
            r.raise_for_status()
            raw = r.json()["response"].strip()
            return self._parse_llm(raw)
        except Exception as e:
            return AdjudicationResult("escalate", "ESCALATE", 0.0,
                                      f"LLM error: {e}", "", "")

    def _parse_llm(self, raw: str) -> AdjudicationResult:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not match:
            return AdjudicationResult("escalate", "ESCALATE", 0.0,
                                      "Could not parse LLM response", "", "")
        try:
            data = json.loads(match.group())
            verdict = data.get("verdict", "ESCALATE").upper()
            confidence = float(data.get("confidence", 0.0))

            # Apply confidence gates
            if verdict == "ACCEPT" and confidence >= self.accept_gate:
                source = "llm"
            elif verdict == "REJECT" and confidence >= self.reject_gate:
                source = "llm"
            else:
                verdict = "ESCALATE"
                source = "escalate"

            return AdjudicationResult(
                source=source,
                verdict=verdict,
                confidence=confidence,
                reason=f"LLM_JUDGE_{verdict}",
                rationale_en=data.get("rationale_en", ""),
                rationale_ar=data.get("rationale_ar", ""),
                criteria_scores=data.get("criteria_scores", []),
            )
        except Exception:
            return AdjudicationResult("escalate", "ESCALATE", 0.0,
                                      "Failed to parse LLM JSON", "", "")
