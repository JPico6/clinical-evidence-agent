"""Deterministic laboratory evidence."""

from datetime import timedelta

from clinical_evidence_agent.data_access import get_patient_latest_date


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
