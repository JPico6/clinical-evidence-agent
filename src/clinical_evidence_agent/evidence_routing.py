"""Deterministic evidence routing for the initial clinical synthesis tasks.

Version 1 intentionally supports two explicit tasks only:

* ``CURRENT_STATE``: describe the patient's current medical situation.
* ``TRAJECTORY``: explain how the patient's medical situation is changing.

The task itself determines the core evidence plan.  No LLM is required to
choose among the core evidence tools.  Laboratory evidence remains conditional
because the lab contract requires an explicit source code (and sometimes a
unit); this module never invents a lab code from a natural-language concept.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from clinical_evidence_agent.evidence_graph import EvidenceToolCall


DEFAULT_LOOKBACK_DAYS = 365


class ClinicalEvidenceIntent(StrEnum):
    """Supported patient-level synthesis tasks for the initial agent."""

    CURRENT_STATE = "current_state"
    TRAJECTORY = "trajectory"


class EvidencePlan(BaseModel):
    """Auditable deterministic evidence plan for one supported task."""

    model_config = ConfigDict(frozen=True)

    intent: ClinicalEvidenceIntent
    tool_calls: tuple[EvidenceToolCall, ...]
    conditional_tools: tuple[str, ...] = Field(default_factory=tuple)
    routing_notes: tuple[str, ...] = Field(default_factory=tuple)


def _validate_lookback_days(lookback_days: int) -> int:
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise ValueError("lookback_days must be a positive integer")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be a positive integer")
    return lookback_days


def _lookback_call(tool_name: str, lookback_days: int) -> EvidenceToolCall:
    return EvidenceToolCall(
        tool_name=tool_name,
        arguments={"lookback_days": lookback_days},
    )


def build_evidence_plan(
    intent: ClinicalEvidenceIntent | str,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> EvidencePlan:
    """Return the fixed core evidence plan for a supported synthesis task.

    ``patient_id`` is deliberately absent from tool-call arguments. The
    deterministic executor binds every call to the graph state's patient ID.

    The lab tool is deliberately not called here.  Lab evidence requires a
    known source code and, for some codes, an explicit unit.  A later
    evidence-selection step may add a lab call only when that information is
    grounded rather than guessed.
    """
    lookback_days = _validate_lookback_days(lookback_days)
    intent = ClinicalEvidenceIntent(intent)

    shared_calls = (
        _lookback_call("get_condition_evidence", lookback_days),
        _lookback_call("get_medication_evidence", lookback_days),
        _lookback_call("get_procedure_evidence", lookback_days),
        _lookback_call("get_recent_event_evidence", lookback_days),
    )

    if intent is ClinicalEvidenceIntent.CURRENT_STATE:
        calls = (
            *shared_calls,
            EvidenceToolCall(
                tool_name="get_utilization_evidence",
                arguments={},
            ),
        )
        notes = (
            "Core current-state evidence is retrieved deterministically rather than selected by an LLM.",
            "Source-open conditions or medications must not be reinterpreted as clinically active/current.",
            "Laboratory evidence is conditional because a source lab code must be grounded explicitly.",
        )
    else:
        calls = (
            _lookback_call("get_recent_event_evidence", lookback_days),
            EvidenceToolCall(
                tool_name="get_utilization_evidence",
                arguments={},
            ),
            _lookback_call("get_condition_evidence", lookback_days),
            _lookback_call("get_medication_evidence", lookback_days),
            _lookback_call("get_procedure_evidence", lookback_days),
        )
        notes = (
            "Trajectory evidence prioritizes recent cross-domain events and deterministic change-over-time signals.",
            "Numeric or utilization change does not by itself establish clinical improvement or worsening.",
            "Laboratory trajectory is conditional because a source lab code must be grounded explicitly.",
        )

    return EvidencePlan(
        intent=intent,
        tool_calls=calls,
        conditional_tools=("get_lab_evidence",),
        routing_notes=notes,
    )
