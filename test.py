from clinical_evidence_agent.database import (
    get_connection,
    register_synthea_tables,
    get_patient_observations,
    build_lab_evidence,
)

con = get_connection()
register_synthea_tables(con)

patient_id = "bca1691f-8839-1d66-ed01-471134d55738"

medications = get_patient_observations(con, patient_id)

print(medications.to_string(index=False))