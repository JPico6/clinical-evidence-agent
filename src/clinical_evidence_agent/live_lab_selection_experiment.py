"""Live constrained numeric-observation selection experiment.

This intentionally stops after selection. Selected observations are not yet
retrieved or merged into the clinical synthesis workflow.
"""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from clinical_evidence_agent import database
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.evidence_workflow import build_clinical_evidence_workflow
from clinical_evidence_agent.lab_selection import select_numeric_observations


REFERENCE_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-id", default=REFERENCE_PATIENT_ID)
    parser.add_argument(
        "--intent",
        choices=[item.value for item in ClinicalEvidenceIntent],
        default=ClinicalEvidenceIntent.CURRENT_STATE.value,
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

    con = database.get_connection()
    try:
        database.register_synthea_tables(con)
        toolset = EvidenceToolset(con)
        workflow = build_clinical_evidence_workflow(toolset)
        state = workflow.invoke(
            {
                "patient_id": args.patient_id,
                "intent": args.intent,
                "lookback_days": args.lookback_days,
            }
        )
        catalog = database.get_patient_numeric_lab_catalog(con, args.patient_id)

        model = ChatOpenAI(
            model=args.model,
            reasoning_effort=DEFAULT_REASONING_EFFORT,
        )
        selection = select_numeric_observations(
            model,
            bundle=state["evidence_bundle"],
            catalog=catalog,
        )
        print(json.dumps(selection.model_dump(mode="json"), indent=2))
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
