"""Backward-compatible public façade for deterministic database/evidence functions.

Low-level DuckDB access lives in :mod:`clinical_evidence_agent.data_access` and
validated deterministic evidence logic lives in domain modules under
:mod:`clinical_evidence_agent.evidence`.
"""

from clinical_evidence_agent.data_access import (
    DATA_DIR,
    PROJECT_ROOT,
    get_connection,
    get_patient_conditions,
    get_patient_demographics,
    get_patient_encounters,
    get_patient_latest_date,
    get_patient_medications,
    get_patient_observations,
    get_patient_procedures,
    register_synthea_tables,
)
from clinical_evidence_agent.evidence.conditions import (
    build_condition_evidence,
    get_patient_condition_summary,
    get_patient_new_conditions,
)
from clinical_evidence_agent.evidence.labs import (
    build_lab_evidence,
    classify_lab_evidence_sufficiency,
    compare_lab_recent_vs_prior,
    get_patient_egfr,
    get_patient_lab_conflicts,
    get_patient_lab_units,
    get_patient_numeric_lab_history,
    get_patient_unambiguous_lab_history,
    summarize_lab_by_year,
)
from clinical_evidence_agent.evidence.medications import (
    build_medication_evidence,
    get_patient_medication_courses,
    get_patient_medication_summary,
    get_patient_new_medications,
)
from clinical_evidence_agent.evidence.procedures import (
    build_procedure_evidence,
    get_patient_new_procedures,
    get_patient_procedure_summary,
    get_patient_recent_procedure_encounters,
    get_patient_recent_procedure_patterns,
)
from clinical_evidence_agent.evidence.recent_events import (
    build_recent_event_evidence,
    get_patient_recent_event_signals,
)
from clinical_evidence_agent.evidence.utilization import (
    build_utilization_evidence,
    classify_utilization_evidence_sufficiency,
    compare_patient_utilization,
    get_patient_utilization_by_period,
    get_patient_utilization_change,
    get_patient_utilization_summary,
)


__all__ = [name for name in globals() if not name.startswith("_")]
