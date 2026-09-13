import pytest
from pydantic import ValidationError

from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    SynthesisFinding,
    TrajectorySynthesis,
    get_synthesis_guardrails,
    validate_synthesis_against_bundle,
)


def _bundle(intent="current_state"):
    return {
        "patient_id": "patient-1",
        "intent": intent,
        "lookback_days": 365,
        "routing_notes": [],
        "conditional_tools": ["get_lab_evidence"],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {
                "status": "ok",
                "new_conditions": [
                    {"description": "Atrial fibrillation", "start": "2026-05-04"}
                ],
            },
            "get_utilization_evidence": {
                "status": "ok",
                "comparison": {"recent_count": 10, "prior_count": 4},
            },
        },
    }


def _finding(tool="get_condition_evidence", path=("new_conditions", 0)):
    return SynthesisFinding(
        statement="Atrial fibrillation was newly observed in the recent period.",
        evidence_refs=(EvidenceReference(tool_name=tool, path=path),),
    )


def test_finding_requires_at_least_one_evidence_reference():
    with pytest.raises(ValidationError):
        SynthesisFinding(statement="Unsupported statement", evidence_refs=())


def test_contract_models_forbid_unexpected_fields():
    with pytest.raises(ValidationError):
        EvidenceReference(
            tool_name="get_condition_evidence",
            path=("status",),
            unsupported=True,
        )


def test_current_state_contract_has_fixed_intent():
    synthesis = CurrentStateSynthesis(overall_assessment=_finding())
    assert synthesis.intent.value == "current_state"

    with pytest.raises(ValidationError):
        CurrentStateSynthesis(intent="trajectory", overall_assessment=_finding())


def test_trajectory_contract_has_fixed_intent():
    synthesis = TrajectorySynthesis(overall_assessment=_finding())
    assert synthesis.intent.value == "trajectory"

    with pytest.raises(ValidationError):
        TrajectorySynthesis(intent="current_state", overall_assessment=_finding())


def test_valid_synthesis_references_existing_nested_evidence():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding(),
        findings=(
            SynthesisFinding(
                statement="Recent utilization exceeded prior utilization.",
                evidence_refs=(
                    EvidenceReference(
                        tool_name="get_utilization_evidence",
                        path=("comparison", "recent_count"),
                    ),
                    EvidenceReference(
                        tool_name="get_utilization_evidence",
                        path=("comparison", "prior_count"),
                    ),
                ),
            ),
        ),
    )

    assert validate_synthesis_against_bundle(synthesis, _bundle()) is synthesis


def test_validation_rejects_reference_to_tool_that_did_not_run():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding(
            tool="get_lab_evidence",
            path=("summary",),
        )
    )

    with pytest.raises(ValueError, match="not executed"):
        validate_synthesis_against_bundle(synthesis, _bundle())


def test_validation_rejects_nonexistent_evidence_path():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding(path=("new_conditions", 99))
    )

    with pytest.raises(ValueError, match="out of range"):
        validate_synthesis_against_bundle(synthesis, _bundle())


def test_validation_rejects_intent_mismatch():
    synthesis = TrajectorySynthesis(overall_assessment=_finding())

    with pytest.raises(ValueError, match="intent does not match"):
        validate_synthesis_against_bundle(synthesis, _bundle("current_state"))


def test_guardrails_preserve_core_clinical_boundaries():
    guardrails = " ".join(get_synthesis_guardrails("trajectory")).lower()

    assert "source-open" in guardrails
    assert "causal" in guardrails
    assert "improvement or worsening" in guardrails
    assert "laboratory" in guardrails
    assert "care plan" in guardrails
