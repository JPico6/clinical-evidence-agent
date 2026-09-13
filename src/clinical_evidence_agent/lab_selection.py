"""Constrained selection of patient-grounded numeric observations.

The model may decide which available observations could materially help answer
the already-selected product task. It may not invent an observation code, unit,
value, or trend. Every selected code/unit pair is validated against the
deterministic patient catalog before it can be used for evidence retrieval.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent


MAX_SELECTED_OBSERVATIONS = 8


class NumericObservationSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    unit: str | None = None
    rationale: str = Field(min_length=1)


class NumericObservationSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: ClinicalEvidenceIntent
    selections: tuple[NumericObservationSelection, ...] = Field(
        default_factory=tuple,
        max_length=MAX_SELECTED_OBSERVATIONS,
    )
    selection_notes: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def unique_code_unit_pairs(self):
        pairs = [(item.code, item.unit) for item in self.selections]
        if len(pairs) != len(set(pairs)):
            raise ValueError("duplicate observation code/unit selection")
        return self


def build_numeric_observation_selection_messages(
    *,
    bundle: dict[str, Any],
    catalog: dict[str, Any],
) -> list[tuple[str, str]]:
    intent = ClinicalEvidenceIntent(bundle["intent"])
    evidence_by_tool = bundle.get("evidence_by_tool", {})
    catalog_items = catalog.get("labs", [])

    system = """You are selecting patient-grounded numeric observations for a synthetic-data clinical evidence demo.

Your task is ONLY to choose which available numeric observations could materially help answer the product task represented by the supplied intent and deterministic evidence.

Rules:
- Select only code/unit pairs that appear exactly in the supplied observation catalog.
- Do not invent codes, units, values, trends, diagnoses, or clinical facts.
- Do not infer any observation value from its presence or frequency.
- A high measurement count does not make an observation clinically important.
- You may select zero observations if none would materially improve the answer.
- Prefer a small, clinically focused set. Maximum 8 selections.
- Use the deterministic clinical evidence to judge relevance.
- If a code has multiple units, choose a specific supplied unit.
- Do not provide treatment recommendations or care plans.
- The rationale explains why retrieving that observation could help answer the task; it must not claim an unseen result.
"""

    payload = {
        "intent": intent.value,
        "task": (
            "Describe the patient's current medical situation."
            if intent is ClinicalEvidenceIntent.CURRENT_STATE
            else "Explain the patient's recent clinical trajectory / how they are changing."
        ),
        "deterministic_evidence": evidence_by_tool,
        "numeric_observation_catalog": catalog_items,
    }

    return [
        ("system", system),
        ("human", json.dumps(payload, default=str)),
    ]


def _catalog_code_unit_pairs(catalog: dict[str, Any]) -> dict[str, set[str | None]]:
    available: dict[str, set[str | None]] = {}
    for item in catalog.get("labs", []):
        code = item["code"]
        available.setdefault(code, set()).update(
            unit_item.get("unit") for unit_item in item.get("available_units", [])
        )
    return available


def validate_numeric_observation_selection(
    selection: NumericObservationSelectionResult,
    *,
    bundle: dict[str, Any],
    catalog: dict[str, Any],
) -> NumericObservationSelectionResult:
    expected_intent = ClinicalEvidenceIntent(bundle["intent"])
    if selection.intent is not expected_intent:
        raise ValueError(
            f"selection intent {selection.intent.value!r} does not match "
            f"bundle intent {expected_intent.value!r}"
        )

    available = _catalog_code_unit_pairs(catalog)

    for selected in selection.selections:
        if selected.code not in available:
            raise ValueError(
                f"selected observation code is not present in patient catalog: "
                f"{selected.code!r}"
            )
        valid_units = available[selected.code]
        if selected.unit not in valid_units:
            raise ValueError(
                f"selected unit {selected.unit!r} is not available for "
                f"observation code {selected.code!r}; "
                f"valid units are {sorted(valid_units, key=lambda x: '' if x is None else x)}"
            )
        if len(valid_units) > 1 and selected.unit is None:
            raise ValueError(
                f"observation code {selected.code!r} has multiple units; "
                "a specific catalog unit is required"
            )

    return selection


def select_numeric_observations(
    model: Any,
    *,
    bundle: dict[str, Any],
    catalog: dict[str, Any],
) -> NumericObservationSelectionResult:
    schema_model = model.with_structured_output(NumericObservationSelectionResult)
    result = schema_model.invoke(
        build_numeric_observation_selection_messages(bundle=bundle, catalog=catalog)
    )
    if not isinstance(result, NumericObservationSelectionResult):
        raise TypeError(
            "numeric observation selector returned unexpected structured output type"
        )
    return validate_numeric_observation_selection(
        result,
        bundle=bundle,
        catalog=catalog,
    )
