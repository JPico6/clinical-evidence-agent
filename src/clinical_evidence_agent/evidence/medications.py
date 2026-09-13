"""Deterministic medication evidence."""

from datetime import timedelta

import pandas as pd

from clinical_evidence_agent.data_access import (
    get_patient_latest_date,
    get_patient_medications,
)


def get_patient_medication_courses(con, patient_id: str):
    """Build source-recorded medication courses without inferring adherence.

    Rows for the same medication code are joined into one course only when
    their *known* intervals overlap or touch at a boundary. A missing STOP is
    preserved as source-open evidence; it is never treated as an infinite end
    date. If the same medication later reappears after a source-open row and
    no known interval proves continuity, a new course is started with an
    ``after_source_open_unknown`` relationship.
    """
    medications = con.execute(
        """
        SELECT
            START,
            STOP,
            CODE,
            DESCRIPTION,
            DISPENSES,
            REASONCODE,
            REASONDESCRIPTION
        FROM medications
        WHERE PATIENT = ?
        ORDER BY CODE, START, STOP NULLS LAST, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

    columns = [
        "CODE",
        "DESCRIPTION",
        "course_number",
        "course_start",
        "course_end",
        "latest_known_stop",
        "latest_source_start",
        "source_open_course",
        "source_row_count",
        "relationship_to_previous_course",
        "gap_days",
        "source_reason_codes",
        "source_reason_descriptions",
    ]

    if medications.empty:
        return pd.DataFrame(columns=columns)

    medications["START"] = pd.to_datetime(medications["START"])
    medications["STOP"] = pd.to_datetime(medications["STOP"])

    course_rows = []

    def unique_nonnull(values, stringify=False):
        result = []
        seen = set()
        for value in values:
            if pd.isna(value):
                continue
            cleaned = str(value) if stringify else value
            if cleaned not in seen:
                seen.add(cleaned)
                result.append(cleaned)
        return result

    for code, group in medications.groupby("CODE", sort=False, dropna=False):
        group = group.sort_values(
            ["START", "STOP"],
            na_position="last",
            kind="stable",
        )

        current = None
        previous_course = None
        course_number = 0

        def finish_course(course):
            nonlocal previous_course
            if course is None:
                return

            course_end = (
                None
                if course["source_open_course"]
                else course["latest_known_stop"]
            )

            course_rows.append(
                {
                    "CODE": code,
                    "DESCRIPTION": course["description"],
                    "course_number": course["course_number"],
                    "course_start": course["course_start"],
                    "course_end": course_end,
                    "latest_known_stop": course["latest_known_stop"],
                    "latest_source_start": course["latest_source_start"],
                    "source_open_course": course["source_open_course"],
                    "source_row_count": course["source_row_count"],
                    "relationship_to_previous_course": course[
                        "relationship_to_previous_course"
                    ],
                    "gap_days": course["gap_days"],
                    "source_reason_codes": unique_nonnull(
                        course["reason_codes"],
                        stringify=True,
                    ),
                    "source_reason_descriptions": unique_nonnull(
                        course["reason_descriptions"]
                    ),
                }
            )
            previous_course = course.copy()

        for _, row in group.iterrows():
            start = row["START"]
            stop = row["STOP"] if not pd.isna(row["STOP"]) else None

            if current is None:
                course_number += 1
                relationship = (
                    "first_course"
                    if previous_course is None
                    else "after_source_open_unknown"
                )
                gap_days = None
                current = {
                    "course_number": course_number,
                    "course_start": start,
                    "latest_known_stop": stop,
                    "latest_source_start": start,
                    "source_open_course": stop is None,
                    "source_row_count": 1,
                    "description": row["DESCRIPTION"],
                    "reason_codes": [row["REASONCODE"]],
                    "reason_descriptions": [row["REASONDESCRIPTION"]],
                    "relationship_to_previous_course": relationship,
                    "gap_days": gap_days,
                }
                continue

            known_end = current["latest_known_stop"]
            intervals_connect = (
                known_end is not None
                and start <= known_end
            )

            if intervals_connect:
                current["latest_source_start"] = max(
                    current["latest_source_start"], start
                )
                if stop is None:
                    current["source_open_course"] = True
                elif (
                    current["latest_known_stop"] is None
                    or stop > current["latest_known_stop"]
                ):
                    current["latest_known_stop"] = stop
                current["source_row_count"] += 1
                current["reason_codes"].append(row["REASONCODE"])
                current["reason_descriptions"].append(
                    row["REASONDESCRIPTION"]
                )
                continue

            prior_for_relationship = current
            finish_course(current)
            course_number += 1

            if prior_for_relationship["source_open_course"]:
                relationship = "after_source_open_unknown"
                gap_days = None
            else:
                relationship = "after_known_gap"
                gap_days = (
                    start - prior_for_relationship["latest_known_stop"]
                ).days

            current = {
                "course_number": course_number,
                "course_start": start,
                "latest_known_stop": stop,
                "latest_source_start": start,
                "source_open_course": stop is None,
                "source_row_count": 1,
                "description": row["DESCRIPTION"],
                "reason_codes": [row["REASONCODE"]],
                "reason_descriptions": [row["REASONDESCRIPTION"]],
                "relationship_to_previous_course": relationship,
                "gap_days": gap_days,
            }

        finish_course(current)

    return pd.DataFrame(course_rows, columns=columns)

def get_patient_medication_summary(con, patient_id: str):
    source_rows = get_patient_medications(con, patient_id)
    courses = get_patient_medication_courses(con, patient_id)

    columns = [
        "CODE",
        "DESCRIPTION",
        "source_row_count",
        "course_count",
        "first_start",
        "latest_start",
        "source_open_course_count",
        "source_reason_codes",
        "source_reason_descriptions",
    ]

    if source_rows.empty:
        return pd.DataFrame(columns=columns)

    source_rows["START"] = pd.to_datetime(source_rows["START"])
    summaries = []

    for code, group in source_rows.groupby("CODE", sort=False, dropna=False):
        code_courses = courses[courses["CODE"] == code]

        reason_codes = []
        reason_descriptions = []
        for values in code_courses["source_reason_codes"]:
            reason_codes.extend(values)
        for values in code_courses["source_reason_descriptions"]:
            reason_descriptions.extend(values)

        summaries.append(
            {
                "CODE": code,
                "DESCRIPTION": group.iloc[0]["DESCRIPTION"],
                "source_row_count": len(group),
                "course_count": len(code_courses),
                "first_start": group["START"].min(),
                "latest_start": group["START"].max(),
                "source_open_course_count": int(
                    code_courses["source_open_course"].sum()
                ),
                "source_reason_codes": list(dict.fromkeys(reason_codes)),
                "source_reason_descriptions": list(
                    dict.fromkeys(reason_descriptions)
                ),
            }
        )

    return pd.DataFrame(summaries, columns=columns).sort_values(
        ["first_start", "DESCRIPTION"],
        kind="stable",
    )

def get_patient_new_medications(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    anchor_date = get_patient_latest_date(con, patient_id)
    summary = get_patient_medication_summary(con, patient_id)

    if anchor_date is None or summary.empty:
        return summary.iloc[0:0].copy()

    cutoff_date = anchor_date - timedelta(days=lookback_days)
    first_start_dates = pd.to_datetime(summary["first_start"]).dt.date
    return summary[first_start_dates >= cutoff_date].copy()

def build_medication_evidence(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    anchor_date = get_patient_latest_date(con, patient_id)

    if anchor_date is None:
        return {
            "status": "no_data",
            "patient_id": patient_id,
        }

    summary = get_patient_medication_summary(con, patient_id)
    courses = get_patient_medication_courses(con, patient_id)
    new_medications = get_patient_new_medications(
        con,
        patient_id,
        lookback_days=lookback_days,
    )
    cutoff_date = anchor_date - timedelta(days=lookback_days)

    def clean_date(value):
        if value is None or pd.isna(value):
            return None
        if hasattr(value, "date"):
            value = value.date()
        return value.isoformat()

    def clean_reasons(codes, descriptions):
        reasons = []
        max_len = max(len(codes), len(descriptions))
        for index in range(max_len):
            reasons.append(
                {
                    "code": codes[index] if index < len(codes) else None,
                    "description": (
                        descriptions[index]
                        if index < len(descriptions)
                        else None
                    ),
                }
            )
        return reasons

    medications = []
    for _, row in summary.iterrows():
        medications.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "source_row_count": int(row["source_row_count"]),
                "course_count": int(row["course_count"]),
                "first_start": clean_date(row["first_start"]),
                "latest_start": clean_date(row["latest_start"]),
                "source_open_course_count": int(
                    row["source_open_course_count"]
                ),
                "source_reasons": clean_reasons(
                    row["source_reason_codes"],
                    row["source_reason_descriptions"],
                ),
            }
        )

    medication_courses = []
    for _, row in courses.iterrows():
        medication_courses.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "course_number": int(row["course_number"]),
                "course_start": clean_date(row["course_start"]),
                "course_end": clean_date(row["course_end"]),
                "latest_known_stop": clean_date(row["latest_known_stop"]),
                "latest_source_start": clean_date(
                    row["latest_source_start"]
                ),
                "source_open_course": bool(row["source_open_course"]),
                "source_row_count": int(row["source_row_count"]),
                "relationship_to_previous_course": row[
                    "relationship_to_previous_course"
                ],
                "gap_days": (
                    None
                    if pd.isna(row["gap_days"])
                    else int(row["gap_days"])
                ),
                "source_reasons": clean_reasons(
                    row["source_reason_codes"],
                    row["source_reason_descriptions"],
                ),
            }
        )

    newly_observed_medications = []
    for _, row in new_medications.iterrows():
        newly_observed_medications.append(
            {
                "code": str(row["CODE"]),
                "description": row["DESCRIPTION"],
                "first_start": clean_date(row["first_start"]),
                "source_reasons": clean_reasons(
                    row["source_reason_codes"],
                    row["source_reason_descriptions"],
                ),
            }
        )

    recent_subsequent_by_code = {}
    ambiguous_courses_after_source_open = []
    recent_source_open_medications = []

    summary_by_code = {item["code"]: item for item in medications}

    for item in medication_courses:
        course_start = pd.Timestamp(item["course_start"]).date()
        latest_source_start = pd.Timestamp(
            item["latest_source_start"]
        ).date()
        relationship = item["relationship_to_previous_course"]

        if course_start >= cutoff_date and relationship == "after_known_gap":
            code = item["code"]
            pattern = recent_subsequent_by_code.setdefault(
                code,
                {
                    "code": code,
                    "description": item["description"],
                    "recent_subsequent_course_count": 0,
                    "total_course_count": summary_by_code[code][
                        "course_count"
                    ],
                    "first_start": summary_by_code[code]["first_start"],
                    "latest_start": summary_by_code[code]["latest_start"],
                    "latest_subsequent_course_start": None,
                    "recent_known_gap_days_min": None,
                    "recent_known_gap_days_max": None,
                    "source_reasons": summary_by_code[code][
                        "source_reasons"
                    ],
                },
            )
            pattern["recent_subsequent_course_count"] += 1
            pattern["latest_subsequent_course_start"] = max(
                filter(
                    None,
                    [
                        pattern["latest_subsequent_course_start"],
                        item["course_start"],
                    ],
                )
            )
            if item["gap_days"] is not None:
                if pattern["recent_known_gap_days_min"] is None:
                    pattern["recent_known_gap_days_min"] = item[
                        "gap_days"
                    ]
                    pattern["recent_known_gap_days_max"] = item[
                        "gap_days"
                    ]
                else:
                    pattern["recent_known_gap_days_min"] = min(
                        pattern["recent_known_gap_days_min"],
                        item["gap_days"],
                    )
                    pattern["recent_known_gap_days_max"] = max(
                        pattern["recent_known_gap_days_max"],
                        item["gap_days"],
                    )

        if (
            course_start >= cutoff_date
            and relationship == "after_source_open_unknown"
        ):
            ambiguous_courses_after_source_open.append(item)

        if (
            item["source_open_course"]
            and latest_source_start >= cutoff_date
        ):
            recent_source_open_medications.append(item)

    recent_subsequent_medications = list(
        recent_subsequent_by_code.values()
    )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "anchor_date": clean_date(anchor_date),
        "lookback_days": lookback_days,
        "medication_count": len(medications),
        "course_count": len(medication_courses),
        "newly_observed_medication_count": len(
            newly_observed_medications
        ),
        "newly_observed_medications": newly_observed_medications,
        "recent_subsequent_medication_count": len(
            recent_subsequent_medications
        ),
        "recent_subsequent_medications": recent_subsequent_medications,
        "ambiguous_courses_after_source_open_count": len(
            ambiguous_courses_after_source_open
        ),
        "ambiguous_courses_after_source_open": (
            ambiguous_courses_after_source_open
        ),
        "recent_source_open_medication_count": len(
            recent_source_open_medications
        ),
        "recent_source_open_medications": recent_source_open_medications,
        "medications": medications,
        "courses": medication_courses,
    }
