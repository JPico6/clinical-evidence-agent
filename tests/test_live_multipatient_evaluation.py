import json

from clinical_evidence_agent.evaluation_run import (
    EvaluationIntentResult,
    EvaluationPatientResult,
    MultiPatientEvaluationRun,
    summarize_evaluation_run,
)
from clinical_evidence_agent.live_multipatient_evaluation import (
    COHORT_METHOD,
    COHORT_NOTES,
    write_evaluation_artifact,
)


def _run():
    patient = EvaluationPatientResult(
        patient_id="p1",
        cohort_label="sparse_record",
        rationale="Sparse evidence.",
        profile={"anchor_date": "2026-01-01"},
        intent_results=(
            EvaluationIntentResult(
                intent="current_state",
                status="ok",
                evidence_bundle={"patient_id": "p1"},
                selection={"intent": "current_state"},
                selected_observation_evidence={"selected_observation_count": 0},
                synthesis={"intent": "current_state"},
                deterministic_evaluation={"passed": True},
            ),
            EvaluationIntentResult(
                intent="trajectory",
                status="ok",
                evidence_bundle={"patient_id": "p1"},
                selection={"intent": "trajectory"},
                selected_observation_evidence={"selected_observation_count": 0},
                synthesis={"intent": "trajectory"},
                deterministic_evaluation={"passed": True},
            ),
        ),
    )
    patients = (patient,)
    return MultiPatientEvaluationRun(
        model_name="test-model",
        reasoning_effort="medium",
        lookback_days=365,
        cohort_method=COHORT_METHOD,
        cohort_notes=COHORT_NOTES,
        patients=patients,
        summary=summarize_evaluation_run(patients),
    )


def test_artifact_writer_retains_evidence_and_outputs(tmp_path):
    path = write_evaluation_artifact(_run(), tmp_path / "run.json")
    payload = json.loads(path.read_text())

    result = payload["patients"][0]["intent_results"][0]
    assert result["evidence_bundle"]["patient_id"] == "p1"
    assert result["selection"]["intent"] == "current_state"
    assert result["synthesis"]["intent"] == "current_state"
    assert result["deterministic_evaluation"]["passed"] is True


def test_artifact_documents_cohort_semantics(tmp_path):
    path = write_evaluation_artifact(_run(), tmp_path / "run.json")
    payload = json.loads(path.read_text())

    assert "remaining patient" in payload["cohort_method"]
    assert any("not clinical severity" in note for note in payload["cohort_notes"])
    assert any("patient-relative" in note for note in payload["cohort_notes"])
