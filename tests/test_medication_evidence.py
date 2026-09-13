import pandas as pd

from clinical_evidence_agent.database import (
    build_medication_evidence,
    get_connection,
    get_patient_medication_courses,
)


PATIENT_ID = "patient-1"


def make_test_connection():
    con = get_connection()

    con.execute(
        """
        CREATE TABLE encounters (
            PATIENT VARCHAR,
            START TIMESTAMP
        );
        CREATE TABLE observations (
            PATIENT VARCHAR,
            DATE TIMESTAMP
        );
        CREATE TABLE conditions (
            PATIENT VARCHAR,
            START TIMESTAMP
        );
        CREATE TABLE procedures (
            PATIENT VARCHAR,
            START TIMESTAMP
        );
        CREATE TABLE medications (
            PATIENT VARCHAR,
            START TIMESTAMP,
            STOP TIMESTAMP,
            CODE BIGINT,
            DESCRIPTION VARCHAR,
            DISPENSES BIGINT,
            REASONCODE BIGINT,
            REASONDESCRIPTION VARCHAR
        );
        """
    )

    con.execute(
        "INSERT INTO encounters VALUES (?, TIMESTAMP '2026-08-12')",
        [PATIENT_ID],
    )
    return con


def insert_medication(
    con,
    start,
    stop,
    code,
    description,
    reasoncode=1,
    reasondescription="Test reason",
):
    con.execute(
        """
        INSERT INTO medications
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        [
            PATIENT_ID,
            start,
            stop,
            code,
            description,
            reasoncode,
            reasondescription,
        ],
    )


def test_medication_courses_union_nested_and_boundary_touching_intervals():
    con = make_test_connection()

    insert_medication(
        con,
        "2000-01-01",
        "2030-01-01",
        100,
        "Medication A",
    )
    insert_medication(
        con,
        "2020-01-01",
        "2021-01-01",
        100,
        "Medication A",
    )
    insert_medication(
        con,
        "2021-01-01",
        "2022-01-01",
        100,
        "Medication A",
    )

    courses = get_patient_medication_courses(con, PATIENT_ID)
    code_courses = courses[courses["CODE"] == 100]

    assert len(code_courses) == 1
    course = code_courses.iloc[0]
    assert str(course["course_start"].date()) == "2000-01-01"
    assert str(course["course_end"].date()) == "2030-01-01"
    assert course["source_row_count"] == 3
    assert not bool(course["source_open_course"])

    con.close()


def test_medication_courses_split_on_known_gap():
    con = make_test_connection()

    insert_medication(
        con,
        "2026-01-01",
        "2026-02-01",
        200,
        "Medication B",
    )
    insert_medication(
        con,
        "2026-03-01",
        "2026-04-01",
        200,
        "Medication B",
    )

    courses = get_patient_medication_courses(con, PATIENT_ID)
    code_courses = courses[courses["CODE"] == 200].reset_index(drop=True)

    assert len(code_courses) == 2
    assert code_courses.iloc[1]["relationship_to_previous_course"] == (
        "after_known_gap"
    )
    assert code_courses.iloc[1]["gap_days"] == 28

    con.close()


def test_source_open_row_does_not_imply_infinite_continuity():
    con = make_test_connection()

    insert_medication(
        con,
        "2020-01-01",
        None,
        300,
        "Medication C",
    )
    insert_medication(
        con,
        "2026-06-01",
        None,
        300,
        "Medication C",
    )

    courses = get_patient_medication_courses(con, PATIENT_ID)
    code_courses = courses[courses["CODE"] == 300].reset_index(drop=True)

    assert len(code_courses) == 2
    assert pd.isna(code_courses.iloc[0]["course_end"])
    assert bool(code_courses.iloc[0]["source_open_course"])
    assert code_courses.iloc[1]["relationship_to_previous_course"] == (
        "after_source_open_unknown"
    )
    assert pd.isna(code_courses.iloc[1]["gap_days"])

    con.close()


def test_build_medication_evidence_separates_new_gap_and_source_open_signals():
    con = make_test_connection()

    # Old source-open record: preserved, but not presented as a recent source-open signal.
    insert_medication(
        con,
        "2005-01-01",
        None,
        500,
        "Old Medication",
    )

    # Known gap followed by a recent subsequent course.
    insert_medication(
        con,
        "2024-01-01",
        "2024-02-01",
        600,
        "Recurring Medication",
    )
    insert_medication(
        con,
        "2026-07-01",
        "2026-07-15",
        600,
        "Recurring Medication",
    )

    # First-ever recent medication with a source-open row.
    insert_medication(
        con,
        "2026-05-04",
        None,
        700,
        "New Medication",
        reasoncode=49436004,
        reasondescription="Atrial fibrillation (disorder)",
    )

    evidence = build_medication_evidence(con, PATIENT_ID)

    assert evidence["status"] == "ok"
    assert evidence["anchor_date"] == "2026-08-12"

    new_codes = {
        item["code"]
        for item in evidence["newly_observed_medications"]
    }
    assert "700" in new_codes
    assert "600" not in new_codes

    subsequent_codes = {
        item["code"]
        for item in evidence["recent_subsequent_medications"]
    }
    assert subsequent_codes == {"600"}

    recurring_pattern = evidence["recent_subsequent_medications"][0]
    assert recurring_pattern["recent_subsequent_course_count"] == 1
    assert recurring_pattern["total_course_count"] == 2
    assert recurring_pattern["latest_subsequent_course_start"] == (
        "2026-07-01"
    )
    assert recurring_pattern["recent_known_gap_days_min"] == 881
    assert recurring_pattern["recent_known_gap_days_max"] == 881

    recent_open_codes = {
        item["code"]
        for item in evidence["recent_source_open_medications"]
    }
    assert recent_open_codes == {"700"}

    old_medication = next(
        item
        for item in evidence["medications"]
        if item["code"] == "500"
    )
    assert old_medication["source_open_course_count"] == 1

    con.close()


def test_repeated_recent_courses_are_promoted_as_one_medication_pattern():
    con = make_test_connection()

    # Repeated single-day source records should remain separate deterministic
    # courses, but should not flood high-level evidence as many pseudo-restarts.
    for start in [
        "2025-09-01",
        "2025-09-04",
        "2025-09-07",
        "2025-09-21",
    ]:
        insert_medication(
            con,
            start,
            start,
            800,
            "Episodic Medication",
            reasoncode=271737000,
            reasondescription="Anemia (disorder)",
        )

    evidence = build_medication_evidence(con, PATIENT_ID)

    assert evidence["course_count"] == 4
    assert evidence["recent_subsequent_medication_count"] == 1

    pattern = evidence["recent_subsequent_medications"][0]
    assert pattern["code"] == "800"
    assert pattern["recent_subsequent_course_count"] == 3
    assert pattern["total_course_count"] == 4
    assert pattern["latest_subsequent_course_start"] == "2025-09-21"
    assert pattern["recent_known_gap_days_min"] == 3
    assert pattern["recent_known_gap_days_max"] == 14

    # Full provenance remains inspectable.
    assert len(evidence["courses"]) == 4

    con.close()
