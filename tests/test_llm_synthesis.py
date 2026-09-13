from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.llm_synthesis import (
    build_synthesis_messages,
    get_synthesis_schema,
    synthesize_evidence_bundle,
)
from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    SynthesisFinding,
    TrajectorySynthesis,
)


def _bundle(intent: str = "current_state"):
    return {
        "patient_id": "patient-123",
        "intent": intent,
        "lookback_days": 365,
        "routing_notes": ["deterministic routing note"],
        "conditional_tools": ["get_lab_evidence"],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {
                "status": "ok",
                "new_conditions": [
                    {"description": "Atrial fibrillation", "first_start": "2026-05-04"}
                ],
            },
            "get_utilization_evidence": {
                "status": "ok",
                "comparison": {"prior": 74, "recent": 68},
            },
        },
    }


class _StructuredStub:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return self.response


class _ModelStub:
    def __init__(self, response):
        self.response = response
        self.schema = None
        self.structured = _StructuredStub(response)

    def with_structured_output(self, schema):
        self.schema = schema
        return self.structured


def _finding(statement="AF was newly observed."):
    return SynthesisFinding(
        statement=statement,
        evidence_refs=(
            EvidenceReference(
                tool_name="get_condition_evidence",
                path=("new_conditions", 0),
            ),
        ),
    )


def test_schema_is_selected_by_intent():
    assert get_synthesis_schema("current_state") is CurrentStateSynthesis
    assert get_synthesis_schema("trajectory") is TrajectorySynthesis


def test_messages_exclude_patient_identifier_and_include_only_evidence_payload():
    messages = build_synthesis_messages(_bundle())
    rendered = "\n".join(str(message.content) for message in messages)
    assert "patient-123" not in rendered
    assert "deterministic routing note" not in rendered
    assert "get_lab_evidence" not in rendered
    assert "Atrial fibrillation" in rendered
    assert "evidence_by_tool" in rendered


def test_messages_include_guardrails_and_json_path_instructions():
    messages = build_synthesis_messages(_bundle())
    system = str(messages[0].content)
    assert "source-open" in system
    assert "care plan" in system
    assert "zero-based array indexes" in system


def test_current_state_synthesis_uses_structured_schema_and_validates_refs():
    response = CurrentStateSynthesis(
        overall_assessment=_finding(),
        findings=(_finding("A recent AF record is present."),),
    )
    model = _ModelStub(response)
    result = synthesize_evidence_bundle(model=model, bundle=_bundle())
    assert result is response
    assert model.schema is CurrentStateSynthesis


def test_trajectory_synthesis_uses_trajectory_schema():
    response = TrajectorySynthesis(
        overall_assessment=_finding("A new condition was observed recently."),
        changes=(_finding(),),
    )
    model = _ModelStub(response)
    result = synthesize_evidence_bundle(
        model=model,
        bundle=_bundle("trajectory"),
    )
    assert result is response
    assert model.schema is TrajectorySynthesis


def test_invalid_model_reference_fails_closed_after_generation():
    response = CurrentStateSynthesis(
        overall_assessment=SynthesisFinding(
            statement="Unsupported statement.",
            evidence_refs=(
                EvidenceReference(
                    tool_name="get_condition_evidence",
                    path=("new_conditions", 99),
                ),
            ),
        )
    )
    with pytest.raises(ValueError, match="out of range"):
        synthesize_evidence_bundle(model=_ModelStub(response), bundle=_bundle())


def test_unexpected_structured_return_type_fails_closed():
    with pytest.raises(TypeError, match="unexpected type"):
        synthesize_evidence_bundle(model=_ModelStub({"not": "a synthesis"}), bundle=_bundle())


class _SequenceStructuredStub:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return next(self.responses)


class _SequenceModelStub:
    def __init__(self, responses):
        self.schema = None
        self.structured = _SequenceStructuredStub(responses)

    def with_structured_output(self, schema):
        self.schema = schema
        return self.structured


def test_invalid_reference_gets_one_bounded_repair_attempt():
    invalid = CurrentStateSynthesis(
        overall_assessment=SynthesisFinding(
            statement="AF was newly observed.",
            evidence_refs=(
                EvidenceReference(
                    tool_name="get_condition_evidence",
                    path=("new_conditions", 5),
                ),
            ),
        )
    )
    repaired = CurrentStateSynthesis(overall_assessment=_finding())
    model = _SequenceModelStub([invalid, repaired])

    result = synthesize_evidence_bundle(model=model, bundle=_bundle())

    assert result is repaired
    assert len(model.structured.calls) == 2
    repair_prompt = str(model.structured.calls[1][-1].content)
    assert "out of range" in repair_prompt
    assert "valid indexes are 0..0" in repair_prompt


def test_reference_repair_still_fails_closed_after_bound():
    invalid = CurrentStateSynthesis(
        overall_assessment=SynthesisFinding(
            statement="Unsupported statement.",
            evidence_refs=(
                EvidenceReference(
                    tool_name="get_condition_evidence",
                    path=("new_conditions", 5),
                ),
            ),
        )
    )
    model = _SequenceModelStub([invalid, invalid])

    with pytest.raises(ValueError, match="out of range"):
        synthesize_evidence_bundle(model=model, bundle=_bundle())

    assert len(model.structured.calls) == 2


def test_reference_repair_can_be_disabled():
    invalid = CurrentStateSynthesis(
        overall_assessment=SynthesisFinding(
            statement="Unsupported statement.",
            evidence_refs=(
                EvidenceReference(
                    tool_name="get_condition_evidence",
                    path=("new_conditions", 5),
                ),
            ),
        )
    )
    model = _SequenceModelStub([invalid])

    with pytest.raises(ValueError, match="out of range"):
        synthesize_evidence_bundle(
            model=model,
            bundle=_bundle(),
            max_reference_repairs=0,
        )

    assert len(model.structured.calls) == 1
