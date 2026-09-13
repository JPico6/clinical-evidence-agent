"""Application-facing service for the cost-conscious portfolio UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from time import perf_counter
from typing import Any, MutableMapping

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from clinical_evidence_agent import database
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent, DEFAULT_LOOKBACK_DAYS
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.evidence_workflow import build_clinical_evidence_workflow
from clinical_evidence_agent.shipping_pipeline import ShippingSynthesisResult, run_shipping_synthesis


load_dotenv()

DEFAULT_SHIPPING_MODEL = "gpt-5.6-luna"
DEFAULT_SHIPPING_REASONING_EFFORT = "low"


@dataclass(frozen=True)
class ApplicationAnswer:
    synthesis: Any
    evidence_bundle: dict[str, Any]
    numeric_selection: dict[str, Any]
    cache_hit: bool
    model_name: str
    reasoning_effort: str
    elapsed_seconds: float


class ClinicalEvidenceApplicationService:
    """Owns DB/tool/workflow/model resources used by Streamlit or a CLI demo."""

    def __init__(
        self,
        *,
        con: Any | None = None,
        model: Any | None = None,
        cache: MutableMapping[tuple[Any, ...], Any] | None = None,
        model_name: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.con = con or database.get_connection()
        if con is None:
            database.register_synthea_tables(self.con)

        self.toolset = EvidenceToolset(self.con)
        self.workflow = build_clinical_evidence_workflow(self.toolset)

        self.model_name = model_name or os.getenv(
            "CLINICAL_EVIDENCE_MODEL", DEFAULT_SHIPPING_MODEL
        )
        self.reasoning_effort = reasoning_effort or os.getenv(
            "CLINICAL_EVIDENCE_REASONING_EFFORT",
            DEFAULT_SHIPPING_REASONING_EFFORT,
        )
        self.model = model or ChatOpenAI(
            model=self.model_name,
            reasoning_effort=self.reasoning_effort,
        )
        self.cache = cache if cache is not None else {}

    def list_patients(self) -> list[dict[str, Any]]:
        """Return compact deterministic patient metadata; never invokes the LLM."""
        rows = self.con.execute(
            """
            SELECT
                Id AS patient_id,
                FIRST AS first_name,
                LAST AS last_name,
                BIRTHDATE AS birth_date,
                DEATHDATE AS death_date,
                GENDER AS gender
            FROM patients
            ORDER BY LAST, FIRST, Id
            """
        ).fetchdf()
        return rows.where(rows.notna(), None).to_dict(orient="records")

    def answer(
        self,
        *,
        patient_id: str,
        intent: ClinicalEvidenceIntent | str,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> ApplicationAnswer:
        """Answer one supported question with at most one paid LLM call on a cache miss."""
        started = perf_counter()
        result: ShippingSynthesisResult = run_shipping_synthesis(
            workflow=self.workflow,
            toolset=self.toolset,
            con=self.con,
            model=self.model,
            patient_id=patient_id,
            intent=intent,
            lookback_days=lookback_days,
            cache=self.cache,
            model_name=self.model_name,
            reasoning_effort=self.reasoning_effort,
        )
        return ApplicationAnswer(
            synthesis=result.synthesis,
            evidence_bundle=result.evidence_bundle,
            numeric_selection=result.numeric_selection,
            cache_hit=result.cache_hit,
            model_name=self.model_name,
            reasoning_effort=self.reasoning_effort,
            elapsed_seconds=perf_counter() - started,
        )
