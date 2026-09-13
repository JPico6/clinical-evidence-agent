"""Evaluation records and deterministic checks for synthesized answers.

These checks intentionally cover properties that can be verified without an
LLM judge.  Semantic faithfulness, clinical salience, and readability remain
separate later evaluation dimensions rather than being disguised as rules.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    MAX_CURRENT_STATE_FINDINGS,
    MAX_TRAJECTORY_CHANGES,
    TrajectorySynthesis,
    validate_synthesis_against_bundle,
)


class DeterministicEvaluationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    passed: bool
    detail: str


class DeterministicSynthesisEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: str
    intent: str
    passed: bool
    checks: tuple[DeterministicEvaluationCheck, ...]


def _statement_texts(synthesis) -> list[str]:
    texts = [synthesis.overall_assessment.statement]
    if isinstance(synthesis, CurrentStateSynthesis):
        texts.extend(f.statement for f in synthesis.findings)
    else:
        texts.extend(f.statement for f in synthesis.changes)
    texts.extend(f.statement for f in synthesis.uncertainties)
    return texts


def evaluate_synthesis_deterministically(
    *,
    synthesis,
    bundle: dict[str, Any],
) -> DeterministicSynthesisEvaluation:
    """Evaluate only mechanically testable synthesis properties."""
    checks: list[DeterministicEvaluationCheck] = []

    try:
        validate_synthesis_against_bundle(synthesis, bundle)
    except (ValueError, TypeError) as error:
        citation_passed = False
        citation_detail = str(error)
    else:
        citation_passed = True
        citation_detail = "All evidence references resolve within the supplied bundle."
    checks.append(
        DeterministicEvaluationCheck(
            name="citation_validity",
            passed=citation_passed,
            detail=citation_detail,
        )
    )

    expected_intent = bundle["intent"]
    actual_intent = synthesis.intent.value
    checks.append(
        DeterministicEvaluationCheck(
            name="intent_match",
            passed=actual_intent == expected_intent,
            detail=f"synthesis={actual_intent!r}, bundle={expected_intent!r}",
        )
    )

    if isinstance(synthesis, CurrentStateSynthesis):
        count = len(synthesis.findings)
        limit = MAX_CURRENT_STATE_FINDINGS
        count_label = "findings"
    elif isinstance(synthesis, TrajectorySynthesis):
        count = len(synthesis.changes)
        limit = MAX_TRAJECTORY_CHANGES
        count_label = "changes"
    else:
        raise TypeError(f"unsupported synthesis type: {type(synthesis).__name__}")

    checks.append(
        DeterministicEvaluationCheck(
            name="answer_shape_limit",
            passed=count <= limit,
            detail=f"{count_label}={count}, limit={limit}",
        )
    )

    statements = _statement_texts(synthesis)
    normalized = [statement.strip().casefold() for statement in statements]
    checks.append(
        DeterministicEvaluationCheck(
            name="no_duplicate_statements",
            passed=len(normalized) == len(set(normalized)),
            detail=f"statement_count={len(statements)}",
        )
    )

    patient_id = str(bundle["patient_id"])
    leaked_patient_id = any(patient_id in statement for statement in statements)
    checks.append(
        DeterministicEvaluationCheck(
            name="no_patient_id_leakage",
            passed=not leaked_patient_id,
            detail=(
                "Patient identifier not present in synthesis text."
                if not leaked_patient_id
                else "Patient identifier appeared in synthesis text."
            ),
        )
    )

    return DeterministicSynthesisEvaluation(
        patient_id=patient_id,
        intent=actual_intent,
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
    )
