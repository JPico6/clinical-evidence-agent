"""Thin LangChain adapters over the deterministic evidence API.

This module contains no clinical evidence logic and no LLM orchestration.  It
only exposes :class:`EvidenceToolset` methods as LangChain StructuredTools with
explicit Pydantic input schemas and descriptions derived from the deterministic
contracts.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from clinical_evidence_agent.evidence_tools import (
    EVIDENCE_TOOL_CONTRACTS,
    EvidenceToolContract,
    EvidenceToolset,
)


class PatientEvidenceInput(BaseModel):
    """Input for evidence tools that only require a patient identifier."""

    patient_id: str = Field(
        ...,
        min_length=1,
        description="Exact source patient identifier to retrieve evidence for.",
    )


class PatientLookbackEvidenceInput(BaseModel):
    """Input for patient evidence tools with a patient-relative lookback."""

    patient_id: str = Field(
        ...,
        min_length=1,
        description="Exact source patient identifier to retrieve evidence for.",
    )
    lookback_days: int = Field(
        365,
        gt=0,
        description=(
            "Positive patient-relative lookback in days, anchored to the "
            "patient's latest observed event rather than the current date."
        ),
    )


class LabEvidenceInput(BaseModel):
    """Input for deterministic numeric laboratory evidence."""

    patient_id: str = Field(
        ...,
        min_length=1,
        description="Exact source patient identifier to retrieve evidence for.",
    )
    code: str = Field(
        ...,
        min_length=1,
        description=(
            "Exact source laboratory code. The tool does not infer a code from "
            "a laboratory name."
        ),
    )
    unit: str | None = Field(
        None,
        description=(
            "Exact source unit to analyze when a laboratory code has multiple "
            "units. Leave null only when unit selection is unnecessary."
        ),
    )


def _render_tool_description(contract: EvidenceToolContract) -> str:
    """Render one model-facing description from the canonical contract."""
    limitations = " ".join(
        f"Limitation: {item}" for item in contract.limitations
    )
    return (
        f"{contract.purpose} Returns: {contract.returns} "
        f"{limitations} Return the deterministic evidence as-is; do not use "
        "this tool to infer facts outside its stated evidence contract."
    )


def _structured_tool(
    *,
    name: str,
    func: Callable[..., dict[str, Any]],
    args_schema: type[BaseModel],
) -> StructuredTool:
    contract = EVIDENCE_TOOL_CONTRACTS[name]
    return StructuredTool.from_function(
        func=func,
        name=name,
        description=_render_tool_description(contract),
        args_schema=args_schema,
    )


def build_langchain_evidence_tools(toolset: EvidenceToolset) -> list[BaseTool]:
    """Build the six model-facing LangChain tools for one evidence toolset.

    The returned tools delegate directly to ``EvidenceToolset`` methods.  They
    do not modify, summarize, reinterpret, or enrich deterministic evidence.
    """
    return [
        _structured_tool(
            name="get_utilization_evidence",
            func=toolset.get_utilization_evidence,
            args_schema=PatientEvidenceInput,
        ),
        _structured_tool(
            name="get_lab_evidence",
            func=toolset.get_lab_evidence,
            args_schema=LabEvidenceInput,
        ),
        _structured_tool(
            name="get_condition_evidence",
            func=toolset.get_condition_evidence,
            args_schema=PatientLookbackEvidenceInput,
        ),
        _structured_tool(
            name="get_medication_evidence",
            func=toolset.get_medication_evidence,
            args_schema=PatientLookbackEvidenceInput,
        ),
        _structured_tool(
            name="get_procedure_evidence",
            func=toolset.get_procedure_evidence,
            args_schema=PatientLookbackEvidenceInput,
        ),
        _structured_tool(
            name="get_recent_event_evidence",
            func=toolset.get_recent_event_evidence,
            args_schema=PatientLookbackEvidenceInput,
        ),
    ]


def get_langchain_evidence_tool_map(
    toolset: EvidenceToolset,
) -> dict[str, BaseTool]:
    """Return LangChain evidence tools keyed by their stable contract names."""
    tools = build_langchain_evidence_tools(toolset)
    return {tool.name: tool for tool in tools}
