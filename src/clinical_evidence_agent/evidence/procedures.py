"""Deterministic procedure evidence."""

from datetime import timedelta

import pandas as pd

from clinical_evidence_agent.data_access import (
    get_patient_latest_date,
    get_patient_procedures,
)


def _clean_source_reason_pairs(rows):
    """Preserve unique source-recorded reason code/description pairs."""
    reasons = []
    seen = set()

    for code, description in rows:
        if pd.isna(code) and pd.isna(description):
            continue

        clean_code = None if pd.isna(code) else str(int(code)) if isinstance(code, (int, float)) and not isinstance(code, bool) else str(code)
        clean_description = None if pd.isna(description) else str(description)
        key = (clean_code, clean_description)

        if key not in seen:
            seen.add(key)
            reasons.append(
                {
                    "code": clean_code,
                    "description": clean_description,
                }
            )

    return reasons

def get_patient_procedure_summary(con, patient_id: str):
    """Summarize source-recorded procedure events by procedure concept."""
    procedures = get_patient_procedures(con, patient_id)
    columns = [
        "CODE",
        "DESCRIPTION",
        "event_count",
        "encounter_count",
        "first_start",
        "latest_start",
        "source_reasons",
    ]

    if procedures.empty:
        return pd.DataFrame(columns=columns)

    procedures = procedures.copy()
    procedures["START"] = pd.to_datetime(procedures["START"])

    summaries = []
    for code, group in procedures.groupby("CODE", sort=False):
        reason_rows = zip(
            group["REASONCODE"].tolist(),
            group["REASONDESCRIPTION"].tolist(),
        )
        summaries.append(
            {
                "CODE": code,
                "DESCRIPTION": group.iloc[0]["DESCRIPTION"],
                "event_count": len(group),
                "encounter_count": group["ENCOUNTER"].nunique(),
                "first_start": group["START"].min(),
                "latest_start": group["START"].max(),
                "source_reasons": _clean_source_reason_pairs(reason_rows),
            }
        )

    return pd.DataFrame(summaries, columns=columns).sort_values(
        ["first_start", "DESCRIPTION"],
        kind="stable",
    )

def get_patient_new_procedures(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Return procedure concepts first observed within the patient-relative lookback."""
    anchor_date = get_patient_latest_date(con, patient_id)
    summary = get_patient_procedure_summary(con, patient_id)

    if anchor_date is None or summary.empty:
        return summary.iloc[0:0].copy()

    cutoff_date = anchor_date - timedelta(days=lookback_days)
    first_start_dates = pd.to_datetime(summary["first_start"]).dt.date
    return summary[first_start_dates >= cutoff_date].copy()

def get_patient_recent_procedure_patterns(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Aggregate repeated recent procedure events by procedure concept.

    A pattern is purely mechanical: at least two source-recorded events for the
    same procedure code within the lookback. It does not imply clinical
    significance, treatment intensity, or a procedure course.
    """
    anchor_date = get_patient_latest_date(con, patient_id)
    columns = [
        "CODE",
        "DESCRIPTION",
        "recent_event_count",
        "recent_encounter_count",
        "first_recent_start",
        "latest_recent_start",
        "lifetime_event_count",
        "lifetime_encounter_count",
        "source_reasons",
    ]

    if anchor_date is None:
        return pd.DataFrame(columns=columns)

    procedures = get_patient_procedures(con, patient_id)
    if procedures.empty:
        return pd.DataFrame(columns=columns)

    procedures = procedures.copy()
    procedures["START"] = pd.to_datetime(procedures["START"])
    cutoff_date = anchor_date - timedelta(days=lookback_days)
    recent = procedures[procedures["START"].dt.date >= cutoff_date].copy()

    if recent.empty:
        return pd.DataFrame(columns=columns)

    lifetime = get_patient_procedure_summary(con, patient_id).set_index("CODE")
    patterns = []

    for code, group in recent.groupby("CODE", sort=False):
        if len(group) < 2:
            continue

        lifetime_row = lifetime.loc[code]
        reason_rows = zip(
            group["REASONCODE"].tolist(),
            group["REASONDESCRIPTION"].tolist(),
        )
        patterns.append(
            {
                "CODE": code,
                "DESCRIPTION": group.iloc[0]["DESCRIPTION"],
                "recent_event_count": len(group),
                "recent_encounter_count": group["ENCOUNTER"].nunique(),
                "first_recent_start": group["START"].min(),
                "latest_recent_start": group["START"].max(),
                "lifetime_event_count": int(lifetime_row["event_count"]),
                "lifetime_encounter_count": int(
                    lifetime_row["encounter_count"]
                ),
                "source_reasons": _clean_source_reason_pairs(reason_rows),
            }
        )

    if not patterns:
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(patterns, columns=columns).sort_values(
        ["latest_recent_start", "DESCRIPTION"],
        ascending=[False, True],
        kind="stable",
    )

def get_patient_recent_procedure_encounters(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Return recent procedure events with their matched encounter context."""
    anchor_date = get_patient_latest_date(con, patient_id)
    if anchor_date is None:
        return pd.DataFrame(
            columns=[
                "ENCOUNTER",
                "encounter_start",
                "encounter_stop",
                "encounter_class",
                "encounter_description",
                "procedure_start",
                "procedure_stop",
                "CODE",
                "DESCRIPTION",
                "REASONCODE",
                "REASONDESCRIPTION",
            ]
        )

    cutoff_date = anchor_date - timedelta(days=lookback_days)
    return con.execute(
        """
        SELECT
            p.ENCOUNTER,
            e.START AS encounter_start,
            e.STOP AS encounter_stop,
            e.ENCOUNTERCLASS AS encounter_class,
            e.DESCRIPTION AS encounter_description,
            p.START AS procedure_start,
            p.STOP AS procedure_stop,
            p.CODE,
            p.DESCRIPTION,
            p.REASONCODE,
            p.REASONDESCRIPTION
        FROM procedures p
        INNER JOIN encounters e
            ON p.ENCOUNTER = e.Id
           AND p.PATIENT = e.PATIENT
        WHERE p.PATIENT = ?
          AND CAST(p.START AS DATE) >= ?
        ORDER BY p.START, p.ENCOUNTER, p.DESCRIPTION
        """,
        [patient_id, cutoff_date.isoformat()],
    ).fetchdf()

def build_procedure_evidence(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Build deterministic procedure evidence without assigning importance."""
    anchor_date = get_patient_latest_date(con, patient_id)

    if anchor_date is None:
        return {
            "status": "no_data",
            "patient_id": patient_id,
        }

    summary = get_patient_procedure_summary(con, patient_id)
    new_procedures = get_patient_new_procedures(
        con,
        patient_id,
        lookback_days=lookback_days,
    )
    patterns = get_patient_recent_procedure_patterns(
        con,
        patient_id,
        lookback_days=lookback_days,
    )
    recent_events = get_patient_recent_procedure_encounters(
        con,
        patient_id,
        lookback_days=lookback_days,
    )

    def clean_date(value):
        if value is None or pd.isna(value):
            return None
        if hasattr(value, "date"):
            value = value.date()
        return value.isoformat()

    def clean_datetime(value):
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()

    procedures = []
    for _, row in summary.iterrows():
        procedures.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "event_count": int(row["event_count"]),
                "encounter_count": int(row["encounter_count"]),
                "first_start": clean_date(row["first_start"]),
                "latest_start": clean_date(row["latest_start"]),
                "source_reasons": row["source_reasons"],
            }
        )

    newly_observed_procedures = []
    for _, row in new_procedures.iterrows():
        newly_observed_procedures.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "first_start": clean_date(row["first_start"]),
                "event_count": int(row["event_count"]),
                "encounter_count": int(row["encounter_count"]),
                "source_reasons": row["source_reasons"],
            }
        )

    recent_procedure_patterns = []
    for _, row in patterns.iterrows():
        recent_procedure_patterns.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "recent_event_count": int(row["recent_event_count"]),
                "recent_encounter_count": int(
                    row["recent_encounter_count"]
                ),
                "first_recent_start": clean_date(
                    row["first_recent_start"]
                ),
                "latest_recent_start": clean_date(
                    row["latest_recent_start"]
                ),
                "lifetime_event_count": int(row["lifetime_event_count"]),
                "lifetime_encounter_count": int(
                    row["lifetime_encounter_count"]
                ),
                "source_reasons": row["source_reasons"],
            }
        )

    encounter_groups = []
    if not recent_events.empty:
        for encounter_id, group in recent_events.groupby(
            "ENCOUNTER",
            sort=False,
        ):
            procedure_events = []
            for _, row in group.sort_values(
                ["procedure_start", "DESCRIPTION"],
                kind="stable",
            ).iterrows():
                reasons = _clean_source_reason_pairs(
                    [(row["REASONCODE"], row["REASONDESCRIPTION"])]
                )
                procedure_events.append(
                    {
                        "code": str(row["CODE"]),
                        "description": row["DESCRIPTION"],
                        "start": clean_datetime(row["procedure_start"]),
                        "stop": clean_datetime(row["procedure_stop"]),
                        "source_reasons": reasons,
                    }
                )

            first = group.iloc[0]
            procedure_starts = pd.to_datetime(group["procedure_start"])
            encounter_groups.append(
                {
                    "encounter_id": encounter_id,
                    "encounter_start": clean_datetime(first["encounter_start"]),
                    "encounter_stop": clean_datetime(first["encounter_stop"]),
                    "first_procedure_start": clean_datetime(
                        procedure_starts.min()
                    ),
                    "latest_procedure_start": clean_datetime(
                        procedure_starts.max()
                    ),
                    "encounter_class": first["encounter_class"],
                    "encounter_description": first[
                        "encounter_description"
                    ],
                    "procedure_event_count": len(group),
                    "distinct_procedure_code_count": int(
                        group["CODE"].nunique()
                    ),
                    "procedures": procedure_events,
                }
            )

    encounter_groups.sort(
        key=lambda item: (
            item["encounter_start"] or "",
            item["encounter_id"],
        ),
        reverse=True,
    )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "anchor_date": clean_date(anchor_date),
        "lookback_days": lookback_days,
        "procedure_count": len(procedures),
        "procedure_event_count": int(summary["event_count"].sum())
        if not summary.empty
        else 0,
        "newly_observed_procedure_count": len(
            newly_observed_procedures
        ),
        "newly_observed_procedures": newly_observed_procedures,
        "recent_procedure_pattern_count": len(
            recent_procedure_patterns
        ),
        "recent_procedure_patterns": recent_procedure_patterns,
        "recent_procedure_encounter_count": len(encounter_groups),
        "recent_procedure_encounters": encounter_groups,
        "procedures": procedures,
    }
