from clinical_evidence_agent.evaluation import evaluate_synthesis_deterministically
from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    SynthesisFinding,
    TrajectorySynthesis,
)


def _bundle(intent="current_state"):
    return {
        "patient_id": "patient-secret-id",
        "intent": intent,
        "lookback_days": 365,
        "routing_notes": [],
        "conditional_tools": [],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {
                "status": "ok",
                "new_conditions": [{"description": "Example"}],
            }
        },
    }


def _finding(statement="A condition was newly observed."):
    return SynthesisFinding(
        statement=statement,
        evidence_refs=(
            EvidenceReference(
                tool_name="get_condition_evidence",
                path=("new_conditions", 0),
            ),
        ),
    )


def test_current_state_deterministic_evaluation_passes_valid_output():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding("The record contains a recent condition."),
        findings=(_finding(),),
    )

    result = evaluate_synthesis_deterministically(
        synthesis=synthesis,
        bundle=_bundle(),
    )

    assert result.passed is True
    assert {check.name for check in result.checks} == {
        "citation_validity",
        "intent_match",
        "answer_shape_limit",
        "no_duplicate_statements",
        "no_patient_id_leakage",
    }


def test_duplicate_statement_is_detected():
    finding = _finding("Repeated.")
    synthesis = CurrentStateSynthesis(
        overall_assessment=finding,
        findings=(finding,),
    )

    result = evaluate_synthesis_deterministically(
        synthesis=synthesis,
        bundle=_bundle(),
    )

    duplicate_check = next(
        check for check in result.checks if check.name == "no_duplicate_statements"
    )
    assert duplicate_check.passed is False
    assert result.passed is False


def test_patient_identifier_leakage_is_detected():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding("Patient patient-secret-id has a condition."),
    )

    result = evaluate_synthesis_deterministically(
        synthesis=synthesis,
        bundle=_bundle(),
    )

    leakage_check = next(
        check for check in result.checks if check.name == "no_patient_id_leakage"
    )
    assert leakage_check.passed is False


def test_trajectory_output_is_supported():
    synthesis = TrajectorySynthesis(
        overall_assessment=_finding("A recent change is documented."),
        changes=(_finding("A new condition appeared."),),
    )

    result = evaluate_synthesis_deterministically(
        synthesis=synthesis,
        bundle=_bundle("trajectory"),
    )

    assert result.intent == "trajectory"
    assert result.passed is True
