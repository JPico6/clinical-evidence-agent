from clinical_evidence_agent.llm_synthesis import build_synthesis_messages


def _bundle(intent="trajectory"):
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
                "newly_observed_conditions": [
                    {"description": "Atrial fibrillation"},
                    {"description": "Lost dental filling"},
                ],
            },
            "get_selected_numeric_observation_evidence": {
                "status": "ok",
                "selected_observation_count": 1,
                "observations": [
                    {
                        "code": "8867-4",
                        "unit": "/min",
                        "evidence": {
                            "change": {"median_absolute": 5.0},
                        },
                    }
                ],
            },
        },
    }


def test_prompt_applies_materiality_threshold():
    messages = build_synthesis_messages(_bundle())
    rendered = "\n".join(str(message.content) for message in messages).lower()

    assert "apply a materiality threshold" in rendered
    assert "materially helps answer the user's question" in rendered
    assert "removal would not meaningfully change" in rendered
    assert "fewer findings is preferable" in rendered
    assert "peripheral events" in rendered


def test_prompt_forbids_weak_replacement_filler():
    messages = build_synthesis_messages(_bundle())
    rendered = "\n".join(str(message.content) for message in messages).lower()

    assert "do not replace an omitted peripheral event with a weak numeric change" in rendered


def test_trajectory_task_explicitly_prefers_fewer_material_changes():
    messages = build_synthesis_messages(_bundle("trajectory"))
    rendered = "\n".join(str(message.content) for message in messages).lower()

    assert "include only changes that materially affect understanding" in rendered
    assert "fewer changes are preferable to peripheral filler" in rendered
