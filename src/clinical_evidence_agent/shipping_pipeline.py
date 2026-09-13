"""Cost-conscious one-call synthesis pipeline for the portfolio application.

The research/evaluation path remains available unchanged.  This shipping path
removes the LLM numeric selector, performs deterministic numeric enrichment,
then makes one constrained synthesis call for each uncached patient/intent
request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, MutableMapping

from clinical_evidence_agent import database
from clinical_evidence_agent.deterministic_numeric_selection import (
    DEFAULT_NUMERIC_CANDIDATE_LIMIT,
    select_numeric_observations_deterministically,
)
from clinical_evidence_agent.evidence_routing import (
    ClinicalEvidenceIntent,
    DEFAULT_LOOKBACK_DAYS,
)
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.llm_synthesis import synthesize_evidence_bundle
from clinical_evidence_agent.selected_observation_evidence import (
    enrich_evidence_bundle_with_selected_observations,
    retrieve_selected_observation_evidence,
)


SHIPPING_PIPELINE_VERSION = "1.0"


@dataclass(frozen=True)
class ShippingSynthesisResult:
    synthesis: Any
    evidence_bundle: dict[str, Any]
    numeric_selection: dict[str, Any]
    cache_hit: bool


def _cache_key(
    *,
    bundle: dict[str, Any],
    intent: ClinicalEvidenceIntent,
    lookback_days: int,
    model_name: str,
    reasoning_effort: str,
    numeric_candidate_limit: int,
) -> tuple[Any, ...]:
    return (
        SHIPPING_PIPELINE_VERSION,
        bundle["patient_id"],
        bundle.get("anchor_date")
        or next(
            (
                value.get("anchor_date")
                for value in bundle.get("evidence_by_tool", {}).values()
                if isinstance(value, dict) and value.get("anchor_date")
            ),
            None,
        ),
        intent.value,
        lookback_days,
        model_name,
        reasoning_effort,
        numeric_candidate_limit,
    )


def run_shipping_synthesis(
    *,
    workflow: Any,
    toolset: EvidenceToolset,
    con: Any,
    model: Any,
    patient_id: str,
    intent: ClinicalEvidenceIntent | str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    numeric_candidate_limit: int = DEFAULT_NUMERIC_CANDIDATE_LIMIT,
    cache: MutableMapping[tuple[Any, ...], Any] | None = None,
    model_name: str = "configured-model",
    reasoning_effort: str = "low",
) -> ShippingSynthesisResult:
    """Run deterministic retrieval + deterministic numeric enrichment + one LLM call."""
    intent = ClinicalEvidenceIntent(intent)
    state = workflow.invoke(
        {
            "patient_id": patient_id,
            "intent": intent.value,
            "lookback_days": lookback_days,
        }
    )
    bundle = state["evidence_bundle"]

    catalog = database.get_patient_numeric_lab_catalog(con, patient_id)
    selection = select_numeric_observations_deterministically(
        bundle=bundle,
        catalog=catalog,
        limit=numeric_candidate_limit,
    )
    package = retrieve_selected_observation_evidence(
        toolset,
        bundle=bundle,
        catalog=catalog,
        selection=selection,
    )
    enriched_bundle = enrich_evidence_bundle_with_selected_observations(
        bundle=bundle,
        package=package,
    )

    key = _cache_key(
        bundle=enriched_bundle,
        intent=intent,
        lookback_days=lookback_days,
        model_name=model_name,
        reasoning_effort=reasoning_effort,
        numeric_candidate_limit=numeric_candidate_limit,
    )
    if cache is not None and key in cache:
        synthesis = cache[key]
        return ShippingSynthesisResult(
            synthesis=synthesis,
            evidence_bundle=enriched_bundle,
            numeric_selection=selection.model_dump(mode="json"),
            cache_hit=True,
        )

    synthesis = synthesize_evidence_bundle(model=model, bundle=enriched_bundle)
    if cache is not None:
        cache[key] = synthesis

    return ShippingSynthesisResult(
        synthesis=synthesis,
        evidence_bundle=enriched_bundle,
        numeric_selection=selection.model_dump(mode="json"),
        cache_hit=False,
    )
