"""Live end-to-end synthesis with grounded numeric-observation enrichment."""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

from clinical_evidence_agent import database
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
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


def run_enriched_synthesis_case(
    *,
    workflow,
    toolset: EvidenceToolset,
    model,
    con,
    patient_id: str,
    intent: ClinicalEvidenceIntent | str,
    lookback_days: int = 365,
):
    state = workflow.invoke(
        {
            "patient_id": patient_id,
            "intent": ClinicalEvidenceIntent(intent).value,
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
    return {
        "selection": selection.model_dump(mode="json"),
        "selected_observation_evidence": package,
        "synthesis": synthesis.model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-id", default=REFERENCE_PATIENT_ID)
    parser.add_argument(
        "--intent",
        choices=[
            ClinicalEvidenceIntent.CURRENT_STATE.value,
            ClinicalEvidenceIntent.TRAJECTORY.value,
            "both",
        ],
        default="both",
    )
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument(
        "--model",
        default=os.getenv("CLINICAL_EVIDENCE_MODEL", DEFAULT_MODEL),
    )
    args = parser.parse_args()

    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to the environment or local .env file."
        )

    intents = (
        [ClinicalEvidenceIntent.CURRENT_STATE, ClinicalEvidenceIntent.TRAJECTORY]
        if args.intent == "both"
        else [ClinicalEvidenceIntent(args.intent)]
    )

    con = database.get_connection()
    try:
        database.register_synthea_tables(con)
        toolset = EvidenceToolset(con)
        workflow = build_clinical_evidence_workflow(toolset)
        model = create_openai_model(
            model_name=args.model,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        )

        for intent in intents:
            result = run_enriched_synthesis_case(
                workflow=workflow,
                toolset=toolset,
                model=model,
                con=con,
                patient_id=args.patient_id,
                intent=intent,
                lookback_days=args.lookback_days,
            )
            print(f"=== {intent.value.upper()} ===")
            print(json.dumps(result, indent=2, default=str))
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
