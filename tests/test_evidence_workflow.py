from unittest.mock import Mock

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from clinical_evidence_agent.evidence_routing import DEFAULT_LOOKBACK_DAYS
from clinical_evidence_agent.evidence_workflow import (
    assemble_evidence_bundle,
    build_clinical_evidence_workflow,
)


class _LookbackInput(BaseModel):
    patient_id: str = Field(..., min_length=1)
    lookback_days: int = Field(365, gt=0)


class _PatientInput(BaseModel):
    patient_id: str = Field(..., min_length=1)


def _lookback_tool(name):
    def func(patient_id: str, lookback_days: int = 365):
        return {
            "status": "ok",
            "tool": name,
            "patient_id": patient_id,
            "lookback_days": lookback_days,
        }

    return StructuredTool.from_function(
        func=func,
        name=name,
        description=f"Test tool {name}.",
        args_schema=_LookbackInput,
    )


def _patient_tool(name):
    def func(patient_id: str):
        return {
            "status": "ok",
            "tool": name,
            "patient_id": patient_id,
        }

    return StructuredTool.from_function(
        func=func,
        name=name,
        description=f"Test tool {name}.",
        args_schema=_PatientInput,
    )


def _tool_map():
    return {
        "get_condition_evidence": _lookback_tool("get_condition_evidence"),
        "get_medication_evidence": _lookback_tool("get_medication_evidence"),
        "get_procedure_evidence": _lookback_tool("get_procedure_evidence"),
        "get_recent_event_evidence": _lookback_tool("get_recent_event_evidence"),
        "get_utilization_evidence": _patient_tool("get_utilization_evidence"),
    }


def test_current_state_workflow_routes_executes_and_bundles(monkeypatch):
    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_workflow.get_langchain_evidence_tool_map",
        lambda toolset: _tool_map(),
    )
    graph = build_clinical_evidence_workflow(Mock())

    result = graph.invoke({"patient_id": "patient-1", "intent": "current_state"})
    bundle = result["evidence_bundle"]

    assert bundle["patient_id"] == "patient-1"
    assert bundle["intent"] == "current_state"
    assert bundle["lookback_days"] == DEFAULT_LOOKBACK_DAYS
    assert list(bundle["evidence_by_tool"]) == [
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
        "get_recent_event_evidence",
        "get_utilization_evidence",
    ]
    assert bundle["evidence_by_tool"]["get_condition_evidence"]["patient_id"] == "patient-1"


def test_trajectory_workflow_preserves_fixed_priority_and_custom_lookback(monkeypatch):
    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_workflow.get_langchain_evidence_tool_map",
        lambda toolset: _tool_map(),
    )
    graph = build_clinical_evidence_workflow(Mock())

    result = graph.invoke(
        {
            "patient_id": "patient-1",
            "intent": "trajectory",
            "lookback_days": 180,
        }
    )
    bundle = result["evidence_bundle"]

    assert [item["tool_name"] for item in bundle["tool_results"]] == [
        "get_recent_event_evidence",
        "get_utilization_evidence",
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
    ]
    assert bundle["evidence_by_tool"]["get_condition_evidence"]["lookback_days"] == 180


def test_workflow_does_not_execute_conditional_lab_tool(monkeypatch):
    tool_map = _tool_map()
    lab = Mock()
    tool_map["get_lab_evidence"] = lab
    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_workflow.get_langchain_evidence_tool_map",
        lambda toolset: tool_map,
    )
    graph = build_clinical_evidence_workflow(Mock())

    result = graph.invoke({"patient_id": "patient-1", "intent": "current_state"})

    assert result["evidence_bundle"]["conditional_tools"] == ["get_lab_evidence"]
    lab.invoke.assert_not_called()


def test_workflow_rejects_unsupported_intent_before_tool_execution(monkeypatch):
    tool_map = _tool_map()
    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_workflow.get_langchain_evidence_tool_map",
        lambda toolset: tool_map,
    )
    graph = build_clinical_evidence_workflow(Mock())

    with pytest.raises(ValueError):
        graph.invoke({"patient_id": "patient-1", "intent": "care_plan"})


def test_workflow_rejects_missing_patient_id(monkeypatch):
    monkeypatch.setattr(
        "clinical_evidence_agent.evidence_workflow.get_langchain_evidence_tool_map",
        lambda toolset: _tool_map(),
    )
    graph = build_clinical_evidence_workflow(Mock())

    with pytest.raises(ValueError, match="patient_id"):
        graph.invoke({"intent": "current_state"})


def test_bundle_preserves_underlying_evidence_objects():
    evidence = {"status": "ok", "nested": {"value": 7}}
    tool_results = [
        {
            "tool_name": "get_condition_evidence",
            "arguments": {"patient_id": "patient-1", "lookback_days": 365},
            "evidence": evidence,
        }
    ]

    bundle = assemble_evidence_bundle(
        patient_id="patient-1",
        intent="current_state",
        lookback_days=365,
        routing_notes=["note"],
        conditional_tools=["get_lab_evidence"],
        tool_results=tool_results,
    )

    assert bundle["tool_results"] is tool_results
    assert bundle["evidence_by_tool"]["get_condition_evidence"] is evidence
