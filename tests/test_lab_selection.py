import pytest

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.lab_selection import (
    NumericObservationSelection,
    NumericObservationSelectionResult,
    build_numeric_observation_selection_messages,
    validate_numeric_observation_selection,
)


def _bundle(intent="current_state"):
    return {
        "intent": intent,
        "evidence_by_tool": {
            "get_condition_evidence": {
                "conditions": [
                    {
                        "description": "Chronic kidney disease stage 4",
                        "source_open_episode_count": 1,
                    }
                ]
            }
        },
    }


def _catalog():
    return {
        "status": "ok",
        "labs": [
            {
                "code": "33914-3",
                "description": "eGFR",
                "available_units": [
                    {"unit": "mL/min"},
                    {"unit": "mL/min/{1.73_m2}"},
                ],
            },
            {
                "code": "2160-0",
                "description": "Creatinine",
                "available_units": [{"unit": "mg/dL"}],
            },
        ],
    }


def test_selection_messages_include_core_evidence_and_catalog():
    messages = build_numeric_observation_selection_messages(
        bundle=_bundle(),
        catalog=_catalog(),
    )
    rendered = "\n".join(message for _, message in messages)

    assert "Chronic kidney disease stage 4" in rendered
    assert "33914-3" in rendered
    assert "mL/min/{1.73_m2}" in rendered
    assert "Maximum 8 selections" in rendered
    assert "Do not invent codes" in rendered


def test_valid_selection_passes():
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="2160-0",
                unit="mg/dL",
                rationale="Could help characterize renal status.",
            ),
        ),
    )

    validated = validate_numeric_observation_selection(
        selection,
        bundle=_bundle(),
        catalog=_catalog(),
    )

    assert validated is selection


def test_unknown_code_fails_closed():
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="NOT-REAL",
                unit="mg/dL",
                rationale="Invented.",
            ),
        ),
    )

    with pytest.raises(ValueError, match="not present in patient catalog"):
        validate_numeric_observation_selection(
            selection,
            bundle=_bundle(),
            catalog=_catalog(),
        )


def test_unknown_unit_fails_closed():
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="2160-0",
                unit="mmol/L",
                rationale="Wrong unit.",
            ),
        ),
    )

    with pytest.raises(ValueError, match="is not available"):
        validate_numeric_observation_selection(
            selection,
            bundle=_bundle(),
            catalog=_catalog(),
        )


def test_multi_unit_code_requires_specific_valid_unit():
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="33914-3",
                unit=None,
                rationale="Renal function.",
            ),
        ),
    )

    with pytest.raises(ValueError, match="not available|multiple units"):
        validate_numeric_observation_selection(
            selection,
            bundle=_bundle(),
            catalog=_catalog(),
        )


def test_intent_mismatch_fails_closed():
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.TRAJECTORY,
        selections=(),
    )

    with pytest.raises(ValueError, match="does not match"):
        validate_numeric_observation_selection(
            selection,
            bundle=_bundle("current_state"),
            catalog=_catalog(),
        )


def test_duplicate_code_unit_pair_rejected_by_schema():
    with pytest.raises(ValueError, match="duplicate observation"):
        NumericObservationSelectionResult(
            intent=ClinicalEvidenceIntent.CURRENT_STATE,
            selections=(
                NumericObservationSelection(
                    code="2160-0",
                    unit="mg/dL",
                    rationale="One.",
                ),
                NumericObservationSelection(
                    code="2160-0",
                    unit="mg/dL",
                    rationale="Two.",
                ),
            ),
        )
