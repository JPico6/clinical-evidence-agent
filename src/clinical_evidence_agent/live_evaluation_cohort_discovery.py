"""Discover a heterogeneous deterministic evaluation cohort from Synthea."""

from __future__ import annotations

import argparse
import json

from clinical_evidence_agent import database
from clinical_evidence_agent.evaluation_cohort import (
    DEFAULT_EVALUATION_COHORT_SIZE,
    build_all_patient_evaluation_profiles,
    select_heterogeneous_evaluation_cohort,
)
from clinical_evidence_agent.live_experiment import REFERENCE_PATIENT_ID


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort-size", type=int, default=DEFAULT_EVALUATION_COHORT_SIZE)
    parser.add_argument("--lookback-days", type=int, default=365)
    parser.add_argument("--reference-patient-id", default=REFERENCE_PATIENT_ID)
    args = parser.parse_args()

    con = database.get_connection()
    try:
        database.register_synthea_tables(con)
        profiles = build_all_patient_evaluation_profiles(
            con,
            lookback_days=args.lookback_days,
        )
        cohort = select_heterogeneous_evaluation_cohort(
            profiles,
            cohort_size=args.cohort_size,
            reference_patient_id=args.reference_patient_id,
        )
    finally:
        con.close()

    output = {
        "patient_profile_count": len(profiles),
        "cohort_size": len(cohort),
        "lookback_days": args.lookback_days,
        "cases": [case.model_dump(mode="json") for case in cohort],
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
