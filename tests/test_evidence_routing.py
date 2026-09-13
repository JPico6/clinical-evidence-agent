import pytest

from clinical_evidence_agent.evidence_routing import (
    ClinicalEvidenceIntent,
    DEFAULT_LOOKBACK_DAYS,
    build_evidence_plan,
)


def _tool_names(plan):
    return [call.tool_name for call in plan.tool_calls]


def test_current_state_plan_is_fixed_and_comprehensive():
    plan = build_evidence_plan(ClinicalEvidenceIntent.CURRENT_STATE)

    assert plan.intent is ClinicalEvidenceIntent.CURRENT_STATE
    assert _tool_names(plan) == [
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
        "get_recent_event_evidence",
        "get_utilization_evidence",
    ]
    assert plan.conditional_tools == ("get_lab_evidence",)


def test_trajectory_plan_prioritizes_change_evidence():
    plan = build_evidence_plan("trajectory", lookback_days=180)

    assert _tool_names(plan) == [
        "get_recent_event_evidence",
        "get_utilization_evidence",
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
    ]
    for call in plan.tool_calls:
        if call.tool_name == "get_utilization_evidence":
            assert call.arguments == {}
        else:
            assert call.arguments == {"lookback_days": 180}


def test_plans_do_not_embed_or_choose_patient_id():
    for intent in ClinicalEvidenceIntent:
        plan = build_evidence_plan(intent)
        assert all("patient_id" not in call.arguments for call in plan.tool_calls)


def test_lab_evidence_is_conditional_not_silently_routed():
    for intent in ClinicalEvidenceIntent:
        plan = build_evidence_plan(intent)
        assert "get_lab_evidence" not in _tool_names(plan)
        assert plan.conditional_tools == ("get_lab_evidence",)
        assert any("lab" in note.lower() for note in plan.routing_notes)


def test_default_lookback_is_applied_to_lookback_tools():
    plan = build_evidence_plan(ClinicalEvidenceIntent.CURRENT_STATE)
    lookback_calls = [
        call
        for call in plan.tool_calls
        if call.tool_name != "get_utilization_evidence"
    ]
    assert all(
        call.arguments == {"lookback_days": DEFAULT_LOOKBACK_DAYS}
        for call in lookback_calls
    )


@pytest.mark.parametrize("bad_value", [0, -1, True, 30.5, "365"])
def test_invalid_lookback_rejected(bad_value):
    with pytest.raises(ValueError, match="positive integer"):
        build_evidence_plan(
            ClinicalEvidenceIntent.CURRENT_STATE,
            lookback_days=bad_value,
        )


def test_unknown_intent_rejected():
    with pytest.raises(ValueError):
        build_evidence_plan("care_plan")
