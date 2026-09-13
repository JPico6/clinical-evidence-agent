"""Serializable records for multi-patient live evaluation runs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


EVALUATION_RUN_VERSION = "1.0"


class EvaluationIntentResult(BaseModel):
    """One patient/intent result, including evidence and evaluation checks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["current_state", "trajectory"]
    status: Literal["ok", "error"]
    evidence_bundle: dict[str, Any] | None = None
    selection: dict[str, Any] | None = None
    selected_observation_evidence: dict[str, Any] | None = None
    synthesis: dict[str, Any] | None = None
    deterministic_evaluation: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


class EvaluationPatientResult(BaseModel):
    """Evaluation results for both supported intents for one cohort patient."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: str
    cohort_label: str
    rationale: str
    profile: dict[str, Any]
    intent_results: tuple[EvaluationIntentResult, ...]


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_count: int
    intent_case_count: int
    successful_intent_cases: int
    failed_intent_cases: int
    deterministic_pass_count: int
    deterministic_fail_count: int


class MultiPatientEvaluationRun(BaseModel):
    """Complete portable artifact for one frozen-pipeline evaluation run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_run_version: str = EVALUATION_RUN_VERSION
    model_name: str
    reasoning_effort: str
    lookback_days: int
    cohort_method: str
    cohort_notes: tuple[str, ...] = Field(default_factory=tuple)
    patients: tuple[EvaluationPatientResult, ...]
    summary: EvaluationRunSummary


def summarize_evaluation_run(
    patients: tuple[EvaluationPatientResult, ...] | list[EvaluationPatientResult],
) -> EvaluationRunSummary:
    """Summarize run execution separately from deterministic pass/fail."""
    patient_count = len(patients)
    intent_results = [
        result
        for patient in patients
        for result in patient.intent_results
    ]
    successful = sum(result.status == "ok" for result in intent_results)
    failed = sum(result.status == "error" for result in intent_results)

    deterministic_pass = 0
    deterministic_fail = 0
    for result in intent_results:
        if result.status != "ok" or result.deterministic_evaluation is None:
            continue
        if result.deterministic_evaluation.get("passed") is True:
            deterministic_pass += 1
        else:
            deterministic_fail += 1

    return EvaluationRunSummary(
        patient_count=patient_count,
        intent_case_count=len(intent_results),
        successful_intent_cases=successful,
        failed_intent_cases=failed,
        deterministic_pass_count=deterministic_pass,
        deterministic_fail_count=deterministic_fail,
    )
