from clinical_evidence_agent import database
from clinical_evidence_agent import data_access
from clinical_evidence_agent.evidence import conditions, labs, medications, procedures, recent_events, utilization


def test_database_facade_preserves_public_function_imports():
    assert database.get_connection is data_access.get_connection
    assert database.register_synthea_tables is data_access.register_synthea_tables
    assert database.get_patient_latest_date is data_access.get_patient_latest_date

    assert database.build_utilization_evidence is utilization.build_utilization_evidence
    assert database.build_lab_evidence is labs.build_lab_evidence
    assert database.build_condition_evidence is conditions.build_condition_evidence
    assert database.build_medication_evidence is medications.build_medication_evidence
    assert database.build_procedure_evidence is procedures.build_procedure_evidence
    assert database.build_recent_event_evidence is recent_events.build_recent_event_evidence
