"""Deterministic construction of a heterogeneous Synthea evaluation cohort.

This module does not judge clinical severity and does not call an LLM.  It
profiles each synthetic patient using observable record characteristics, then
selects a small set of distinct patients that stress different evidence shapes.

The purpose is evaluation diversity, not epidemiologic sampling.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable

from pydantic import BaseModel, ConfigDict

from clinical_evidence_agent.data_access import get_patient_latest_date


DEFAULT_EVALUATION_COHORT_SIZE = 10
REFERENCE_COHORT_LABEL = "reference_complex"


class PatientEvaluationProfile(BaseModel):
    """Observable characteristics used only for evaluation-cohort diversity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: str
    anchor_date: str
    encounter_count: int
    condition_count: int
    medication_count: int
    procedure_count: int
    numeric_observation_count: int
    numeric_observation_code_count: int
    recent_encounter_count: int
    recent_condition_count: int
    recent_medication_count: int
    recent_procedure_count: int
    recent_numeric_observation_count: int


class EvaluationCohortCase(BaseModel):
    """One selected patient and the record-shape reason for inclusion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    patient_id: str
    cohort_label: str
    rationale: str
    profile: PatientEvaluationProfile


def _scalar_count(con, sql: str, params: list[object]) -> int:
    return int(con.execute(sql, params).fetchone()[0])


def build_patient_evaluation_profile(
    con,
    patient_id: str,
    *,
    lookback_days: int = 365,
) -> PatientEvaluationProfile:
    """Profile one patient without introducing clinical interpretation."""
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValueError("patient_id must be a non-empty string")
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
        raise TypeError("lookback_days must be a positive integer")
    if lookback_days <= 0:
        raise ValueError("lookback_days must be a positive integer")

    patient_id = patient_id.strip()
    anchor = get_patient_latest_date(con, patient_id)
    if anchor is None:
        raise ValueError(f"patient has no observed clinical events: {patient_id!r}")

    end_exclusive = anchor + timedelta(days=1)
    recent_start = end_exclusive - timedelta(days=lookback_days)
    recent_start_s = recent_start.isoformat()
    end_exclusive_s = end_exclusive.isoformat()

    def total(table: str, patient_column: str = "PATIENT") -> int:
        return _scalar_count(
            con,
            f"SELECT COUNT(*) FROM {table} WHERE {patient_column} = ?",
            [patient_id],
        )

    def recent(table: str, date_column: str, patient_column: str = "PATIENT") -> int:
        return _scalar_count(
            con,
            f"""
            SELECT COUNT(*)
            FROM {table}
            WHERE {patient_column} = ?
              AND CAST({date_column} AS DATE) >= ?
              AND CAST({date_column} AS DATE) < ?
            """,
            [patient_id, recent_start_s, end_exclusive_s],
        )

    numeric_count = _scalar_count(
        con,
        """
        SELECT COUNT(*)
        FROM observations
        WHERE PATIENT = ?
          AND lower(CAST(TYPE AS VARCHAR)) = 'numeric'
        """,
        [patient_id],
    )
    numeric_code_count = _scalar_count(
        con,
        """
        SELECT COUNT(DISTINCT CODE)
        FROM observations
        WHERE PATIENT = ?
          AND lower(CAST(TYPE AS VARCHAR)) = 'numeric'
        """,
        [patient_id],
    )
    recent_numeric_count = _scalar_count(
        con,
        """
        SELECT COUNT(*)
        FROM observations
        WHERE PATIENT = ?
          AND lower(CAST(TYPE AS VARCHAR)) = 'numeric'
          AND CAST(DATE AS DATE) >= ?
          AND CAST(DATE AS DATE) < ?
        """,
        [patient_id, recent_start_s, end_exclusive_s],
    )

    return PatientEvaluationProfile(
        patient_id=patient_id,
        anchor_date=anchor.isoformat(),
        encounter_count=total("encounters"),
        condition_count=total("conditions"),
        medication_count=total("medications"),
        procedure_count=total("procedures"),
        numeric_observation_count=numeric_count,
        numeric_observation_code_count=numeric_code_count,
        recent_encounter_count=recent("encounters", "START"),
        recent_condition_count=recent("conditions", "START"),
        recent_medication_count=recent("medications", "START"),
        recent_procedure_count=recent("procedures", "START"),
        recent_numeric_observation_count=recent_numeric_count,
    )


def build_all_patient_evaluation_profiles(
    con,
    *,
    lookback_days: int = 365,
) -> tuple[PatientEvaluationProfile, ...]:
    """Profile every Synthea patient that has at least one observed event."""
    patient_ids = [
        str(row[0])
        for row in con.execute("SELECT Id FROM patients ORDER BY Id").fetchall()
    ]
    profiles: list[PatientEvaluationProfile] = []
    for patient_id in patient_ids:
        try:
            profiles.append(
                build_patient_evaluation_profile(
                    con,
                    patient_id,
                    lookback_days=lookback_days,
                )
            )
        except ValueError as error:
            if "no observed clinical events" not in str(error):
                raise
    return tuple(profiles)


def _record_volume(profile: PatientEvaluationProfile) -> int:
    return (
        profile.encounter_count
        + profile.condition_count
        + profile.medication_count
        + profile.procedure_count
        + profile.numeric_observation_count
    )


def _recent_volume(profile: PatientEvaluationProfile) -> int:
    return (
        profile.recent_encounter_count
        + profile.recent_condition_count
        + profile.recent_medication_count
        + profile.recent_procedure_count
        + profile.recent_numeric_observation_count
    )


def _pick_distinct(
    *,
    profiles: tuple[PatientEvaluationProfile, ...],
    used: set[str],
    key,
    reverse: bool,
) -> PatientEvaluationProfile | None:
    candidates = [p for p in profiles if p.patient_id not in used]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda p: (key(p), p.patient_id),
        reverse=reverse,
    )[0]


def select_heterogeneous_evaluation_cohort(
    profiles: Iterable[PatientEvaluationProfile],
    *,
    cohort_size: int = DEFAULT_EVALUATION_COHORT_SIZE,
    reference_patient_id: str | None = None,
) -> tuple[EvaluationCohortCase, ...]:
    """Select distinct patients spanning different deterministic record shapes.

    Labels describe why a case stresses the system.  They are deliberately
    record-shape labels rather than clinical severity labels.
    """
    profiles = tuple(profiles)
    if isinstance(cohort_size, bool) or not isinstance(cohort_size, int):
        raise TypeError("cohort_size must be a positive integer")
    if cohort_size <= 0:
        raise ValueError("cohort_size must be a positive integer")
    if not profiles:
        return ()

    by_id = {profile.patient_id: profile for profile in profiles}
    used: set[str] = set()
    cases: list[EvaluationCohortCase] = []

    def add(profile, label: str, rationale: str):
        if profile is None or profile.patient_id in used or len(cases) >= cohort_size:
            return
        used.add(profile.patient_id)
        cases.append(
            EvaluationCohortCase(
                patient_id=profile.patient_id,
                cohort_label=label,
                rationale=rationale,
                profile=profile,
            )
        )

    if reference_patient_id is not None and reference_patient_id in by_id:
        add(
            by_id[reference_patient_id],
            REFERENCE_COHORT_LABEL,
            "Previously studied complex reference case retained as a regression anchor.",
        )

    axes = (
        ("sparse_record", lambda p: _record_volume(p), False,
         "Low total record volume stresses sparse-evidence and omission behavior."),
        ("dense_record", lambda p: _record_volume(p), True,
         "High total record volume stresses salience and resistance to exhaustive inventory."),
        ("low_recent_activity", lambda p: _recent_volume(p), False,
         "Low recent record volume stresses uncertainty when little current evidence exists."),
        ("high_recent_activity", lambda p: _recent_volume(p), True,
         "High recent record volume stresses prioritization among many recent facts."),
        ("condition_heavy", lambda p: p.condition_count, True,
         "High condition-row volume stresses repeated-condition summarization."),
        ("medication_heavy", lambda p: p.medication_count, True,
         "High medication-row volume stresses course semantics and source-open guardrails."),
        ("procedure_heavy", lambda p: p.procedure_count, True,
         "High procedure-row volume stresses event grouping and repeated-procedure handling."),
        ("numeric_rich", lambda p: p.numeric_observation_code_count, True,
         "Broad numeric-observation coverage stresses constrained observation selection."),
        ("recent_condition_activity", lambda p: p.recent_condition_count, True,
         "Many recently starting condition records stress current-state and trajectory salience."),
        ("recent_procedure_activity", lambda p: p.recent_procedure_count, True,
         "Many recent procedure events stress trajectory synthesis without frequency-as-importance."),
        ("recent_medication_activity", lambda p: p.recent_medication_count, True,
         "Many recent medication records stress provenance and non-adherence inference."),
        ("recent_numeric_activity", lambda p: p.recent_numeric_observation_count, True,
         "Dense recent numeric evidence stresses materiality filtering after retrieval."),
    )

    for label, key, reverse, rationale in axes:
        if len(cases) >= cohort_size:
            break
        add(
            _pick_distinct(profiles=profiles, used=used, key=key, reverse=reverse),
            label,
            rationale,
        )

    return tuple(cases)
