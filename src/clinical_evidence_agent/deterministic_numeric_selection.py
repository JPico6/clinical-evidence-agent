"""Deterministic numeric-observation candidates for the low-cost live path.

The evaluated research path may still use the LLM selector.  The shipping path
uses this module instead so numeric enrichment does not require a separate
model call.

This is deliberately a retrieval heuristic, not a clinical-importance model:
it favors observations documented recently and repeatedly, chooses one
grounded unit per code, and leaves final inclusion/materiality to constrained
synthesis.
"""

from __future__ import annotations

from typing import Any

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.lab_selection import (
    MAX_SELECTED_OBSERVATIONS,
    NumericObservationSelection,
    NumericObservationSelectionResult,
)


DEFAULT_NUMERIC_CANDIDATE_LIMIT = 6


def _unit_rank(unit_item: dict[str, Any]) -> tuple[int, int, str]:
    return (
        int(unit_item.get("recent_measurement_count", 0)),
        int(unit_item.get("measurement_count", 0)),
        "" if unit_item.get("unit") is None else str(unit_item["unit"]),
    )


def select_numeric_observations_deterministically(
    *,
    bundle: dict[str, Any],
    catalog: dict[str, Any],
    limit: int = DEFAULT_NUMERIC_CANDIDATE_LIMIT,
) -> NumericObservationSelectionResult:
    """Choose grounded numeric candidates without an LLM call.

    Only observations with at least one measurement in the patient-relative
    recent window are eligible.  Catalog order already favors recent then
    lifetime frequency; this function adds deterministic recency tie-breaking
    and chooses the strongest observed unit for multi-unit codes.

    The returned rationale is retrieval metadata only and is never citable
    clinical evidence.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be a nonnegative integer")
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    limit = min(limit, MAX_SELECTED_OBSERVATIONS)

    intent = ClinicalEvidenceIntent(bundle["intent"])
    if catalog.get("status") not in {"ok", None} or limit == 0:
        return NumericObservationSelectionResult(
            intent=intent,
            selections=(),
            selection_notes=("Deterministic live-path selection; no eligible numeric candidates.",),
        )

    eligible = [
        item
        for item in catalog.get("labs", [])
        if int(item.get("recent_measurement_count", 0)) > 0
        and item.get("available_units")
    ]
    eligible.sort(
        key=lambda item: (
            str(item.get("last_date") or ""),
            int(item.get("recent_measurement_count", 0)),
            int(item.get("measurement_count", 0)),
            str(item.get("code", "")),
        ),
        reverse=True,
    )

    selections = []
    for item in eligible[:limit]:
        units = sorted(item["available_units"], key=_unit_rank, reverse=True)
        chosen_unit = units[0].get("unit")
        selections.append(
            NumericObservationSelection(
                code=str(item["code"]),
                unit=None if chosen_unit is None else str(chosen_unit),
                rationale=(
                    "Deterministic live-path candidate: recently documented numeric "
                    "observation; synthesis decides whether it is material."
                ),
            )
        )

    return NumericObservationSelectionResult(
        intent=intent,
        selections=tuple(selections),
        selection_notes=(
            "Selected deterministically for the low-cost live path; frequency/recency "
            "are retrieval heuristics, not clinical-importance claims.",
        ),
    )
