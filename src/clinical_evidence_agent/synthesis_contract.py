"""Structured, evidence-grounded contracts for future clinical synthesis.

This module defines what a future language model may return for the two
supported synthesis tasks.  It does not call an LLM and it does not interpret
clinical evidence itself.

Every substantive synthesis finding must cite one or more concrete locations
inside the deterministic evidence bundle.  ``validate_synthesis_against_bundle``
checks those references mechanically before a synthesis can be trusted by a
later presentation layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.evidence_workflow import ClinicalEvidenceBundle


EvidencePathPart: TypeAlias = str | int


class EvidenceReference(BaseModel):
    """Pointer to a concrete item inside one executed evidence-tool payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str = Field(..., min_length=1)
    path: tuple[EvidencePathPart, ...] = Field(..., min_length=1)


class SynthesisFinding(BaseModel):
    """One substantive statement with explicit deterministic provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(..., min_length=1)
    evidence_refs: tuple[EvidenceReference, ...] = Field(..., min_length=1)


class CurrentStateSynthesis(BaseModel):
    """Structured answer to: describe the patient's current medical situation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal[ClinicalEvidenceIntent.CURRENT_STATE] = (
        ClinicalEvidenceIntent.CURRENT_STATE
    )
    overall_assessment: SynthesisFinding
    findings: tuple[SynthesisFinding, ...] = Field(default_factory=tuple)
    uncertainties: tuple[SynthesisFinding, ...] = Field(default_factory=tuple)


class TrajectorySynthesis(BaseModel):
    """Structured answer to: explain how the patient's situation is changing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal[ClinicalEvidenceIntent.TRAJECTORY] = ClinicalEvidenceIntent.TRAJECTORY
    overall_assessment: SynthesisFinding
    changes: tuple[SynthesisFinding, ...] = Field(default_factory=tuple)
    uncertainties: tuple[SynthesisFinding, ...] = Field(default_factory=tuple)


ClinicalSynthesis: TypeAlias = CurrentStateSynthesis | TrajectorySynthesis


_SHARED_GUARDRAILS = (
    "Use only facts supported by the deterministic evidence bundle; do not invent missing clinical facts.",
    "Every substantive finding must cite one or more concrete evidence references.",
    "A source-open condition or medication is source provenance and must not be reinterpreted as clinically active or current.",
    "A medication source reason is not a proven indication, and medication records do not establish adherence, persistence, or actual ingestion.",
    "Exact-date cross-domain grouping is descriptive and must not be presented as causal evidence.",
    "Do not infer clinical improvement or worsening from a numeric or utilization change alone.",
    "Do not invent laboratory concepts, codes, units, or values when laboratory evidence was not retrieved.",
    "Represent missing, sparse, conflicting, or ambiguous evidence as uncertainty rather than silently resolving it.",
    "Do not provide a care plan, treatment recommendation, diagnosis, or prescribing recommendation in this synthesis stage.",
)


_INTENT_GUARDRAILS = {
    ClinicalEvidenceIntent.CURRENT_STATE: (
        "Describe the patient's evidence-supported current medical situation without converting historical/source-open records into current diagnoses.",
    ),
    ClinicalEvidenceIntent.TRAJECTORY: (
        "Describe evidence-supported change over time without forcing a single improving/worsening label when the evidence is mixed or insufficient.",
    ),
}


def get_synthesis_guardrails(
    intent: ClinicalEvidenceIntent | str,
) -> tuple[str, ...]:
    """Return auditable instructions for a future structured synthesis call."""
    intent = ClinicalEvidenceIntent(intent)
    return (*_SHARED_GUARDRAILS, *_INTENT_GUARDRAILS[intent])


def _iter_findings(synthesis: ClinicalSynthesis):
    yield synthesis.overall_assessment
    if isinstance(synthesis, CurrentStateSynthesis):
        yield from synthesis.findings
    else:
        yield from synthesis.changes
    yield from synthesis.uncertainties


def _resolve_evidence_path(payload: Any, path: tuple[EvidencePathPart, ...]) -> Any:
    current = payload
    traversed: list[EvidencePathPart] = []
    for part in path:
        if isinstance(part, str):
            if not isinstance(current, Mapping) or part not in current:
                raise ValueError(
                    "evidence path key not found: "
                    f"{part!r} after {tuple(traversed)!r}"
                )
            current = current[part]
            traversed.append(part)
            continue

        if isinstance(part, bool) or not isinstance(part, int):
            raise ValueError("evidence path parts must be strings or integer indexes")
        if not isinstance(current, Sequence) or isinstance(current, (str, bytes, bytearray)):
            raise ValueError(
                "evidence path index cannot be applied here: "
                f"{part} after {tuple(traversed)!r}"
            )
        if part < 0 or part >= len(current):
            raise ValueError(
                "evidence path index out of range: "
                f"{part} after {tuple(traversed)!r}; "
                f"valid indexes are 0..{len(current) - 1}"
            )
        current = current[part]
        traversed.append(part)
    return current


def validate_synthesis_against_bundle(
    synthesis: ClinicalSynthesis,
    bundle: ClinicalEvidenceBundle,
) -> ClinicalSynthesis:
    """Validate intent and every evidence reference against an evidence bundle.

    This is structural validation only.  It proves that cited evidence exists;
    it does not prove that natural-language statements faithfully interpret that
    evidence.  Semantic faithfulness belongs to the later evaluation layer.
    """
    if synthesis.intent.value != bundle["intent"]:
        raise ValueError(
            "synthesis intent does not match evidence bundle intent: "
            f"{synthesis.intent.value!r} != {bundle['intent']!r}"
        )

    evidence_by_tool = bundle["evidence_by_tool"]
    for finding in _iter_findings(synthesis):
        for ref in finding.evidence_refs:
            if ref.tool_name not in evidence_by_tool:
                raise ValueError(
                    f"synthesis cites evidence tool that was not executed: {ref.tool_name!r}"
                )
            _resolve_evidence_path(evidence_by_tool[ref.tool_name], ref.path)

    return synthesis
