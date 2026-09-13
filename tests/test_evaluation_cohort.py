import pytest

from clinical_evidence_agent.evaluation_cohort import (
    PatientEvaluationProfile,
    select_heterogeneous_evaluation_cohort,
)


def _profile(patient_id: str, n: int) -> PatientEvaluationProfile:
    return PatientEvaluationProfile(
        patient_id=patient_id,
        anchor_date="2026-08-12",
        encounter_count=n,
        condition_count=n * 2,
        medication_count=n * 3,
        procedure_count=n * 4,
        numeric_observation_count=n * 5,
        numeric_observation_code_count=n,
        recent_encounter_count=n,
        recent_condition_count=n,
        recent_medication_count=n,
        recent_procedure_count=n,
        recent_numeric_observation_count=n,
    )


def test_cohort_selection_is_unique_and_bounded():
    profiles = tuple(_profile(f"p{i}", i) for i in range(1, 15))
    cohort = select_heterogeneous_evaluation_cohort(profiles, cohort_size=10)

    assert len(cohort) == 10
    assert len({case.patient_id for case in cohort}) == 10


def test_reference_patient_is_retained_when_present():
    profiles = tuple(_profile(f"p{i}", i) for i in range(1, 6))
    cohort = select_heterogeneous_evaluation_cohort(
        profiles,
        cohort_size=3,
        reference_patient_id="p3",
    )

    assert cohort[0].patient_id == "p3"
    assert cohort[0].cohort_label == "reference_complex"


def test_empty_profiles_return_empty_cohort():
    assert select_heterogeneous_evaluation_cohort((), cohort_size=10) == ()


@pytest.mark.parametrize("value", [0, -1])
def test_invalid_cohort_size_rejected(value):
    with pytest.raises(ValueError):
        select_heterogeneous_evaluation_cohort((_profile("p1", 1),), cohort_size=value)


def test_bool_cohort_size_rejected():
    with pytest.raises(TypeError):
        select_heterogeneous_evaluation_cohort((_profile("p1", 1),), cohort_size=True)
