from unittest.mock import Mock

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from clinical_evidence_agent.evidence_graph import (
    EvidenceToolCall,
    build_deterministic_evidence_graph,
    execute_evidence_tool_plan,
)


class _LookbackToolInput(BaseModel):
    """Test-only schema matching the graph arguments used in these tests."""

    patient_id: str = Field(..., min_length=1)
    lookback_days: int = Field(365, gt=0)


def _tool(name, response):
    def func(patient_id: str, lookback_days: int = 365):
        return {
            **response,
            "received": {
                "patient_id": patient_id,
                "lookback_days": lookback_days,
            },
        }

    return StructuredTool.from_function(
        func=func,
        name=name,
        description=f"Deterministic test tool {name}.",
        args_schema=_LookbackToolInput,
    )


def test_execute_plan_preserves_order_arguments_and_results():
    tool_map = {
        "conditions": _tool("conditions", {"status": "ok", "domain": "conditions"}),
        "procedures": _tool("procedures", {"status": "ok", "domain": "procedures"}),
    }

    results = execute_evidence_tool_plan(
        patient_id="patient-1",
        tool_calls=[
            {"tool_name": "conditions", "arguments": {"lookback_days": 365}},
            EvidenceToolCall(
                tool_name="procedures",
                arguments={"lookback_days": 90},
            ),
        ],
        tool_map=tool_map,
    )

    assert [item["tool_name"] for item in results] == ["conditions", "procedures"]
    assert results[0]["arguments"] == {
        "patient_id": "patient-1",
        "lookback_days": 365,
    }
    assert results[1]["evidence"]["received"] == {
        "patient_id": "patient-1",
        "lookback_days": 90,
    }


def test_execute_plan_rejects_unknown_tools_fail_closed():
    with pytest.raises(ValueError, match="Unknown evidence tool"):
        execute_evidence_tool_plan(
            patient_id="patient-1",
            tool_calls=[{"tool_name": "not_registered", "arguments": {}}],
            tool_map={},
        )


def test_execute_plan_rejects_cross_patient_tool_call():
    tool_map = {"conditions": _tool("conditions", {"status": "ok"})}

    with pytest.raises(ValueError, match="must match"):
        execute_evidence_tool_plan(
            patient_id="patient-1",
            tool_calls=[
                {
                    "tool_name": "conditions",
                    "arguments": {"patient_id": "patient-2"},
                }
            ],
            tool_map=tool_map,
        )


def test_execute_plan_allows_empty_plan():
    assert execute_evidence_tool_plan(
        patient_id="patient-1",
        tool_calls=[],
        tool_map={},
    ) == []


def test_graph_executes_supplied_plan_without_selecting_tools(monkeypatch):
    condition_tool = _tool("get_condition_evidence", {"status": "ok"})
    tool_map = {"get_condition_evidence": condition_tool}

    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_graph.get_langchain_evidence_tool_map",
        lambda toolset: tool_map,
    )

    graph = build_deterministic_evidence_graph(Mock())
    result = graph.invoke(
        {
            "patient_id": "patient-1",
            "tool_calls": [
                {
                    "tool_name": "get_condition_evidence",
                    "arguments": {"lookback_days": 365},
                }
            ],
        }
    )

    assert result["patient_id"] == "patient-1"
    assert result["tool_calls"][0]["tool_name"] == "get_condition_evidence"
    assert result["tool_results"][0]["tool_name"] == "get_condition_evidence"
    assert result["tool_results"][0]["evidence"]["received"] == {
        "patient_id": "patient-1",
        "lookback_days": 365,
    }
