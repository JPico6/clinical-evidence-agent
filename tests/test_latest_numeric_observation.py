from clinical_evidence_agent import database
from clinical_evidence_agent.evidence.labs import (
    build_lab_evidence,
    get_patient_latest_numeric_observation,
)


RICH_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def test_latest_numeric_observation_is_exposed_for_exact_code_unit():
    con = database.get_connection()
    database.register_synthea_tables(con)

    latest = get_patient_latest_numeric_observation(
        con,
        RICH_PATIENT_ID,
        "33914-3",
        "mL/min/{1.73_m2}",
    )

    assert latest is not None
    assert latest["date"] is not None
    assert latest["ambiguous"] is False
    assert isinstance(latest["value"], float)

    con.close()


def test_lab_evidence_includes_latest_measurement():
    con = database.get_connection()
    database.register_synthea_tables(con)

    evidence = build_lab_evidence(
        con,
        RICH_PATIENT_ID,
        "2823-3",
        unit="mmol/L",
    )

    assert evidence["status"] == "ok"
    assert evidence["latest_measurement"] is not None
    assert evidence["latest_measurement"]["date"] <= evidence["anchor_date"]
    assert "value" in evidence["latest_measurement"]
    assert "ambiguous" in evidence["latest_measurement"]

    con.close()


def test_sparse_lab_still_has_latest_measurement_without_inventing_trajectory():
    con = database.get_connection()
    database.register_synthea_tables(con)

    evidence = build_lab_evidence(
        con,
        RICH_PATIENT_ID,
        "718-7",
        unit="g/dL",
    )

    assert evidence["latest_measurement"] == {
        "date": "2026-02-18",
        "value": 15.9,
        "ambiguous": False,
    }
    assert evidence["evidence_sufficiency"] == "no_prior_data"
    assert evidence["change"]["median_absolute"] is None
    assert evidence["change"]["median_percent"] is None

    con.close()


def test_latest_numeric_observation_preserves_same_timestamp_value_ambiguity():
    con = database.get_connection()

    con.execute(
        """
        CREATE TABLE observations (
            DATE TIMESTAMP,
            PATIENT VARCHAR,
            ENCOUNTER VARCHAR,
            CODE VARCHAR,
            DESCRIPTION VARCHAR,
            VALUE VARCHAR,
            UNITS VARCHAR,
            TYPE VARCHAR
        )
        """
    )
    con.executemany(
        """
        INSERT INTO observations
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "2026-01-01 10:00:00",
                "p1",
                "e1",
                "x",
                "Example",
                "1.0",
                "u",
                "numeric",
            ),
            (
                "2026-02-01 10:00:00",
                "p1",
                "e2",
                "x",
                "Example",
                "2.0",
                "u",
                "numeric",
            ),
            (
                "2026-02-01 15:00:00",
                "p1",
                "e3",
                "x",
                "Example",
                "3.0",
                "u",
                "numeric",
            ),
        ],
    )

    latest = get_patient_latest_numeric_observation(con, "p1", "x", "u")

    assert latest["ambiguous"] is True
    assert latest["value"] is None
    assert latest["values"] == [2.0, 3.0]

    con.close()
