from __future__ import annotations

import json

import pytest

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.live_experiment import (
    REFERENCE_PATIENT_ID,
    resolve_intents,
    run_synthesis_case,
    synthesis_to_json,
)
from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    SynthesisFinding,
)


def _finding():
    return SynthesisFinding(
        statement="Atrial fibrillation was newly observed.",
        evidence_refs=(
            EvidenceReference(
                tool_name="get_condition_evidence",
                path=("new_conditions", 0),
            ),
        ),
    )


def _bundle():
    return {
        "patient_id": REFERENCE_PATIENT_ID,
        "intent": "current_state",
        "lookback_days": 365,
        "routing_notes": [],
        "conditional_tools": ["get_lab_evidence"],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {
                "new_conditions": [
                    {
                        "description": "Atrial fibrillation",
                        "first_start": "2026-05-04",
                    }
                ]
            }
        },
    }


class _WorkflowStub:
    def __init__(self, state):
        self.state = state
        self.received = None

    def invoke(self, payload):
        self.received = payload
        return self.state


class _StructuredStub:
    def __init__(self, response):
        self.response = response

    def invoke(self, messages):
        return self.response


class _ModelStub:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema):
        return _StructuredStub(self.response)


def test_resolve_intents_expands_both_in_stable_order():
    assert resolve_intents("both") == (
        ClinicalEvidenceIntent.CURRENT_STATE,
        ClinicalEvidenceIntent.TRAJECTORY,
    )


def test_resolve_intents_accepts_one_supported_intent():
    assert resolve_intents("trajectory") == (ClinicalEvidenceIntent.TRAJECTORY,)


def test_resolve_intents_rejects_unknown_intent():
    with pytest.raises(ValueError):
        resolve_intents("care_plan")


def test_run_synthesis_case_passes_patient_intent_and_lookback_to_workflow():
    synthesis = CurrentStateSynthesis(overall_assessment=_finding())
    workflow = _WorkflowStub({"evidence_bundle": _bundle()})

    result = run_synthesis_case(
        workflow=workflow,
        model=_ModelStub(synthesis),
        patient_id=REFERENCE_PATIENT_ID,
        intent="current_state",
        lookback_days=180,
    )

    assert result is synthesis
    assert workflow.received == {
        "patient_id": REFERENCE_PATIENT_ID,
        "intent": "current_state",
        "lookback_days": 180,
    }


def test_run_synthesis_case_fails_if_workflow_omits_bundle():
    with pytest.raises(RuntimeError, match="evidence_bundle"):
        run_synthesis_case(
            workflow=_WorkflowStub({}),
            model=_ModelStub(None),
            patient_id=REFERENCE_PATIENT_ID,
            intent="current_state",
        )


def test_synthesis_to_json_preserves_structured_evidence_references():
    synthesis = CurrentStateSynthesis(overall_assessment=_finding())
    payload = json.loads(synthesis_to_json(synthesis))
    assert payload["intent"] == "current_state"
    assert payload["overall_assessment"]["evidence_refs"][0] == {
        "tool_name": "get_condition_evidence",
        "path": ["new_conditions", 0],
    }
