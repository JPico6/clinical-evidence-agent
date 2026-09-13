import pytest

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.lab_selection import (
    NumericObservationSelection,
    NumericObservationSelectionResult,
)
from clinical_evidence_agent.selected_observation_evidence import (
    retrieve_selected_observation_evidence,
)


class RecordingToolset:
    def __init__(self):
        self.calls = []

    def get_lab_evidence(self, patient_id, code, unit=None):
        self.calls.append(
            {"patient_id": patient_id, "code": code, "unit": unit}
        )
        return {
            "status": "ok",
            "code": code,
            "unit": unit,
            "marker": object(),
        }


def _bundle():
    return {
        "patient_id": "patient-1",
        "intent": "current_state",
        "evidence_by_tool": {},
    }


def _catalog():
    return {
        "labs": [
            {
                "code": "2160-0",
                "available_units": [{"unit": "mg/dL"}],
            },
            {
                "code": "33914-3",
                "available_units": [
                    {"unit": "mL/min"},
                    {"unit": "mL/min/{1.73_m2}"},
                ],
            },
        ]
    }


def test_retrieves_exact_selected_code_unit_pairs_in_order():
    toolset = RecordingToolset()
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="33914-3",
                unit="mL/min/{1.73_m2}",
                rationale="Renal filtration.",
            ),
            NumericObservationSelection(
                code="2160-0",
                unit="mg/dL",
                rationale="Complementary renal marker.",
            ),
        ),
        selection_notes=("Keep retrieval focused.",),
    )

    package = retrieve_selected_observation_evidence(
        toolset,
        bundle=_bundle(),
        catalog=_catalog(),
        selection=selection,
    )

    assert toolset.calls == [
        {
            "patient_id": "patient-1",
            "code": "33914-3",
            "unit": "mL/min/{1.73_m2}",
        },
        {
            "patient_id": "patient-1",
            "code": "2160-0",
            "unit": "mg/dL",
        },
    ]
    assert package["selected_observation_count"] == 2
    assert package["selection_notes"] == ["Keep retrieval focused."]


def test_preserves_deterministic_evidence_object_unchanged():
    toolset = RecordingToolset()
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="2160-0",
                unit="mg/dL",
                rationale="Renal marker.",
            ),
        ),
    )

    package = retrieve_selected_observation_evidence(
        toolset,
        bundle=_bundle(),
        catalog=_catalog(),
        selection=selection,
    )

    evidence = package["observations"][0]["evidence"]
    assert evidence["marker"] is not None
    assert evidence["code"] == "2160-0"


def test_keeps_model_rationale_separate_from_deterministic_evidence():
    toolset = RecordingToolset()
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

    package = retrieve_selected_observation_evidence(
        toolset,
        bundle=_bundle(),
        catalog=_catalog(),
        selection=selection,
    )

    item = package["observations"][0]
    assert item["selection_rationale"] == "Could help characterize renal status."
    assert "selection_rationale" not in item["evidence"]


def test_empty_selection_returns_empty_package_without_tool_calls():
    toolset = RecordingToolset()
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(),
        selection_notes=("No useful numeric observations.",),
    )

    package = retrieve_selected_observation_evidence(
        toolset,
        bundle=_bundle(),
        catalog=_catalog(),
        selection=selection,
    )

    assert toolset.calls == []
    assert package["selected_observation_count"] == 0
    assert package["observations"] == []


def test_revalidates_selection_before_any_retrieval():
    toolset = RecordingToolset()
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="invented",
                unit="mg/dL",
                rationale="Invalid.",
            ),
        ),
    )

    with pytest.raises(ValueError, match="not present in patient catalog"):
        retrieve_selected_observation_evidence(
            toolset,
            bundle=_bundle(),
            catalog=_catalog(),
            selection=selection,
        )

    assert toolset.calls == []


def test_uses_bundle_patient_scope_not_model_supplied_scope():
    toolset = RecordingToolset()
    selection = NumericObservationSelectionResult(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        selections=(
            NumericObservationSelection(
                code="2160-0",
                unit="mg/dL",
                rationale="Renal marker.",
            ),
        ),
    )

    retrieve_selected_observation_evidence(
        toolset,
        bundle=_bundle(),
        catalog=_catalog(),
        selection=selection,
    )

    assert toolset.calls[0]["patient_id"] == "patient-1"
