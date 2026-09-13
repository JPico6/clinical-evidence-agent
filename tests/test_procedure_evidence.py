from clinical_evidence_agent.database import (
    build_procedure_evidence,
    get_connection,
    get_patient_procedure_summary,
    get_patient_recent_procedure_patterns,
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
            DATE TIMESTAMP
        );
        CREATE TABLE conditions (
            PATIENT VARCHAR,
            START TIMESTAMP
        );
        CREATE TABLE medications (
            PATIENT VARCHAR,
            START TIMESTAMP
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

    # Anchor the patient on 2026-08-12 independently of procedures.
    con.execute(
        """
        INSERT INTO encounters
        VALUES (
            'anchor-encounter', ?, TIMESTAMP '2026-08-12 09:00:00',
            TIMESTAMP '2026-08-12 10:00:00', 'outpatient', 1,
            'Anchor encounter', NULL, NULL, 0.0
        )
        """,
        [PATIENT_ID],
    )
    return con


def insert_encounter(
    con,
    encounter_id,
    start,
    stop=None,
    encounter_class="ambulatory",
    description="Procedure encounter",
):
    if stop is None:
        stop = start

    con.execute(
        """
        INSERT INTO encounters
        VALUES (?, ?, ?, ?, ?, 1, ?, NULL, NULL, 0.0)
        """,
        [
            encounter_id,
            PATIENT_ID,
            start,
            stop,
            encounter_class,
            description,
        ],
    )


def insert_procedure(
    con,
    encounter_id,
    start,
    stop,
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
            stop,
            encounter_id,
            code,
            description,
            reasoncode,
            reasondescription,
        ],
    )


def test_procedure_summary_preserves_repeated_events_and_source_reasons():
    con = make_test_connection()
    insert_encounter(con, "enc-1", "2026-01-01 09:00:00")
    insert_encounter(con, "enc-2", "2026-02-01 09:00:00")

    insert_procedure(
        con,
        "enc-1",
        "2026-01-01 09:15:00",
        "2026-01-01 09:30:00",
        100,
        "Repeated procedure",
        10,
        "Reason A",
    )
    insert_procedure(
        con,
        "enc-2",
        "2026-02-01 09:15:00",
        "2026-02-01 09:30:00",
        100,
        "Repeated procedure",
        20,
        "Reason B",
    )

    summary = get_patient_procedure_summary(con, PATIENT_ID)
    row = summary[summary["CODE"] == 100].iloc[0]

    assert row["event_count"] == 2
    assert row["encounter_count"] == 2
    assert str(row["first_start"].date()) == "2026-01-01"
    assert str(row["latest_start"].date()) == "2026-02-01"
    assert row["source_reasons"] == [
        {"code": "10", "description": "Reason A"},
        {"code": "20", "description": "Reason B"},
    ]

    con.close()


def test_recent_procedure_pattern_aggregates_repeated_recent_events():
    con = make_test_connection()

    for index, date in enumerate(
        ["2026-01-01", "2026-01-04", "2026-01-07"],
        start=1,
    ):
        encounter_id = f"dialysis-{index}"
        insert_encounter(con, encounter_id, f"{date} 08:00:00")
        insert_procedure(
            con,
            encounter_id,
            f"{date} 08:10:00",
            f"{date} 11:10:00",
            265764009,
            "Renal dialysis (procedure)",
            431857002,
            "Chronic kidney disease stage 4 (disorder)",
        )

    patterns = get_patient_recent_procedure_patterns(con, PATIENT_ID)
    pattern = patterns[patterns["CODE"] == 265764009].iloc[0]

    assert pattern["recent_event_count"] == 3
    assert pattern["recent_encounter_count"] == 3
    assert pattern["lifetime_event_count"] == 3
    assert pattern["lifetime_encounter_count"] == 3
    assert str(pattern["first_recent_start"].date()) == "2026-01-01"
    assert str(pattern["latest_recent_start"].date()) == "2026-01-07"

    con.close()


def test_build_procedure_evidence_detects_new_first_ever_procedure():
    con = make_test_connection()

    insert_encounter(con, "old-enc", "2024-01-01 08:00:00")
    insert_procedure(
        con,
        "old-enc",
        "2024-01-01 08:10:00",
        "2024-01-01 08:20:00",
        200,
        "Old procedure",
    )

    insert_encounter(con, "new-enc", "2026-05-04 07:30:00")
    insert_procedure(
        con,
        "new-enc",
        "2026-05-04 07:39:55",
        "2026-05-04 07:45:00",
        180325003,
        "Direct current cardioversion (procedure)",
        49436004,
        "Atrial fibrillation (disorder)",
    )

    evidence = build_procedure_evidence(con, PATIENT_ID)

    assert evidence["status"] == "ok"
    assert evidence["anchor_date"] == "2026-08-12"

    new_codes = {
        item["code"] for item in evidence["newly_observed_procedures"]
    }
    assert "180325003" in new_codes
    assert "200" not in new_codes

    cardioversion = next(
        item
        for item in evidence["newly_observed_procedures"]
        if item["code"] == "180325003"
    )
    assert cardioversion["first_start"] == "2026-05-04"
    assert cardioversion["source_reasons"] == [
        {
            "code": "49436004",
            "description": "Atrial fibrillation (disorder)",
        }
    ]

    con.close()


def test_same_code_repeated_within_one_encounter_is_not_deduplicated():
    con = make_test_connection()
    insert_encounter(
        con,
        "hospice-enc",
        "2026-06-01 08:00:00",
        encounter_class="hospice",
        description="Admission to hospice (procedure)",
    )

    insert_procedure(
        con,
        "hospice-enc",
        "2026-06-01 08:00:00",
        "2026-06-01 08:30:00",
        385763009,
        "Hospice care (regime/therapy)",
    )
    insert_procedure(
        con,
        "hospice-enc",
        "2026-06-02 08:00:00",
        "2026-06-02 08:30:00",
        385763009,
        "Hospice care (regime/therapy)",
    )

    evidence = build_procedure_evidence(con, PATIENT_ID)
    encounter = next(
        item
        for item in evidence["recent_procedure_encounters"]
        if item["encounter_id"] == "hospice-enc"
    )

    assert encounter["procedure_event_count"] == 2
    assert encounter["distinct_procedure_code_count"] == 1
    assert len(encounter["procedures"]) == 2
    assert encounter["procedures"][0]["start"].startswith(
        "2026-06-01T08:00:00"
    )
    assert encounter["procedures"][1]["start"].startswith(
        "2026-06-02T08:00:00"
    )

    con.close()


def test_encounter_context_preserves_span_when_procedure_occurs_days_later():
    con = make_test_connection()
    insert_encounter(
        con,
        "extended-enc",
        "2026-04-29 07:39:55",
        stop="2026-05-04 09:00:00",
        encounter_class="emergency",
        description="Emergency room admission (procedure)",
    )

    insert_procedure(
        con,
        "extended-enc",
        "2026-04-29 08:00:00",
        "2026-04-29 08:30:00",
        100,
        "Initial procedure",
    )
    insert_procedure(
        con,
        "extended-enc",
        "2026-05-04 07:39:55",
        "2026-05-04 08:35:38",
        180325003,
        "Direct current cardioversion (procedure)",
        49436004,
        "Atrial fibrillation (disorder)",
    )

    evidence = build_procedure_evidence(con, PATIENT_ID)
    encounter = next(
        item
        for item in evidence["recent_procedure_encounters"]
        if item["encounter_id"] == "extended-enc"
    )

    assert encounter["encounter_start"].startswith(
        "2026-04-29T07:39:55"
    )
    assert encounter["encounter_stop"].startswith(
        "2026-05-04T09:00:00"
    )
    assert encounter["first_procedure_start"].startswith(
        "2026-04-29T08:00:00"
    )
    assert encounter["latest_procedure_start"].startswith(
        "2026-05-04T07:39:55"
    )
    assert encounter["procedure_event_count"] == 2
    assert [item["code"] for item in encounter["procedures"]] == [
        "100",
        "180325003",
    ]

    con.close()


def test_build_procedure_evidence_no_data():
    con = make_test_connection()

    evidence = build_procedure_evidence(con, "patient-with-no-data")

    assert evidence == {
        "status": "no_data",
        "patient_id": "patient-with-no-data",
    }

    con.close()
