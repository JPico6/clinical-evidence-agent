"""Exploratory diagnostics for Synthea procedure records.

This script is intentionally NOT part of the production evidence API. Its purpose is
only to inspect procedure source semantics before designing deterministic procedure
evidence.

Run from the repository root with:
    uv run python scripts/procedure_diagnostics.py
"""

from __future__ import annotations

import pandas as pd

from clinical_evidence_agent.database import (
    get_connection,
    get_patient_procedures,
    register_synthea_tables,
)


REFERENCE_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def print_section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def require_procedures_table(con) -> None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if "procedures" not in tables:
        raise RuntimeError(
            "The procedures view is not registered. Expected local Synthea data at "
            "data/synthea/procedures.csv."
        )


def procedures_schema(con) -> pd.DataFrame:
    return con.execute("DESCRIBE procedures").fetchdf()


def procedure_columns(con) -> set[str]:
    return {
        row[0].upper()
        for row in con.execute("DESCRIBE procedures").fetchall()
    }


def dataset_summary(con) -> pd.DataFrame:
    cols = procedure_columns(con)
    stop_expr = (
        "SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS missing_stop_rows, "
        "ROUND(100.0 * SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) "
        "AS missing_stop_pct, "
        if "STOP" in cols
        else "NULL AS missing_stop_rows, NULL AS missing_stop_pct, "
    )

    return con.execute(
        f"""
        SELECT
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT PATIENT) AS patients_with_procedures,
            COUNT(DISTINCT CODE) AS distinct_codes,
            COUNT(DISTINCT DESCRIPTION) AS distinct_descriptions,
            COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters,
            {stop_expr}
            SUM(CASE WHEN ENCOUNTER IS NULL THEN 1 ELSE 0 END) AS missing_encounter_rows,
            SUM(CASE WHEN REASONCODE IS NOT NULL THEN 1 ELSE 0 END) AS reasoncode_present_rows,
            ROUND(
                100.0 * SUM(CASE WHEN REASONCODE IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                2
            ) AS reasoncode_present_pct,
            SUM(CASE WHEN REASONDESCRIPTION IS NOT NULL THEN 1 ELSE 0 END) AS reasondescription_present_rows,
            ROUND(
                100.0 * SUM(CASE WHEN REASONDESCRIPTION IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                2
            ) AS reasondescription_present_pct
        FROM procedures
        """
    ).fetchdf()


def duration_summary(con) -> pd.DataFrame:
    cols = procedure_columns(con)
    if "STOP" not in cols:
        return pd.DataFrame(
            [{"note": "STOP column not present; duration diagnostics are not applicable."}]
        )

    return con.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE STOP IS NOT NULL) AS rows_with_known_stop,
            COUNT(*) FILTER (WHERE STOP IS NULL) AS rows_with_missing_stop,
            COUNT(*) FILTER (WHERE STOP < START) AS stop_before_start_rows,
            COUNT(*) FILTER (WHERE STOP = START) AS zero_duration_rows,
            COUNT(*) FILTER (WHERE STOP > START) AS positive_duration_rows,
            MIN(DATE_DIFF('day', CAST(START AS DATE), CAST(STOP AS DATE))) FILTER (WHERE STOP IS NOT NULL)
                AS min_duration_days,
            MEDIAN(DATE_DIFF('day', CAST(START AS DATE), CAST(STOP AS DATE))) FILTER (WHERE STOP IS NOT NULL)
                AS median_duration_days,
            QUANTILE_CONT(
                DATE_DIFF('day', CAST(START AS DATE), CAST(STOP AS DATE)), 0.95
            ) FILTER (WHERE STOP IS NOT NULL) AS p95_duration_days,
            MAX(DATE_DIFF('day', CAST(START AS DATE), CAST(STOP AS DATE))) FILTER (WHERE STOP IS NOT NULL)
                AS max_duration_days
        FROM procedures
        """
    ).fetchdf()


def most_common_procedure_codes(con, limit: int = 25) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT PATIENT) AS patient_count,
            COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS encounter_count,
            COUNT(DISTINCT REASONCODE) FILTER (WHERE REASONCODE IS NOT NULL) AS distinct_reason_codes
        FROM procedures
        GROUP BY CODE
        ORDER BY procedure_rows DESC, patient_count DESC, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def repeated_patient_code_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH patient_code AS (
            SELECT
                PATIENT,
                CODE,
                COUNT(*) AS procedure_rows,
                COUNT(DISTINCT CAST(START AS DATE)) AS distinct_start_dates,
                COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters
            FROM procedures
            GROUP BY PATIENT, CODE
        )
        SELECT
            COUNT(*) AS patient_code_pairs,
            COUNT(*) FILTER (WHERE procedure_rows > 1) AS repeated_patient_code_pairs,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE procedure_rows > 1) / NULLIF(COUNT(*), 0),
                2
            ) AS repeated_patient_code_pct,
            MAX(procedure_rows) AS max_rows_for_one_patient_code,
            MAX(distinct_start_dates) AS max_start_dates_for_one_patient_code,
            MAX(distinct_encounters) AS max_encounters_for_one_patient_code
        FROM patient_code
        """
    ).fetchdf()


def most_repeated_patient_codes(con, limit: int = 25) -> pd.DataFrame:
    cols = procedure_columns(con)
    source_open_expr = (
        "SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS source_open_rows"
        if "STOP" in cols
        else "NULL AS source_open_rows"
    )
    return con.execute(
        f"""
        SELECT
            PATIENT,
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT CAST(START AS DATE)) AS distinct_start_dates,
            COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters,
            MIN(START) AS first_start,
            MAX(START) AS latest_start,
            {source_open_expr}
        FROM procedures
        GROUP BY PATIENT, CODE
        HAVING COUNT(*) > 1
        ORDER BY procedure_rows DESC, distinct_start_dates DESC, PATIENT, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def exact_duplicate_candidates(con, limit: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    cols = procedure_columns(con)
    stop_group = "STOP," if "STOP" in cols else ""
    stop_select = "STOP," if "STOP" in cols else ""

    summary = con.execute(
        f"""
        WITH duplicate_groups AS (
            SELECT
                PATIENT,
                START,
                {stop_group}
                ENCOUNTER,
                CODE,
                DESCRIPTION,
                REASONCODE,
                REASONDESCRIPTION,
                COUNT(*) AS row_count
            FROM procedures
            GROUP BY ALL
            HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) AS duplicate_groups,
            COALESCE(SUM(row_count), 0) AS rows_in_duplicate_groups,
            COALESCE(SUM(row_count - 1), 0) AS excess_duplicate_rows,
            COALESCE(MAX(row_count), 0) AS largest_duplicate_group
        FROM duplicate_groups
        """
    ).fetchdf()

    examples = con.execute(
        f"""
        SELECT
            PATIENT,
            START,
            {stop_select}
            ENCOUNTER,
            CODE,
            DESCRIPTION,
            REASONCODE,
            REASONDESCRIPTION,
            COUNT(*) AS row_count
        FROM procedures
        GROUP BY ALL
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, PATIENT, START, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def code_description_consistency(con, limit: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = con.execute(
        """
        WITH code_map AS (
            SELECT CODE, COUNT(DISTINCT DESCRIPTION) AS description_count
            FROM procedures
            GROUP BY CODE
        ),
        description_map AS (
            SELECT DESCRIPTION, COUNT(DISTINCT CODE) AS code_count
            FROM procedures
            GROUP BY DESCRIPTION
        )
        SELECT
            COUNT(*) FILTER (WHERE description_count > 1) AS codes_with_multiple_descriptions,
            MAX(description_count) AS max_descriptions_per_code,
            (SELECT COUNT(*) FROM description_map WHERE code_count > 1) AS descriptions_with_multiple_codes,
            (SELECT MAX(code_count) FROM description_map) AS max_codes_per_description
        FROM code_map
        """
    ).fetchdf()

    examples = con.execute(
        """
        SELECT
            CODE,
            COUNT(DISTINCT DESCRIPTION) AS description_count,
            STRING_AGG(DISTINCT DESCRIPTION, ' | ' ORDER BY DESCRIPTION) AS descriptions
        FROM procedures
        GROUP BY CODE
        HAVING COUNT(DISTINCT DESCRIPTION) > 1
        ORDER BY description_count DESC, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def encounter_linkage_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            COUNT(*) AS procedure_rows,
            COUNT(*) FILTER (WHERE p.ENCOUNTER IS NULL) AS missing_encounter_rows,
            COUNT(*) FILTER (WHERE p.ENCOUNTER IS NOT NULL AND e.Id IS NULL) AS unmatched_encounter_rows,
            COUNT(*) FILTER (WHERE e.Id IS NOT NULL AND p.PATIENT <> e.PATIENT) AS patient_mismatch_rows,
            COUNT(DISTINCT p.ENCOUNTER) FILTER (WHERE p.ENCOUNTER IS NOT NULL) AS procedure_encounters,
            COUNT(DISTINCT p.ENCOUNTER) FILTER (WHERE e.Id IS NOT NULL) AS matched_procedure_encounters
        FROM procedures p
        LEFT JOIN encounters e
            ON p.ENCOUNTER = e.Id
        """
    ).fetchdf()


def procedures_per_encounter_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH per_encounter AS (
            SELECT
                PATIENT,
                ENCOUNTER,
                COUNT(*) AS procedure_rows,
                COUNT(DISTINCT CODE) AS distinct_codes,
                COUNT(DISTINCT CAST(START AS DATE)) AS distinct_start_dates
            FROM procedures
            WHERE ENCOUNTER IS NOT NULL
            GROUP BY PATIENT, ENCOUNTER
        )
        SELECT
            COUNT(*) AS encounters_with_procedures,
            COUNT(*) FILTER (WHERE procedure_rows > 1) AS encounters_with_multiple_procedure_rows,
            ROUND(
                100.0 * COUNT(*) FILTER (WHERE procedure_rows > 1) / NULLIF(COUNT(*), 0),
                2
            ) AS multi_procedure_encounter_pct,
            MEDIAN(procedure_rows) AS median_rows_per_procedure_encounter,
            QUANTILE_CONT(procedure_rows, 0.95) AS p95_rows_per_procedure_encounter,
            MAX(procedure_rows) AS max_rows_per_procedure_encounter,
            MAX(distinct_codes) AS max_distinct_codes_per_encounter,
            MAX(distinct_start_dates) AS max_distinct_start_dates_per_encounter
        FROM per_encounter
        """
    ).fetchdf()


def busiest_procedure_encounters(con, limit: int = 25) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            p.PATIENT,
            p.ENCOUNTER,
            MIN(e.START) AS encounter_start,
            MIN(e.ENCOUNTERCLASS) AS encounter_class,
            MIN(e.DESCRIPTION) AS encounter_description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT p.CODE) AS distinct_procedure_codes,
            STRING_AGG(DISTINCT p.DESCRIPTION, ' | ' ORDER BY p.DESCRIPTION) AS procedure_descriptions
        FROM procedures p
        LEFT JOIN encounters e
            ON p.ENCOUNTER = e.Id
        WHERE p.ENCOUNTER IS NOT NULL
        GROUP BY p.PATIENT, p.ENCOUNTER
        HAVING COUNT(*) > 1
        ORDER BY procedure_rows DESC, distinct_procedure_codes DESC, p.PATIENT, encounter_start
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def same_encounter_code_multiplicity(con, limit: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = con.execute(
        """
        WITH groups AS (
            SELECT
                PATIENT,
                ENCOUNTER,
                CODE,
                COUNT(*) AS row_count,
                COUNT(DISTINCT CAST(START AS DATE)) AS distinct_start_dates
            FROM procedures
            WHERE ENCOUNTER IS NOT NULL
            GROUP BY PATIENT, ENCOUNTER, CODE
            HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) AS repeated_patient_encounter_code_groups,
            COALESCE(SUM(row_count), 0) AS rows_in_groups,
            COALESCE(MAX(row_count), 0) AS max_rows_in_group,
            COALESCE(MAX(distinct_start_dates), 0) AS max_distinct_start_dates_in_group
        FROM groups
        """
    ).fetchdf()

    examples = con.execute(
        """
        SELECT
            p.PATIENT,
            p.ENCOUNTER,
            MIN(e.START) AS encounter_start,
            MIN(e.ENCOUNTERCLASS) AS encounter_class,
            p.CODE,
            MIN(p.DESCRIPTION) AS description,
            COUNT(*) AS row_count,
            COUNT(DISTINCT CAST(p.START AS DATE)) AS distinct_start_dates,
            MIN(p.START) AS first_procedure_start,
            MAX(p.START) AS latest_procedure_start,
            COUNT(DISTINCT p.REASONCODE) FILTER (WHERE p.REASONCODE IS NOT NULL) AS distinct_reason_codes
        FROM procedures p
        LEFT JOIN encounters e
            ON p.ENCOUNTER = e.Id
        WHERE p.ENCOUNTER IS NOT NULL
        GROUP BY p.PATIENT, p.ENCOUNTER, p.CODE
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, p.PATIENT, encounter_start, p.CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def same_start_code_multiplicity(con, limit: int = 25) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = con.execute(
        """
        WITH groups AS (
            SELECT
                PATIENT,
                START,
                CODE,
                COUNT(*) AS row_count,
                COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters
            FROM procedures
            GROUP BY PATIENT, START, CODE
            HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) AS repeated_patient_start_code_groups,
            COALESCE(SUM(row_count), 0) AS rows_in_groups,
            COALESCE(MAX(row_count), 0) AS max_rows_in_group,
            COALESCE(MAX(distinct_encounters), 0) AS max_distinct_encounters_in_group
        FROM groups
        """
    ).fetchdf()

    examples = con.execute(
        """
        SELECT
            PATIENT,
            START,
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS row_count,
            COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters,
            COUNT(DISTINCT REASONCODE) FILTER (WHERE REASONCODE IS NOT NULL) AS distinct_reason_codes
        FROM procedures
        GROUP BY PATIENT, START, CODE
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, PATIENT, START, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def repeated_code_gap_summary(con, limit: int = 25) -> pd.DataFrame:
    """Describe spacing between repeated rows for the same patient+procedure code.

    This is chronology only. A gap does not imply a treatment course, restart, or
    recurrence of disease.
    """
    return con.execute(
        """
        WITH ordered AS (
            SELECT
                PATIENT,
                CODE,
                DESCRIPTION,
                CAST(START AS DATE) AS start_date,
                LAG(CAST(START AS DATE)) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, ENCOUNTER
                ) AS previous_start_date
            FROM procedures
        ),
        gaps AS (
            SELECT
                PATIENT,
                CODE,
                MIN(DESCRIPTION) AS description,
                COUNT(*) FILTER (WHERE previous_start_date IS NOT NULL) AS repeated_transitions,
                MIN(DATE_DIFF('day', previous_start_date, start_date))
                    FILTER (WHERE previous_start_date IS NOT NULL) AS min_gap_days,
                MEDIAN(DATE_DIFF('day', previous_start_date, start_date))
                    FILTER (WHERE previous_start_date IS NOT NULL) AS median_gap_days,
                MAX(DATE_DIFF('day', previous_start_date, start_date))
                    FILTER (WHERE previous_start_date IS NOT NULL) AS max_gap_days
            FROM ordered
            GROUP BY PATIENT, CODE
            HAVING COUNT(*) FILTER (WHERE previous_start_date IS NOT NULL) > 0
        )
        SELECT *
        FROM gaps
        ORDER BY repeated_transitions DESC, PATIENT, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def reason_consistency_for_patient_code(con, limit: int = 25) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            PATIENT,
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT REASONCODE) FILTER (WHERE REASONCODE IS NOT NULL) AS distinct_reason_codes,
            STRING_AGG(
                DISTINCT COALESCE(CAST(REASONCODE AS VARCHAR), '<null>') || ': ' ||
                    COALESCE(REASONDESCRIPTION, '<null>'),
                ' | ' ORDER BY COALESCE(CAST(REASONCODE AS VARCHAR), '<null>') || ': ' ||
                    COALESCE(REASONDESCRIPTION, '<null>')
            ) AS source_reasons
        FROM procedures
        GROUP BY PATIENT, CODE
        HAVING COUNT(*) > 1
           AND COUNT(DISTINCT REASONCODE) FILTER (WHERE REASONCODE IS NOT NULL) > 1
        ORDER BY distinct_reason_codes DESC, procedure_rows DESC, PATIENT, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def reference_patient_code_summary(con) -> pd.DataFrame:
    cols = procedure_columns(con)
    source_open_expr = (
        "SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS source_open_rows"
        if "STOP" in cols
        else "NULL AS source_open_rows"
    )
    return con.execute(
        f"""
        SELECT
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT CAST(START AS DATE)) AS distinct_start_dates,
            COUNT(DISTINCT ENCOUNTER) FILTER (WHERE ENCOUNTER IS NOT NULL) AS distinct_encounters,
            MIN(START) AS first_start,
            MAX(START) AS latest_start,
            {source_open_expr},
            COUNT(DISTINCT REASONCODE) FILTER (WHERE REASONCODE IS NOT NULL) AS distinct_reason_codes,
            STRING_AGG(
                DISTINCT COALESCE(CAST(REASONCODE AS VARCHAR), '<null>') || ': ' ||
                    COALESCE(REASONDESCRIPTION, '<null>'),
                ' | ' ORDER BY COALESCE(CAST(REASONCODE AS VARCHAR), '<null>') || ': ' ||
                    COALESCE(REASONDESCRIPTION, '<null>')
            ) AS source_reasons
        FROM procedures
        WHERE PATIENT = ?
        GROUP BY CODE
        ORDER BY first_start, CODE
        """,
        [REFERENCE_PATIENT_ID],
    ).fetchdf()


def reference_patient_encounter_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            p.ENCOUNTER,
            MIN(e.START) AS encounter_start,
            MIN(e.ENCOUNTERCLASS) AS encounter_class,
            MIN(e.DESCRIPTION) AS encounter_description,
            COUNT(*) AS procedure_rows,
            COUNT(DISTINCT p.CODE) AS distinct_procedure_codes,
            STRING_AGG(DISTINCT p.DESCRIPTION, ' | ' ORDER BY p.DESCRIPTION) AS procedures
        FROM procedures p
        LEFT JOIN encounters e
            ON p.ENCOUNTER = e.Id
        WHERE p.PATIENT = ?
        GROUP BY p.ENCOUNTER
        ORDER BY encounter_start, p.ENCOUNTER
        """,
        [REFERENCE_PATIENT_ID],
    ).fetchdf()


def reference_patient_raw_chronology(con) -> pd.DataFrame:
    procedures = get_patient_procedures(con, REFERENCE_PATIENT_ID)
    return procedures


def main() -> None:
    pd.set_option("display.max_rows", 300)
    pd.set_option("display.max_columns", 50)
    pd.set_option("display.width", 260)
    pd.set_option("display.max_colwidth", 120)

    con = get_connection()
    register_synthea_tables(con)
    require_procedures_table(con)

    print_section("1. PROCEDURES SOURCE SCHEMA")
    print(procedures_schema(con).to_string(index=False))

    print_section("2. DATASET SUMMARY")
    print(dataset_summary(con).to_string(index=False))

    print_section("3. START/STOP DURATION SUMMARY")
    print(duration_summary(con).to_string(index=False))

    print_section("4. MOST COMMON PROCEDURE CODES")
    print(most_common_procedure_codes(con).to_string(index=False))

    print_section("5. REPEATED PATIENT + PROCEDURE CODE SUMMARY")
    print(repeated_patient_code_summary(con).to_string(index=False))
    print("\nMost repeated patient+code combinations:")
    print(most_repeated_patient_codes(con).to_string(index=False))

    print_section("6. EXACT DUPLICATE CANDIDATES")
    duplicate_summary, duplicate_examples = exact_duplicate_candidates(con)
    print(duplicate_summary.to_string(index=False))
    if duplicate_examples.empty:
        print("\nNo exact duplicate groups found.")
    else:
        print("\nExamples:")
        print(duplicate_examples.to_string(index=False))

    print_section("7. CODE / DESCRIPTION CONSISTENCY")
    mapping_summary, mapping_examples = code_description_consistency(con)
    print(mapping_summary.to_string(index=False))
    if mapping_examples.empty:
        print("\nNo procedure codes map to multiple descriptions.")
    else:
        print("\nCodes with multiple descriptions:")
        print(mapping_examples.to_string(index=False))

    print_section("8. ENCOUNTER LINKAGE")
    print(encounter_linkage_summary(con).to_string(index=False))

    print_section("9. PROCEDURES PER ENCOUNTER")
    print(procedures_per_encounter_summary(con).to_string(index=False))
    print("\nBusiest encounters with procedures:")
    print(busiest_procedure_encounters(con).to_string(index=False))

    print_section("10. REPEATED SAME PATIENT + ENCOUNTER + CODE")
    encounter_code_summary, encounter_code_examples = same_encounter_code_multiplicity(con)
    print(encounter_code_summary.to_string(index=False))
    if encounter_code_examples.empty:
        print("\nNo repeated same-code procedure rows within an encounter.")
    else:
        print("\nExamples:")
        print(encounter_code_examples.to_string(index=False))

    print_section("11. REPEATED SAME PATIENT + START + CODE")
    start_code_summary, start_code_examples = same_start_code_multiplicity(con)
    print(start_code_summary.to_string(index=False))
    if start_code_examples.empty:
        print("\nNo repeated same patient+start+code groups.")
    else:
        print("\nExamples:")
        print(start_code_examples.to_string(index=False))

    print_section("12. SPACING OF MOST-REPEATED PATIENT + CODE HISTORIES")
    print(repeated_code_gap_summary(con).to_string(index=False))

    print_section("13. REPEATED PROCEDURE CODES WITH MULTIPLE SOURCE REASONS")
    reason_variation = reason_consistency_for_patient_code(con)
    if reason_variation.empty:
        print("No repeated patient+code histories with multiple non-null source reason codes.")
    else:
        print(reason_variation.to_string(index=False))

    print_section("14. REFERENCE PATIENT PROCEDURE CODE SUMMARY")
    print(f"Reference patient: {REFERENCE_PATIENT_ID}")
    reference_summary = reference_patient_code_summary(con)
    if reference_summary.empty:
        print("No procedures found for the reference patient.")
    else:
        print(reference_summary.to_string(index=False))

    print_section("15. REFERENCE PATIENT PROCEDURE ENCOUNTER SUMMARY")
    reference_encounters = reference_patient_encounter_summary(con)
    if reference_encounters.empty:
        print("No procedure-linked encounters found for the reference patient.")
    else:
        print(reference_encounters.to_string(index=False))

    print_section("16. REFERENCE PATIENT RAW PROCEDURE CHRONOLOGY")
    reference_raw = reference_patient_raw_chronology(con)
    if reference_raw.empty:
        print("No procedures found for the reference patient.")
    else:
        print(reference_raw.to_string(index=False))


if __name__ == "__main__":
    main()
