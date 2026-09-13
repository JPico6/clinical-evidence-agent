from clinical_evidence_agent.evaluation_run import (
    EVALUATION_RUN_VERSION,
    EvaluationIntentResult,
    EvaluationPatientResult,
    MultiPatientEvaluationRun,
    summarize_evaluation_run,
)


def _patient(patient_id="p1", *, current_ok=True, trajectory_ok=True):
    current = EvaluationIntentResult(
        intent="current_state",
        status="ok" if current_ok else "error",
        deterministic_evaluation={"passed": True} if current_ok else None,
        error_type=None if current_ok else "RuntimeError",
        error_message=None if current_ok else "failed",
    )
    trajectory = EvaluationIntentResult(
        intent="trajectory",
        status="ok" if trajectory_ok else "error",
        deterministic_evaluation={"passed": False} if trajectory_ok else None,
        error_type=None if trajectory_ok else "RuntimeError",
        error_message=None if trajectory_ok else "failed",
    )
    return EvaluationPatientResult(
        patient_id=patient_id,
        cohort_label="test",
        rationale="test rationale",
        profile={"anchor_date": "2026-01-01"},
        intent_results=(current, trajectory),
    )


def test_summary_counts_execution_and_deterministic_results_separately():
    summary = summarize_evaluation_run((_patient(),))

    assert summary.patient_count == 1
    assert summary.intent_case_count == 2
    assert summary.successful_intent_cases == 2
    assert summary.failed_intent_cases == 0
    assert summary.deterministic_pass_count == 1
    assert summary.deterministic_fail_count == 1


def test_summary_records_failed_execution_without_calling_it_deterministic_failure():
    summary = summarize_evaluation_run((_patient(current_ok=False),))

    assert summary.successful_intent_cases == 1
    assert summary.failed_intent_cases == 1
    assert summary.deterministic_pass_count == 0
    assert summary.deterministic_fail_count == 1


def test_multi_patient_run_defaults_version():
    patients = (_patient(),)
    run = MultiPatientEvaluationRun(
        model_name="test-model",
        reasoning_effort="medium",
        lookback_days=365,
        cohort_method="deterministic test",
        patients=patients,
        summary=summarize_evaluation_run(patients),
    )

    assert run.evaluation_run_version == EVALUATION_RUN_VERSION
    assert run.summary.intent_case_count == 2


def test_intent_error_record_does_not_require_evidence_payloads():
    result = EvaluationIntentResult(
        intent="trajectory",
        status="error",
        error_type="ValueError",
        error_message="bad case",
    )

    assert result.evidence_bundle is None
    assert result.synthesis is None
    assert result.deterministic_evaluation is None
