from clinical_evidence_agent.database import (
    get_connection,
    register_synthea_tables,
    get_patient_encounters,
    get_patient_procedures,
    get_patient_demographics,
    get_patient_utilization_summary,
    get_patient_utilization_by_period,
    get_patient_latest_date,
    get_patient_utilization_change,
    compare_patient_utilization,
    get_patient_egfr,
    get_patient_lab_conflicts,
    get_patient_unambiguous_lab_history,
    get_patient_numeric_lab_history,
    summarize_lab_by_year,
    compare_lab_recent_vs_prior,
    get_patient_lab_units,
    build_utilization_evidence,
    build_lab_evidence,
    get_patient_condition_summary,
    get_patient_new_conditions,
    build_condition_evidence,
    build_medication_evidence,
    build_procedure_evidence,
    build_recent_event_evidence
)
import pandas as pd
from datetime  import timedelta
import json

con = get_connection()
register_synthea_tables(con)


import json



evidence = build_recent_event_evidence(
    con,
    "bca1691f-8839-1d66-ed01-471134d55738"
)

from pprint import pprint
pprint(evidence, sort_dicts=False)


