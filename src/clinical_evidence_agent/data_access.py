"""DuckDB connection, Synthea registration, raw retrieval, and shared patient dating."""

import os
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("CLINICAL_EVIDENCE_DATA_DIR", PROJECT_ROOT / "data" / "synthea")).resolve()


def get_connection():
    return duckdb.connect()

def register_synthea_tables(con):
    tables = [
        "patients",
        "encounters",
        "conditions",
        "medications",
        "observations",
        "claims",
        "procedures",
    ]

    for table in tables:
        path = DATA_DIR / f"{table}.csv"

        if path.exists():
            con.execute(
                f"""
                CREATE OR REPLACE VIEW {table} AS
                SELECT *
                FROM read_csv_auto('{path.as_posix()}')
                """
            )

def get_patient_conditions(con, patient_id: str):
    return con.execute(
        """
        SELECT
            START,
            STOP,
            CODE,
            DESCRIPTION
        FROM conditions
        WHERE PATIENT = ?
        ORDER BY START, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

def get_patient_medications(con, patient_id: str):
    return con.execute(
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
        ORDER BY START, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

def get_patient_observations(con, patient_id: str):
    return con.execute(
        """
        SELECT
            DATE,
            ENCOUNTER,
            CATEGORY,
            CODE,
            DESCRIPTION,
            VALUE,
            UNITS,
            TYPE
        FROM observations
        WHERE PATIENT = ?
        ORDER BY DATE, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

def get_patient_encounters(con, patient_id: str):
    return con.execute(
        """
        SELECT
            Id AS encounter_id,
            START,
            STOP,
            ENCOUNTERCLASS,
            CODE,
            DESCRIPTION,
            REASONCODE,
            REASONDESCRIPTION,
            TOTAL_CLAIM_COST
        FROM encounters
        WHERE PATIENT = ?
        ORDER BY START
        """,
        [patient_id],
    ).fetchdf()

def get_patient_procedures(con, patient_id: str):
    return con.execute(
        """
        SELECT
            START,
            STOP,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            REASONCODE,
            REASONDESCRIPTION
        FROM procedures
        WHERE PATIENT = ?
        ORDER BY START, DESCRIPTION
        """,
        [patient_id],
    ).fetchdf()

def get_patient_demographics(con, patient_id: str):
    return con.execute(
        """
        SELECT
            Id AS patient_id,
            BIRTHDATE,
            DEATHDATE,
            GENDER,
            RACE,
            ETHNICITY
        FROM patients
        WHERE Id = ?
        """,
        [patient_id],
    ).fetchdf()

def get_patient_latest_date(con, patient_id: str):
    return con.execute(
        """
        SELECT MAX(event_date) AS latest_date
        FROM (
            SELECT CAST(START AS DATE) AS event_date
            FROM encounters
            WHERE PATIENT = ?

            UNION ALL

            SELECT CAST(DATE AS DATE) AS event_date
            FROM observations
            WHERE PATIENT = ?

            UNION ALL

            SELECT CAST(START AS DATE) AS event_date
            FROM conditions
            WHERE PATIENT = ?

            UNION ALL

            SELECT CAST(START AS DATE) AS event_date
            FROM medications
            WHERE PATIENT = ?

            UNION ALL

            SELECT CAST(START AS DATE) AS event_date
            FROM procedures
            WHERE PATIENT = ?
        )
        """,
        [patient_id] * 5,
    ).fetchone()[0]
