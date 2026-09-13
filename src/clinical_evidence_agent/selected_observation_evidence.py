"""Deterministic retrieval for validated numeric-observation selections.

Selection rationale is model-generated metadata. Retrieved evidence is produced
only by the existing deterministic lab evidence boundary and is kept separate
from that rationale.
"""

from __future__ import annotations

from typing import Any, TypedDict

from clinical_evidence_agent.lab_selection import (
    NumericObservationSelectionResult,
    validate_numeric_observation_selection,
)


class SelectedObservationEvidenceItem(TypedDict):
    code: str
    unit: str | None
    selection_rationale: str
    evidence: dict[str, Any]


class SelectedObservationEvidencePackage(TypedDict):
    intent: str
    selection_notes: list[str]
    selected_observation_count: int
    observations: list[SelectedObservationEvidenceItem]


def retrieve_selected_observation_evidence(
    toolset: Any,
    *,
    bundle: dict[str, Any],
    catalog: dict[str, Any],
    selection: NumericObservationSelectionResult,
) -> SelectedObservationEvidencePackage:
    """Validate selection again, then retrieve exact deterministic evidence."""
    validated = validate_numeric_observation_selection(
        selection,
        bundle=bundle,
        catalog=catalog,
    )

    observations: list[SelectedObservationEvidenceItem] = []
    for selected in validated.selections:
        evidence = toolset.get_lab_evidence(
            patient_id=bundle["patient_id"],
            code=selected.code,
            unit=selected.unit,
        )
        observations.append(
            {
                "code": selected.code,
                "unit": selected.unit,
                "selection_rationale": selected.rationale,
                "evidence": evidence,
            }
        )

    return {
        "intent": validated.intent.value,
        "selection_notes": list(validated.selection_notes),
        "selected_observation_count": len(observations),
        "observations": observations,
    }


SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL = "get_selected_numeric_observation_evidence"


def build_citable_selected_observation_evidence(
    package: SelectedObservationEvidencePackage,
) -> dict[str, Any]:
    """Strip model-generated selection metadata from citable evidence."""
    return {
        "status": "ok",
        "selected_observation_count": package["selected_observation_count"],
        "observations": [
            {
                "code": item["code"],
                "unit": item["unit"],
                "evidence": item["evidence"],
            }
            for item in package["observations"]
        ],
    }


def enrich_evidence_bundle_with_selected_observations(
    *,
    bundle: dict[str, Any],
    package: SelectedObservationEvidencePackage,
) -> dict[str, Any]:
    """Return a copy enriched with deterministic numeric-observation evidence.

    Selector notes/rationales are retained only as non-citable diagnostic
    metadata. Synthesis receives only ``evidence_by_tool``.
    """
    enriched = dict(bundle)
    evidence_by_tool = dict(bundle["evidence_by_tool"])
    evidence_by_tool[SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL] = (
        build_citable_selected_observation_evidence(package)
    )
    enriched["evidence_by_tool"] = evidence_by_tool
    enriched["numeric_observation_selection_metadata"] = {
        "selection_notes": list(package["selection_notes"]),
        "selection_rationales": [
            {
                "code": item["code"],
                "unit": item["unit"],
                "rationale": item["selection_rationale"],
            }
            for item in package["observations"]
        ],
    }
    return enriched
