"""Deterministic LangGraph orchestration foundation.

This module defines graph state and tool-execution plumbing without an LLM.
Tool selection is supplied explicitly as a deterministic execution plan.  A
future model-routing node can produce the same plan shape without changing the
execution boundary.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.langchain_tools import get_langchain_evidence_tool_map


class EvidenceToolCall(BaseModel):
    """One explicit request to invoke a registered deterministic evidence tool."""

    tool_name: str = Field(..., min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class EvidenceToolResult(TypedDict):
    """Provenance-preserving result from one evidence-tool invocation."""

    tool_name: str
    arguments: dict[str, Any]
    evidence: dict[str, Any]


class EvidenceGraphState(TypedDict, total=False):
    """State carried by the deterministic evidence execution graph."""

    patient_id: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[EvidenceToolResult]


def _normalize_tool_call(raw_call: dict[str, Any] | EvidenceToolCall) -> EvidenceToolCall:
    if isinstance(raw_call, EvidenceToolCall):
        return raw_call
    return EvidenceToolCall.model_validate(raw_call)


def _validate_patient_scope(patient_id: str, call: EvidenceToolCall) -> dict[str, Any]:
    """Bind every tool call to the graph's patient and reject cross-patient plans."""
    arguments = dict(call.arguments)
    supplied_patient_id = arguments.get("patient_id")
    if supplied_patient_id is not None and supplied_patient_id != patient_id:
        raise ValueError(
            "tool call patient_id must match the graph state's patient_id"
        )
    arguments["patient_id"] = patient_id
    return arguments


def execute_evidence_tool_plan(
    *,
    patient_id: str,
    tool_calls: list[dict[str, Any] | EvidenceToolCall],
    tool_map: dict[str, BaseTool],
) -> list[EvidenceToolResult]:
    """Execute an explicit deterministic evidence-tool plan in order.

    This function contains no routing heuristics and no LLM behavior. Unknown
    tools fail closed. Every invocation is bound to the state's patient ID, and
    each result retains the invoked tool name and exact arguments for later
    provenance/evaluation.
    """
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("patient_id must be a non-empty string")
    patient_id = patient_id.strip()

    results: list[EvidenceToolResult] = []
    for raw_call in tool_calls:
        call = _normalize_tool_call(raw_call)
        if call.tool_name not in tool_map:
            raise ValueError(f"Unknown evidence tool: {call.tool_name}")

        arguments = _validate_patient_scope(patient_id, call)
        evidence = tool_map[call.tool_name].invoke(arguments)
        results.append(
            {
                "tool_name": call.tool_name,
                "arguments": arguments,
                "evidence": evidence,
            }
        )
    return results


def build_deterministic_evidence_graph(toolset: EvidenceToolset):
    """Build a one-node LangGraph that executes a supplied evidence-tool plan.

    The graph deliberately does not choose tools. A future routing node may
    populate ``tool_calls``; this executor remains the trusted deterministic
    boundary beneath that decision.
    """
    tool_map = get_langchain_evidence_tool_map(toolset)

    def execute_tools(state: EvidenceGraphState) -> dict[str, Any]:
        patient_id = state.get("patient_id")
        if not isinstance(patient_id, str) or not patient_id.strip():
            raise ValueError("graph state patient_id must be a non-empty string")

        raw_calls = state.get("tool_calls", [])
        results = execute_evidence_tool_plan(
            patient_id=patient_id,
            tool_calls=raw_calls,
            tool_map=tool_map,
        )
        return {"tool_results": results}

    builder = StateGraph(EvidenceGraphState)
    builder.add_node("execute_tools", execute_tools)
    builder.add_edge(START, "execute_tools")
    builder.add_edge("execute_tools", END)
    return builder.compile()
