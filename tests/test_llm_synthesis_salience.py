from clinical_evidence_agent.llm_synthesis import build_synthesis_messages


def _bundle(intent="current_state"):
    return {
        "patient_id": "patient-1",
        "intent": intent,
        "lookback_days": 365,
        "routing_notes": [],
        "conditional_tools": [],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {
                "status": "ok",
                "conditions": [{"description": "Example"}],
            }
        },
    }


def test_current_state_prompt_requires_prioritized_bounded_output():
    messages = build_synthesis_messages(_bundle("current_state"))
    rendered = "\n".join(str(message.content) for message in messages).lower()

    assert "at most 6 prioritized findings" in rendered
    assert "not an exhaustive evidence inventory" in rendered
    assert "desirable to omit true but lower-priority evidence" in rendered
    assert "frequency of documentation alone" in rendered
    assert "do not give them their own finding solely because they were retrieved" in rendered


def test_trajectory_prompt_requires_prioritized_bounded_output():
    messages = build_synthesis_messages(_bundle("trajectory"))
    rendered = "\n".join(str(message.content) for message in messages).lower()

    assert "at most 5 prioritized changes" in rendered
    assert "rather than inventorying every measurable difference" in rendered
