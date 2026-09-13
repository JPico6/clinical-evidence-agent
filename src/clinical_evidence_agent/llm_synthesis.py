"""Constrained LLM synthesis over deterministic clinical evidence bundles.

The model receives only the already-retrieved evidence bundle plus explicit
synthesis guardrails. It cannot call tools, query the database, change patient
scope, or return free-form output outside the task-specific Pydantic contract.

After model generation, every evidence reference is mechanically validated
against the exact bundle before the result is returned.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.evidence_workflow import ClinicalEvidenceBundle
from clinical_evidence_agent.synthesis_contract import (
    ClinicalSynthesis,
    CurrentStateSynthesis,
    TrajectorySynthesis,
    get_synthesis_guardrails,
    validate_synthesis_against_bundle,
)


_SYNTHESIS_TASKS = {
    ClinicalEvidenceIntent.CURRENT_STATE: (
        "Describe the patient's current medical situation using only the supplied deterministic evidence. "
        "Prioritize the most clinically meaningful evidence-supported findings and explicitly preserve important uncertainty."
    ),
    ClinicalEvidenceIntent.TRAJECTORY: (
        "Explain how the patient's medical situation is changing using only the supplied deterministic evidence. "
        "Prioritize evidence-supported changes over time and explicitly preserve important uncertainty."
    ),
}


def get_synthesis_schema(intent: ClinicalEvidenceIntent | str):
    """Return the task-specific structured-output schema."""
    intent = ClinicalEvidenceIntent(intent)
    if intent is ClinicalEvidenceIntent.CURRENT_STATE:
        return CurrentStateSynthesis
    return TrajectorySynthesis


def build_synthesis_messages(
    bundle: ClinicalEvidenceBundle,
) -> list[SystemMessage | HumanMessage]:
    """Build the complete prompt from an already-deterministic evidence bundle."""
    intent = ClinicalEvidenceIntent(bundle["intent"])
    guardrails = get_synthesis_guardrails(intent)

    system_text = "\n".join(
        [
            "You are a clinical evidence synthesis component for a synthetic-data demonstration.",
            "Your job is evidence synthesis, not diagnosis or treatment planning.",
            "Return only the requested structured output.",
            "Guardrails:",
            *(f"- {guardrail}" for guardrail in guardrails),
            "Evidence-reference rules:",
            "- Each evidence reference must use a tool_name present in evidence_by_tool.",
            "- Each evidence-reference path is a JSON path represented as an array of object keys and zero-based array indexes.",
            "- Cite the narrowest concrete evidence item that supports the statement when practical.",
            "- Do not cite routing_notes, conditional_tools, patient_id, intent, or lookback_days as clinical evidence.",
        ]
    )

    # Patient ID is intentionally excluded: synthesis does not need the identifier,
    # and patient scope has already been enforced by deterministic retrieval.
    model_input: dict[str, Any] = {
        "intent": intent.value,
        "task": _SYNTHESIS_TASKS[intent],
        "lookback_days": bundle["lookback_days"],
        "evidence_by_tool": bundle["evidence_by_tool"],
    }
    human_text = (
        "Synthesize the following deterministic evidence bundle.\n\n"
        + json.dumps(model_input, default=str, sort_keys=True, separators=(",", ":"))
    )
    return [SystemMessage(content=system_text), HumanMessage(content=human_text)]


def _build_reference_repair_message(error: ValueError) -> HumanMessage:
    """Ask only for citation repair after structural provenance validation fails."""
    return HumanMessage(
        content=(
            "The previous structured synthesis failed deterministic evidence-reference "
            "validation. Correct the evidence references while preserving only claims "
            "that are supported by the supplied evidence. Do not add new claims merely "
            "to satisfy the validator. Return the complete structured output again.\n\n"
            f"Validation error: {error}"
        )
    )


def synthesize_evidence_bundle(
    *,
    model: BaseChatModel,
    bundle: ClinicalEvidenceBundle,
    max_reference_repairs: int = 1,
) -> ClinicalSynthesis:
    """Generate and validate one constrained synthesis.

    The supplied model is dependency-injected so model configuration remains
    outside this evidence boundary and tests do not require a network call.
    """
    if isinstance(max_reference_repairs, bool) or not isinstance(max_reference_repairs, int):
        raise TypeError("max_reference_repairs must be a nonnegative integer")
    if max_reference_repairs < 0:
        raise ValueError("max_reference_repairs must be nonnegative")

    intent = ClinicalEvidenceIntent(bundle["intent"])
    schema = get_synthesis_schema(intent)
    structured_model = model.with_structured_output(schema)
    messages = build_synthesis_messages(bundle)

    for attempt in range(max_reference_repairs + 1):
        synthesis = structured_model.invoke(messages)

        if not isinstance(synthesis, schema):
            raise TypeError(
                "structured synthesis model returned unexpected type: "
                f"{type(synthesis).__name__}; expected {schema.__name__}"
            )

        try:
            return validate_synthesis_against_bundle(synthesis, bundle)
        except ValueError as error:
            if attempt >= max_reference_repairs:
                raise
            messages = [
                *messages,
                HumanMessage(
                    content=(
                        "Previous structured output (for citation repair only):\n"
                        + synthesis.model_dump_json()
                    )
                ),
                _build_reference_repair_message(error),
            ]

    raise AssertionError("unreachable")
