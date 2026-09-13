"""Deterministic condition evidence."""

from datetime import timedelta

import pandas as pd

from clinical_evidence_agent.data_access import get_patient_latest_date


def get_patient_condition_summary(con, patient_id: str):
    return con.execute(
        """
        SELECT
            CODE,
            DESCRIPTION,
            COUNT(*) AS episode_count,
            MIN(CAST(START AS DATE)) AS first_start,
            MAX(CAST(START AS DATE)) AS latest_start,
            MAX(CAST(STOP AS DATE)) AS latest_stop,
            SUM(
                CASE
                    WHEN STOP IS NULL THEN 1
                    ELSE 0
                END
            ) AS source_open_episode_count
        FROM conditions
        WHERE PATIENT = ?
        GROUP BY CODE, DESCRIPTION
        ORDER BY first_start, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

def get_patient_new_conditions(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    anchor_date = get_patient_latest_date(
        con,
        patient_id,
    )

    if anchor_date is None:
        return con.execute(
            """
            SELECT
                CODE,
                DESCRIPTION,
                CAST(NULL AS DATE) AS first_start,
                CAST(NULL AS BIGINT) AS episode_count
            WHERE FALSE
            """
        ).fetchdf()

    cutoff_date = anchor_date - timedelta(
        days=lookback_days
    )

    return con.execute(
        """
        SELECT
            CODE,
            DESCRIPTION,
            MIN(CAST(START AS DATE)) AS first_start,
            COUNT(*) AS episode_count
        FROM conditions
        WHERE PATIENT = ?
        GROUP BY CODE, DESCRIPTION
        HAVING MIN(CAST(START AS DATE)) >= ?
        ORDER BY first_start, DESCRIPTION
        """,
        [
            patient_id,
            cutoff_date,
        ],
    ).fetchdf()

def build_condition_evidence(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    anchor_date = get_patient_latest_date(
        con,
        patient_id,
    )

    if anchor_date is None:
        return {
            "status": "no_data",
            "patient_id": patient_id,
        }

    condition_summary = get_patient_condition_summary(
        con,
        patient_id,
    )

    new_conditions = get_patient_new_conditions(
        con,
        patient_id,
        lookback_days=lookback_days,
    )

    def clean_date(value):
        if pd.isna(value):
            return None

        if hasattr(value, "date"):
            value = value.date()

        return value.isoformat()

    conditions = []

    for _, row in condition_summary.iterrows():
        conditions.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "episode_count": int(row["episode_count"]),
                "first_start": clean_date(row["first_start"]),
                "latest_start": clean_date(row["latest_start"]),
                "latest_stop": clean_date(row["latest_stop"]),
                "source_open_episode_count": int(
                    row["source_open_episode_count"]
                ),
            }
        )

    newly_observed_conditions = []

    for _, row in new_conditions.iterrows():
        newly_observed_conditions.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "first_start": clean_date(row["first_start"]),
                "episode_count": int(row["episode_count"]),
            }
        )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "anchor_date": clean_date(anchor_date),
        "lookback_days": lookback_days,
        "condition_count": len(conditions),
        "newly_observed_condition_count": len(
            newly_observed_conditions
        ),
        "newly_observed_conditions": newly_observed_conditions,
        "conditions": conditions,
    }
