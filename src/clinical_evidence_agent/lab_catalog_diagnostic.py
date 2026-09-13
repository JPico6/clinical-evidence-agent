"""Print the deterministic numeric-lab catalog for one Synthea patient."""

import argparse
import json

from clinical_evidence_agent.database import (
    get_connection,
    get_patient_numeric_lab_catalog,
    register_synthea_tables,
)


DEFAULT_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-id", default=DEFAULT_PATIENT_ID)
    args = parser.parse_args()

    con = get_connection()
    try:
        register_synthea_tables(con)
        catalog = get_patient_numeric_lab_catalog(con, args.patient_id)
        print(json.dumps(catalog, indent=2))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
