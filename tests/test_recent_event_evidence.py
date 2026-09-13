from clinical_evidence_agent.database import (
    build_recent_event_evidence,
    get_connection,
)


PATIENT_ID = "patient-1"


def make_test_connection():
    con = get_connection()
    con.execute(
        """
        CREATE TABLE encounters (
            Id VARCHAR,
            PATIENT VARCHAR,
            START TIMESTAMP,
            STOP TIMESTAMP,
            ENCOUNTERCLASS VARCHAR,
            CODE BIGINT,
            DESCRIPTION VARCHAR,
            REASONCODE BIGINT,
            REASONDESCRIPTION VARCHAR,
            TOTAL_CLAIM_COST DOUBLE
        );
        CREATE TABLE observations (
            PATIENT VARCHAR,
            DATE TIMESTAMP,
            ENCOUNTER VARCHAR,
            CATEGORY VARCHAR,
            CODE VARCHAR,
            DESCRIPTION VARCHAR,
            VALUE VARCHAR,
            UNITS VARCHAR,
            TYPE VARCHAR
        );
        CREATE TABLE conditions (
            PATIENT VARCHAR,
            START TIMESTAMP,
            STOP TIMESTAMP,
            CODE BIGINT,
            DESCRIPTION VARCHAR
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
        CREATE TABLE procedures (
            PATIENT VARCHAR,
            START TIMESTAMP,
            STOP TIMESTAMP,
            ENCOUNTER VARCHAR,
            CODE BIGINT,
            DESCRIPTION VARCHAR,
            REASONCODE BIGINT,
            REASONDESCRIPTION VARCHAR
        );
        """
    )

    con.execute(
        """
        INSERT INTO encounters
        VALUES (
            'anchor', ?, TIMESTAMP '2026-08-12 09:00:00',
            TIMESTAMP '2026-08-12 10:00:00', 'outpatient', 1,
            'Anchor encounter', NULL, NULL, 0.0
        )
        """,
        [PATIENT_ID],
    )
    return con


def insert_condition(con, start, code, description, stop=None):
    con.execute(
        "INSERT INTO conditions VALUES (?, ?, ?, ?, ?)",
        [PATIENT_ID, start, stop, code, description],
    )


def insert_medication(
    con,
    start,
    code,
    description,
    reasoncode=None,
    reasondescription=None,
    stop=None,
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


def insert_procedure(
    con,
    encounter_id,
    start,
    code,
    description,
    reasoncode=None,
    reasondescription=None,
):
    con.execute(
        """
        INSERT INTO procedures
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            PATIENT_ID,
            start,
            start,
            encounter_id,
            code,
            description,
            reasoncode,
            reasondescription,
        ],
    )


def test_same_date_new_signals_form_one_multi_domain_event_candidate():
    con = make_test_connection()

    con.execute(
        """
        INSERT INTO encounters
        VALUES (
            'af-encounter', ?, TIMESTAMP '2026-04-29 07:39:55',
            TIMESTAMP '2026-05-04 08:35:38', 'emergency', 2,
            'Emergency room admission', NULL, NULL, 0.0
        )
        """,
        [PATIENT_ID],
    )

    insert_condition(
        con,
        "2026-05-04 07:39:55",
        49436004,
        "Atrial fibrillation (disorder)",
    )
    for code, description in [
        (1001, "Digoxin"),
        (1002, "Warfarin"),
        (1003, "Verapamil"),
    ]:
        insert_medication(
            con,
            "2026-05-04 07:39:55",
            code,
            description,
            49436004,
            "Atrial fibrillation (disorder)",
        )

    insert_procedure(
        con,
        "af-encounter",
        "2026-05-04 07:39:55",
        180325003,
        "Direct current cardioversion (procedure)",
        49436004,
        "Atrial fibrillation (disorder)",
    )

    evidence = build_recent_event_evidence(con, PATIENT_ID)

    assert evidence["status"] == "ok"
    assert evidence["event_candidate_count"] == 1
    assert evidence["multi_domain_event_candidate_count"] == 1

    event = evidence["event_candidates"][0]
    assert event["event_date"] == "2026-05-04"
    assert event["multi_domain"] is True
    assert event["domain_count"] == 3
    assert event["domains"] == ["condition", "medication", "procedure"]
    assert event["signal_count"] == 5
    assert event["domain_signal_counts"] == {
        "condition": 1,
        "medication": 3,
        "procedure": 1,
    }

    procedure_signal = next(
        item for item in event["signals"] if item["domain"] == "procedure"
    )
    assert procedure_signal["source_reasons"] == [
        {
            "code": "49436004",
            "description": "Atrial fibrillation (disorder)",
        }
    ]

    con.close()


def test_old_concepts_are_not_promoted_as_recent_event_signals():
    con = make_test_connection()

    insert_condition(
        con,
        "2024-01-01",
        200,
        "Old condition",
    )
    insert_medication(
        con,
        "2024-01-01",
        300,
        "Old medication",
    )

    evidence = build_recent_event_evidence(con, PATIENT_ID)

    assert evidence["source_signal_count"] == 0
    assert evidence["event_candidate_count"] == 0
    assert evidence["event_candidates"] == []

    con.close()


def test_single_domain_first_observation_is_preserved_without_importance_claim():
    con = make_test_connection()

    insert_condition(
        con,
        "2025-12-03",
        278558000,
        "Dental filling lost (finding)",
    )

    evidence = build_recent_event_evidence(con, PATIENT_ID)
    event = evidence["event_candidates"][0]

    assert event["event_date"] == "2025-12-03"
    assert event["multi_domain"] is False
    assert event["domains"] == ["condition"]
    assert event["signal_count"] == 1
    assert event["signals"][0]["signal_type"] == (
        "newly_observed_condition"
    )

    con.close()


def test_same_day_multiple_signals_within_one_domain_remain_distinct():
    con = make_test_connection()

    insert_medication(con, "2026-06-01", 401, "Medication A")
    insert_medication(con, "2026-06-01", 402, "Medication B")

    evidence = build_recent_event_evidence(con, PATIENT_ID)
    event = evidence["event_candidates"][0]

    assert event["multi_domain"] is False
    assert event["domain_count"] == 1
    assert event["signal_count"] == 2
    assert event["domain_signal_counts"] == {"medication": 2}
    assert {item["code"] for item in event["signals"]} == {"401", "402"}

    con.close()


def test_no_patient_data_returns_structured_no_data():
    con = make_test_connection()

    evidence = build_recent_event_evidence(con, "missing-patient")

    assert evidence == {
        "status": "no_data",
        "patient_id": "missing-patient",
    }

    con.close()
