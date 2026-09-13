"""End-to-end deterministic evidence workflow for supported synthesis tasks.

The workflow connects the fixed task router to the tested LangChain tool
executor and assembles one provenance-preserving evidence bundle.  It contains
no LLM calls and performs no clinical interpretation.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from clinical_evidence_agent.evidence_graph import (
    EvidenceToolResult,
    execute_evidence_tool_plan,
)
from clinical_evidence_agent.evidence_routing import (
    ClinicalEvidenceIntent,
    DEFAULT_LOOKBACK_DAYS,
    build_evidence_plan,
)
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.langchain_tools import get_langchain_evidence_tool_map


class ClinicalEvidenceBundle(TypedDict):
    """Deterministic evidence package handed to a future synthesis layer."""

    patient_id: str
    intent: str
    lookback_days: int
    routing_notes: list[str]
    conditional_tools: list[str]
    tool_results: list[EvidenceToolResult]
    evidence_by_tool: dict[str, dict[str, Any]]


class ClinicalEvidenceWorkflowState(TypedDict, total=False):
    """LangGraph state for deterministic task routing and evidence retrieval."""

    patient_id: str
    intent: str
    lookback_days: int
    tool_calls: list[dict[str, Any]]
    routing_notes: list[str]
    conditional_tools: list[str]
    tool_results: list[EvidenceToolResult]
    evidence_bundle: ClinicalEvidenceBundle


def _serialize_tool_calls(plan) -> list[dict[str, Any]]:
    return [call.model_dump() for call in plan.tool_calls]


def assemble_evidence_bundle(
    *,
    patient_id: str,
    intent: ClinicalEvidenceIntent | str,
    lookback_days: int,
    routing_notes: list[str],
    conditional_tools: list[str],
    tool_results: list[EvidenceToolResult],
) -> ClinicalEvidenceBundle:
    """Assemble retrieval outputs without modifying any evidence payload."""
    intent_value = ClinicalEvidenceIntent(intent).value
    evidence_by_tool = {
        result["tool_name"]: result["evidence"] for result in tool_results
    }
    return {
        "patient_id": patient_id,
        "intent": intent_value,
        "lookback_days": lookback_days,
        "routing_notes": list(routing_notes),
        "conditional_tools": list(conditional_tools),
        "tool_results": tool_results,
        "evidence_by_tool": evidence_by_tool,
    }


def build_clinical_evidence_workflow(toolset: EvidenceToolset):
    """Build deterministic ``route -> execute -> bundle`` LangGraph workflow.

    Inputs are ``patient_id``, a supported synthesis ``intent``, and optional
    ``lookback_days``.  The router selects the fixed evidence plan, the executor
    binds all calls to the same patient, and the final node assembles the raw
    deterministic results for a future synthesis layer.
    """
    tool_map = get_langchain_evidence_tool_map(toolset)

    def route(state: ClinicalEvidenceWorkflowState) -> dict[str, Any]:
        lookback_days = state.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
        plan = build_evidence_plan(
            state.get("intent", ""),
            lookback_days=lookback_days,
        )
        return {
            "intent": plan.intent.value,
            "lookback_days": lookback_days,
            "tool_calls": _serialize_tool_calls(plan),
            "routing_notes": list(plan.routing_notes),
            "conditional_tools": list(plan.conditional_tools),
        }

    def execute(state: ClinicalEvidenceWorkflowState) -> dict[str, Any]:
        patient_id = state.get("patient_id")
        if not isinstance(patient_id, str) or not patient_id.strip():
            raise ValueError("graph state patient_id must be a non-empty string")
        return {
            "tool_results": execute_evidence_tool_plan(
                patient_id=patient_id,
                tool_calls=state.get("tool_calls", []),
                tool_map=tool_map,
            )
        }

    def bundle(state: ClinicalEvidenceWorkflowState) -> dict[str, Any]:
        patient_id = state.get("patient_id")
        if not isinstance(patient_id, str) or not patient_id.strip():
            raise ValueError("graph state patient_id must be a non-empty string")
        evidence_bundle = assemble_evidence_bundle(
            patient_id=patient_id.strip(),
            intent=state["intent"],
            lookback_days=state["lookback_days"],
            routing_notes=state.get("routing_notes", []),
            conditional_tools=state.get("conditional_tools", []),
            tool_results=state.get("tool_results", []),
        )
        return {"evidence_bundle": evidence_bundle}

    builder = StateGraph(ClinicalEvidenceWorkflowState)
    builder.add_node("route", route)
    builder.add_node("execute", execute)
    builder.add_node("bundle", bundle)
    builder.add_edge(START, "route")
    builder.add_edge("route", "execute")
    builder.add_edge("execute", "bundle")
    builder.add_edge("bundle", END)
    return builder.compile()
