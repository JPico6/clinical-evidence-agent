from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "synthea"


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

from datetime import timedelta


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


import pandas as pd


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

def get_patient_egfr(con, patient_id: str):
    return con.execute(
        """
        SELECT
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            VALUE,
            UNITS,
            TYPE
        FROM observations
        WHERE PATIENT = ?
          AND CODE = '33914-3'
        ORDER BY DATE
        """,
        [patient_id],
    ).fetchdf()


def get_patient_lab_conflicts(con, patient_id: str, code: str):
    return con.execute(
        """
        SELECT
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            UNITS,
            COUNT(*) AS row_count,
            COUNT(DISTINCT VALUE) AS distinct_value_count,
            STRING_AGG(DISTINCT VALUE, ' | ') AS values_seen
        FROM observations
        WHERE PATIENT = ?
          AND CODE = ?
        GROUP BY
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            UNITS
        HAVING COUNT(DISTINCT VALUE) > 1
        ORDER BY DATE
        """,
        [patient_id, code],
    ).fetchdf()


def get_patient_unambiguous_lab_history(con, patient_id: str, code: str):
    return con.execute(
        """
        SELECT
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            TRY_CAST(MIN(VALUE) AS DOUBLE) AS value,
            UNITS
        FROM observations
        WHERE PATIENT = ?
          AND CODE = ?
          AND TYPE = 'numeric'
        GROUP BY
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            UNITS
        HAVING COUNT(DISTINCT VALUE) = 1
        ORDER BY DATE
        """,
        [patient_id, code],
    ).fetchdf()


def get_patient_numeric_lab_history(con, patient_id: str, code: str):
    return con.execute(
        """
        SELECT
            DATE,
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            TRY_CAST(VALUE AS DOUBLE) AS value,
            UNITS
        FROM observations
        WHERE PATIENT = ?
          AND CODE = ?
          AND TYPE = 'numeric'
          AND TRY_CAST(VALUE AS DOUBLE) IS NOT NULL
        ORDER BY DATE, ENCOUNTER, value
        """,
        [patient_id, code],
    ).fetchdf()


def summarize_lab_by_year(con, patient_id: str, code: str):
    return con.execute(
        """
        SELECT
            EXTRACT(YEAR FROM DATE) AS year,
            COUNT(*) AS measurement_count,
            MEDIAN(TRY_CAST(VALUE AS DOUBLE)) AS median_value,
            MIN(TRY_CAST(VALUE AS DOUBLE)) AS min_value,
            MAX(TRY_CAST(VALUE AS DOUBLE)) AS max_value
        FROM observations
        WHERE PATIENT = ?
          AND CODE = ?
          AND TYPE = 'numeric'
          AND TRY_CAST(VALUE AS DOUBLE) IS NOT NULL
        GROUP BY EXTRACT(YEAR FROM DATE)
        ORDER BY year
        """,
        [patient_id, code],
    ).fetchdf()


from datetime import timedelta


def compare_lab_recent_vs_prior(
    con,
    patient_id: str,
    code: str,
    unit: str | None = None,
):
    units = get_patient_lab_units(con, patient_id, code)

    if units.empty:
        return {
            "status": "no_data",
            "patient_id": patient_id,
            "code": code,
        }

    if unit is None:
        if len(units) > 1:
            return {
                "status": "multiple_units",
                "patient_id": patient_id,
                "code": code,
                "available_units": units,
            }

        unit = units.iloc[0]["UNITS"]
    anchor_date = get_patient_latest_date(con, patient_id)
    end_exclusive = anchor_date + timedelta(days=1)

    recent_start = end_exclusive - timedelta(days=365)
    prior_start = recent_start - timedelta(days=365)

    summary = con.execute(
    """
    SELECT
        CASE
            WHEN CAST(DATE AS DATE) >= ?
             AND CAST(DATE AS DATE) < ?
                THEN 'prior'
            WHEN CAST(DATE AS DATE) >= ?
             AND CAST(DATE AS DATE) < ?
                THEN 'recent'
        END AS period,
        COUNT(*) AS measurement_count,
        MEDIAN(TRY_CAST(VALUE AS DOUBLE)) AS median_value,
        QUANTILE_CONT(TRY_CAST(VALUE AS DOUBLE), 0.25) AS q1_value,
        QUANTILE_CONT(TRY_CAST(VALUE AS DOUBLE), 0.75) AS q3_value,
        MIN(TRY_CAST(VALUE AS DOUBLE)) AS min_value,
        MAX(TRY_CAST(VALUE AS DOUBLE)) AS max_value
    FROM observations
    WHERE PATIENT = ?
      AND CODE = ?
      AND UNITS = ?
      AND TYPE = 'numeric'
      AND TRY_CAST(VALUE AS DOUBLE) IS NOT NULL
      AND CAST(DATE AS DATE) >= ?
      AND CAST(DATE AS DATE) < ?
    GROUP BY period
    ORDER BY period
    """,
    [
        prior_start,
        recent_start,
        recent_start,
        end_exclusive,
        patient_id,
        code,
        unit,
        prior_start,
        end_exclusive,
    ]
    ).fetchdf()

    prior_row = summary[summary["period"] == "prior"]
    recent_row = summary[summary["period"] == "recent"]

    median_change = None
    median_percent_change = None

    if not prior_row.empty and not recent_row.empty:
        prior_median = float(prior_row.iloc[0]["median_value"])
        recent_median = float(recent_row.iloc[0]["median_value"])

        median_change = recent_median - prior_median

        if prior_median != 0:
            median_percent_change = (
                                            median_change / prior_median
                                    ) * 100

    prior_count = (
        int(prior_row.iloc[0]["measurement_count"])
        if not prior_row.empty else 0
    )

    recent_count = (
        int(recent_row.iloc[0]["measurement_count"])
        if not recent_row.empty else 0
    )

    evidence_sufficiency = classify_lab_evidence_sufficiency(
        prior_count,
        recent_count,
    )

    prior_q1 = (
        float(prior_row.iloc[0]["q1_value"])
        if not prior_row.empty
        else None
    )

    prior_q3 = (
        float(prior_row.iloc[0]["q3_value"])
        if not prior_row.empty
        else None
    )

    recent_q1 = (
        float(recent_row.iloc[0]["q1_value"])
        if not recent_row.empty
        else None
    )

    recent_q3 = (
        float(recent_row.iloc[0]["q3_value"])
        if not recent_row.empty
        else None
    )

    prior_iqr = (
        prior_q3 - prior_q1
        if prior_q1 is not None and prior_q3 is not None
        else None
    )

    recent_iqr = (
        recent_q3 - recent_q1
        if recent_q1 is not None and recent_q3 is not None
        else None
    )

    iqr_change = (
        recent_iqr - prior_iqr
        if prior_iqr is not None and recent_iqr is not None
        else None
    )


    return {
        "status": "ok",
        "patient_id": patient_id,
        "code": code,
        "unit": unit,
        "anchor_date": anchor_date,
        "prior_period": {
            "start": prior_start,
            "end": recent_start - timedelta(days=1),
        },
        "recent_period": {
            "start": recent_start,
            "end": anchor_date,
        },
        "evidence_sufficiency": evidence_sufficiency,
        "median_change": median_change,
        "median_percent_change": median_percent_change,
        "prior_iqr": prior_iqr,
        "recent_iqr": recent_iqr,
        "iqr_change": iqr_change,
        "summary": summary,
    }


def build_lab_evidence(
    con,
    patient_id: str,
    code: str,
    unit: str | None = None,
):
    result = compare_lab_recent_vs_prior(
        con,
        patient_id,
        code,
        unit=unit,
    )

    def clean_date(value):
        if value is None:
            return None

        if hasattr(value, "date"):
            value = value.date()

        return value.isoformat()
    def clean_float(value, digits=2):
        if value is None:
            return None
        return round(float(value), digits)

    status = result["status"]

    # No usable data for this patient/code.
    if status == "no_data":
        return {
            "status": "no_data",
            "patient_id": patient_id,
            "code": code,
        }

    # More than one unit exists. Do not silently combine them.
    if status == "multiple_units":
        units = result["available_units"]

        return {
            "status": "multiple_units",
            "patient_id": patient_id,
            "code": code,
            "available_units": [
                {
                    "unit": row["UNITS"],
                    "measurement_count": int(row["measurement_count"]),
                    "first_date": clean_date(row["first_date"]),
                    "last_date": clean_date(row["last_date"]),
                }
                for _, row in units.iterrows()
            ],
        }

    summary = result["summary"]

    prior_row = summary[summary["period"] == "prior"]
    recent_row = summary[summary["period"] == "recent"]

    def period_stats(row):
        if row.empty:
            return None

        row = row.iloc[0]
        measurement_count = int(row["measurement_count"])

        return {
            "measurement_count": measurement_count,
            "median": clean_float(row["median_value"]),
            "q1": (
                clean_float(row["q1_value"])
                if measurement_count >= 2
                else None
            ),
            "q3": (
                clean_float(row["q3_value"])
                if measurement_count >= 2
                else None
            ),
            "iqr": (
                clean_float(
                    row["q3_value"] - row["q1_value"]
                )
                if measurement_count >= 2
                else None
            ),
            "min": clean_float(row["min_value"]),
            "max": clean_float(row["max_value"]),
        }

    prior_stats = period_stats(prior_row)
    recent_stats = period_stats(recent_row)

    iqr_change = (
        clean_float(result["iqr_change"])
        if (
                prior_stats is not None
                and recent_stats is not None
                and prior_stats["measurement_count"] >= 2
                and recent_stats["measurement_count"] >= 2
        )
        else None
    )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "code": code,
        "unit": result["unit"],
        "anchor_date": result["anchor_date"].isoformat(),
        "evidence_sufficiency": result["evidence_sufficiency"],
        "prior_period": {
            "start": result["prior_period"]["start"].isoformat(),
            "end": result["prior_period"]["end"].isoformat(),
            "statistics": prior_stats,
        },
        "recent_period": {
            "start": result["recent_period"]["start"].isoformat(),
            "end": result["recent_period"]["end"].isoformat(),
            "statistics": recent_stats,
        },
        "change": {
            "median_absolute": clean_float(
                result["median_change"]
            ),
            "median_percent": clean_float(
                result["median_percent_change"]
            ),
            "iqr_change": iqr_change,
        },
    }


def classify_lab_evidence_sufficiency(prior_count: int, recent_count: int) -> str:
    if recent_count == 0:
        return "no_recent_data"

    if prior_count == 0:
        return "no_prior_data"

    if prior_count == 1 or recent_count == 1:
        return "single_point_comparison"

    return "multi_point_comparison"


def get_patient_lab_units(con, patient_id: str, code: str):
    return con.execute(
        """
        SELECT
            UNITS,
            COUNT(*) AS measurement_count,
            MIN(CAST(DATE AS DATE)) AS first_date,
            MAX(CAST(DATE AS DATE)) AS last_date
        FROM observations
        WHERE PATIENT = ?
          AND CODE = ?
          AND TYPE = 'numeric'
          AND TRY_CAST(VALUE AS DOUBLE) IS NOT NULL
        GROUP BY UNITS
        ORDER BY measurement_count DESC
        """,
        [patient_id, code],
    ).fetchdf()


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
