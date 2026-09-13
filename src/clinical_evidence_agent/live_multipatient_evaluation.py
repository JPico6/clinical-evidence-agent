"""Run the frozen enriched-synthesis pipeline across a heterogeneous cohort.

This runner is intentionally an evaluation harness, not a new agent layer.
It reuses the existing deterministic workflow, constrained numeric-observation
selector, deterministic retrieval, frozen synthesis prompt, and mechanical
synthesis checks.

A run writes a JSON artifact containing the exact evidence bundle, selector
output, retrieved numeric evidence, synthesis, and deterministic evaluation for
every patient/intent case.  One failed case is recorded and does not prevent the
remaining cohort from running.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from clinical_evidence_agent import database
from clinical_evidence_agent.evaluation import evaluate_synthesis_deterministically
from clinical_evidence_agent.evaluation_cohort import (
    DEFAULT_EVALUATION_COHORT_SIZE,
    build_all_patient_evaluation_profiles,
    select_heterogeneous_evaluation_cohort,
)
from clinical_evidence_agent.evaluation_run import (
    EvaluationIntentResult,
    EvaluationPatientResult,
    MultiPatientEvaluationRun,
    summarize_evaluation_run,
)
from clinical_evidence_agent.evidence_routing import (
    ClinicalEvidenceIntent,
    DEFAULT_LOOKBACK_DAYS,
)
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.evidence_workflow import build_clinical_evidence_workflow
from clinical_evidence_agent.lab_selection import select_numeric_observations
from clinical_evidence_agent.live_experiment import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    REFERENCE_PATIENT_ID,
    create_openai_model,
)
from clinical_evidence_agent.llm_synthesis import synthesize_evidence_bundle
from clinical_evidence_agent.selected_observation_evidence import (
    enrich_evidence_bundle_with_selected_observations,
    retrieve_selected_observation_evidence,
)


DEFAULT_EVALUATION_OUTPUT = Path("evaluation_runs/multipatient_evaluation.json")

COHORT_METHOD = (
    "Greedy deterministic record-shape selection with patient uniqueness; "
    "the reference patient is retained first, then each axis selects the "
    "highest/lowest remaining patient rather than claiming a global clinical rank."
)

COHORT_NOTES = (
    "The cohort is designed to stress evidence shapes, not to estimate clinical prevalence or model performance in a representative population.",
    "Cohort labels such as procedure_heavy and medication_heavy describe deterministic record shape, not clinical severity.",
    "Patient timelines are anchored to each patient's latest observed event; older calendar-year anchors are valid patient-relative evaluation cases.",
    "The synthesis behavior is frozen for this evaluation run; this harness does not modify prompts, retrieval semantics, or evidence contracts.",
)


def run_one_evaluation_intent(
    *,
    con,
    workflow,
    toolset: EvidenceToolset,
    model,
    patient_id: str,
    intent: ClinicalEvidenceIntent,
    lookback_days: int,
) -> EvaluationIntentResult:
    """Run one complete patient/intent case and retain all evaluation inputs."""
    try:
        state = workflow.invoke(
            {
                "patient_id": patient_id,
                "intent": intent.value,
                "lookback_days": lookback_days,
            }
        )
        bundle = state["evidence_bundle"]
        catalog = database.get_patient_numeric_lab_catalog(con, patient_id)

        selection = select_numeric_observations(
            model,
            bundle=bundle,
            catalog=catalog,
        )
        package = retrieve_selected_observation_evidence(
            toolset,
            bundle=bundle,
            catalog=catalog,
            selection=selection,
        )
        enriched_bundle = enrich_evidence_bundle_with_selected_observations(
            bundle=bundle,
            package=package,
        )
        synthesis = synthesize_evidence_bundle(
            model=model,
            bundle=enriched_bundle,
        )
        deterministic = evaluate_synthesis_deterministically(
            synthesis=synthesis,
            bundle=enriched_bundle,
        )

        return EvaluationIntentResult(
            intent=intent.value,
            status="ok",
            evidence_bundle=enriched_bundle,
            selection=selection.model_dump(mode="json"),
            selected_observation_evidence=package,
            synthesis=synthesis.model_dump(mode="json"),
            deterministic_evaluation=deterministic.model_dump(mode="json"),
        )
    except Exception as error:
        return EvaluationIntentResult(
            intent=intent.value,
            status="error",
            error_type=type(error).__name__,
            error_message=str(error),
        )


def build_live_multipatient_evaluation(
    *,
    cohort_size: int = DEFAULT_EVALUATION_COHORT_SIZE,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    model_name: str = DEFAULT_MODEL,
    reference_patient_id: str = REFERENCE_PATIENT_ID,
) -> MultiPatientEvaluationRun:
    """Execute both supported intents for a deterministically selected cohort."""
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to the environment or local .env file."
        )

    con = database.get_connection()
    try:
        database.register_synthea_tables(con)
        profiles = build_all_patient_evaluation_profiles(
            con,
            lookback_days=lookback_days,
        )
        cohort = select_heterogeneous_evaluation_cohort(
            profiles,
            cohort_size=cohort_size,
            reference_patient_id=reference_patient_id,
        )

        toolset = EvidenceToolset(con)
        workflow = build_clinical_evidence_workflow(toolset)
        model = create_openai_model(
            model_name=model_name,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        )

        patient_results: list[EvaluationPatientResult] = []
        for case in cohort:
            intent_results = tuple(
                run_one_evaluation_intent(
                    con=con,
                    workflow=workflow,
                    toolset=toolset,
                    model=model,
                    patient_id=case.patient_id,
                    intent=intent,
                    lookback_days=lookback_days,
                )
                for intent in (
                    ClinicalEvidenceIntent.CURRENT_STATE,
                    ClinicalEvidenceIntent.TRAJECTORY,
                )
            )
            patient_results.append(
                EvaluationPatientResult(
                    patient_id=case.patient_id,
                    cohort_label=case.cohort_label,
                    rationale=case.rationale,
                    profile=case.profile.model_dump(mode="json"),
                    intent_results=intent_results,
                )
            )

        patients = tuple(patient_results)
        return MultiPatientEvaluationRun(
            model_name=model_name,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
            lookback_days=lookback_days,
            cohort_method=COHORT_METHOD,
            cohort_notes=COHORT_NOTES,
            patients=patients,
            summary=summarize_evaluation_run(patients),
        )
    finally:
        con.close()


def write_evaluation_artifact(
    run: MultiPatientEvaluationRun,
    output_path: str | Path,
) -> Path:
    """Write a stable, human-inspectable JSON artifact."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            run.model_dump(mode="json"),
            indent=2,
            sort_keys=False,
            default=str,
        ),
        encoding="utf-8",
    )
    return path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the frozen enriched-synthesis pipeline across the evaluation cohort."
    )
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=DEFAULT_EVALUATION_COHORT_SIZE,
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
    )
    parser.add_argument(
        "--model",
        default=os.getenv("CLINICAL_EVIDENCE_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument(
        "--reference-patient-id",
        default=REFERENCE_PATIENT_ID,
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_EVALUATION_OUTPUT),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run = build_live_multipatient_evaluation(
        cohort_size=args.cohort_size,
        lookback_days=args.lookback_days,
        model_name=args.model,
        reference_patient_id=args.reference_patient_id,
    )
    output_path = write_evaluation_artifact(run, args.output)

    print(
        json.dumps(
            {
                "output": str(output_path),
                "summary": run.summary.model_dump(mode="json"),
                "cases": [
                    {
                        "patient_id": patient.patient_id,
                        "cohort_label": patient.cohort_label,
                        "intent_status": {
                            result.intent: result.status
                            for result in patient.intent_results
                        },
                    }
                    for patient in run.patients
                ],
            },
            indent=2,
        )
    )
    return 0 if run.summary.failed_intent_cases == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
