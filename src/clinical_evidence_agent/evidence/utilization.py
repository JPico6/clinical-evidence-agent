"""Deterministic utilization evidence."""

from datetime import timedelta

import pandas as pd

from clinical_evidence_agent.data_access import get_patient_latest_date


def get_patient_utilization_summary(con, patient_id: str):
    return con.execute(
        """
        SELECT
            ENCOUNTERCLASS,
            COUNT(*) AS encounter_count,
            MIN(START) AS first_encounter,
            MAX(START) AS last_encounter
        FROM encounters
        WHERE PATIENT = ?
        GROUP BY ENCOUNTERCLASS
        ORDER BY encounter_count DESC
        """,
        [patient_id],
    ).fetchdf()

def get_patient_utilization_by_period(
    con,
    patient_id: str,
    start_date: str,
    end_date: str,
):
    return con.execute(
        """
        SELECT
            ENCOUNTERCLASS,
            COUNT(*) AS encounter_count
        FROM encounters
        WHERE PATIENT = ?
          AND START >= ?
          AND START < ?
        GROUP BY ENCOUNTERCLASS
        ORDER BY encounter_count DESC
        """,
        [patient_id, start_date, end_date],
    ).fetchdf()

def get_patient_utilization_change(con, patient_id: str):
    anchor_date = get_patient_latest_date(con, patient_id)

    # Our SQL uses an exclusive end date, so move one day
    # beyond the patient's final observed date.
    end_exclusive = anchor_date + timedelta(days=1)

    recent_start = end_exclusive - timedelta(days=365)
    prior_start = recent_start - timedelta(days=365)

    recent = get_patient_utilization_by_period(
        con,
        patient_id,
        recent_start.isoformat(),
        end_exclusive.isoformat(),
    )

    prior = get_patient_utilization_by_period(
        con,
        patient_id,
        prior_start.isoformat(),
        recent_start.isoformat(),
    )

    return {
        "anchor_date": anchor_date,
        "prior_period": {
            "start": prior_start,
            "end": recent_start - timedelta(days=1),
            "utilization": prior,
        },
        "recent_period": {
            "start": recent_start,
            "end": anchor_date,
            "utilization": recent,
        },
    }

def compare_patient_utilization(con, patient_id: str):
    utilization_change = get_patient_utilization_change(con, patient_id)

    prior = utilization_change["prior_period"]["utilization"].rename(
        columns={"encounter_count": "prior_count"}
    )

    recent = utilization_change["recent_period"]["utilization"].rename(
        columns={"encounter_count": "recent_count"}
    )

    comparison = pd.merge(
        prior,
        recent,
        on="ENCOUNTERCLASS",
        how="outer",
    ).fillna(0)

    comparison["prior_count"] = comparison["prior_count"].astype(int)
    comparison["recent_count"] = comparison["recent_count"].astype(int)
    comparison["absolute_change"] = (
        comparison["recent_count"] - comparison["prior_count"]
    )

    return comparison.sort_values(
        "recent_count",
        ascending=False,
    ).reset_index(drop=True)

def build_utilization_evidence(con, patient_id: str):
    utilization_change = get_patient_utilization_change(
        con,
        patient_id,
    )

    comparison = compare_patient_utilization(
        con,
        patient_id,
    )

    def clean_date(value):
        if value is None:
            return None

        if hasattr(value, "date"):
            value = value.date()

        return value.isoformat()

    encounter_classes = []

    for _, row in comparison.iterrows():
        prior_count = int(row["prior_count"])
        recent_count = int(row["recent_count"])
        absolute_change = int(row["absolute_change"])

        encounter_classes.append(
            {
                "encounter_class": row["ENCOUNTERCLASS"],
                "prior_count": prior_count,
                "recent_count": recent_count,
                "absolute_change": absolute_change,
            }
        )

    prior_total = sum(
        item["prior_count"]
        for item in encounter_classes
    )

    recent_total = sum(
        item["recent_count"]
        for item in encounter_classes
    )

    evidence_sufficiency = classify_utilization_evidence_sufficiency(
        prior_total,
        recent_total,
    )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "anchor_date": clean_date(
            utilization_change["anchor_date"]
        ),
        "prior_period": {
            "start": clean_date(
                utilization_change["prior_period"]["start"]
            ),
            "end": clean_date(
                utilization_change["prior_period"]["end"]
            ),
            "total_encounters": prior_total,
        },
        "recent_period": {
            "start": clean_date(
                utilization_change["recent_period"]["start"]
            ),
            "end": clean_date(
                utilization_change["recent_period"]["end"]
            ),
            "total_encounters": recent_total,
        },
        "evidence_sufficiency": evidence_sufficiency,
        "total_change": {
            "absolute": recent_total - prior_total,
        },
        "by_encounter_class": encounter_classes,
    }

def classify_utilization_evidence_sufficiency(
    prior_count: int,
    recent_count: int,
) -> str:
    if recent_count == 0:
        return "no_recent_utilization"

    if prior_count == 0:
        return "no_prior_utilization"

    if prior_count == 1 or recent_count == 1:
        return "sparse_comparison"

    return "multi_encounter_comparison"
