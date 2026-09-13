"""Exploratory diagnostics for Synthea medication records.

This script is intentionally NOT part of the production evidence API. Its purpose is
only to inspect medication source semantics before we design medication evidence.

Run from the repository root with:
    uv run python scripts/medication_diagnostics.py
"""

from __future__ import annotations

import pandas as pd

from clinical_evidence_agent.database import get_connection, get_patient_medications, register_synthea_tables


REFERENCE_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def print_section(title: str) -> None:
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)


def require_medications_table(con) -> None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if "medications" not in tables:
        raise RuntimeError(
            "The medications view is not registered. Expected local Synthea data at "
            "data/synthea/medications.csv."
        )


def dataset_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            COUNT(*) AS medication_rows,
            COUNT(DISTINCT PATIENT) AS patients_with_medications,
            COUNT(DISTINCT CODE) AS distinct_codes,
            COUNT(DISTINCT DESCRIPTION) AS distinct_descriptions,
            SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS missing_stop_rows,
            ROUND(100.0 * SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2)
                AS missing_stop_pct,
            SUM(CASE WHEN DISPENSES IS NULL THEN 1 ELSE 0 END) AS missing_dispenses_rows,
            SUM(CASE WHEN REASONCODE IS NOT NULL THEN 1 ELSE 0 END) AS reasoncode_present_rows,
            ROUND(100.0 * SUM(CASE WHEN REASONCODE IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2)
                AS reasoncode_present_pct,
            SUM(CASE WHEN REASONDESCRIPTION IS NOT NULL THEN 1 ELSE 0 END) AS reasondescription_present_rows,
            ROUND(100.0 * SUM(CASE WHEN REASONDESCRIPTION IS NOT NULL THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2)
                AS reasondescription_present_pct
        FROM medications
        """
    ).fetchdf()


def dispenses_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            COUNT(*) AS nonnull_rows,
            MIN(DISPENSES) AS min_dispenses,
            QUANTILE_CONT(DISPENSES, 0.25) AS q1_dispenses,
            MEDIAN(DISPENSES) AS median_dispenses,
            QUANTILE_CONT(DISPENSES, 0.75) AS q3_dispenses,
            MAX(DISPENSES) AS max_dispenses,
            AVG(DISPENSES) AS mean_dispenses
        FROM medications
        WHERE DISPENSES IS NOT NULL
        """
    ).fetchdf()


def repeated_patient_code_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH patient_code AS (
            SELECT
                PATIENT,
                CODE,
                MIN(DESCRIPTION) AS example_description,
                COUNT(*) AS episode_rows,
                COUNT(DISTINCT START) AS distinct_start_dates,
                COUNT(DISTINCT STOP) FILTER (WHERE STOP IS NOT NULL) AS distinct_nonnull_stop_dates
            FROM medications
            GROUP BY PATIENT, CODE
        )
        SELECT
            COUNT(*) AS patient_code_pairs,
            SUM(CASE WHEN episode_rows > 1 THEN 1 ELSE 0 END) AS repeated_patient_code_pairs,
            ROUND(
                100.0 * SUM(CASE WHEN episode_rows > 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0),
                2
            ) AS repeated_patient_code_pct,
            MAX(episode_rows) AS max_rows_for_one_patient_code
        FROM patient_code
        """
    ).fetchdf()


def most_repeated_patient_codes(con, limit: int = 20) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            PATIENT,
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS episode_rows,
            MIN(START) AS first_start,
            MAX(START) AS latest_start,
            SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS source_open_rows
        FROM medications
        GROUP BY PATIENT, CODE
        HAVING COUNT(*) > 1
        ORDER BY episode_rows DESC, PATIENT, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()


def exact_duplicate_candidates(con, limit: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = con.execute(
        """
        WITH duplicate_groups AS (
            SELECT
                PATIENT,
                START,
                STOP,
                CODE,
                DESCRIPTION,
                DISPENSES,
                REASONCODE,
                REASONDESCRIPTION,
                COUNT(*) AS row_count
            FROM medications
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
        """
        SELECT
            PATIENT,
            START,
            STOP,
            CODE,
            DESCRIPTION,
            DISPENSES,
            REASONCODE,
            REASONDESCRIPTION,
            COUNT(*) AS row_count
        FROM medications
        GROUP BY ALL
        HAVING COUNT(*) > 1
        ORDER BY row_count DESC, PATIENT, START, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def code_description_consistency(con, limit: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = con.execute(
        """
        WITH code_map AS (
            SELECT CODE, COUNT(DISTINCT DESCRIPTION) AS description_count
            FROM medications
            GROUP BY CODE
        ),
        description_map AS (
            SELECT DESCRIPTION, COUNT(DISTINCT CODE) AS code_count
            FROM medications
            GROUP BY DESCRIPTION
        )
        SELECT
            (SELECT COUNT(*) FROM code_map WHERE description_count > 1) AS codes_with_multiple_descriptions,
            (SELECT MAX(description_count) FROM code_map) AS max_descriptions_per_code,
            (SELECT COUNT(*) FROM description_map WHERE code_count > 1) AS descriptions_with_multiple_codes,
            (SELECT MAX(code_count) FROM description_map) AS max_codes_per_description
        """
    ).fetchdf()

    examples = con.execute(
        """
        SELECT
            CODE,
            COUNT(DISTINCT DESCRIPTION) AS description_count,
            STRING_AGG(DISTINCT DESCRIPTION, ' | ' ORDER BY DESCRIPTION) AS descriptions
        FROM medications
        GROUP BY CODE
        HAVING COUNT(DISTINCT DESCRIPTION) > 1
        ORDER BY description_count DESC, CODE
        LIMIT ?
        """,
        [limit],
    ).fetchdf()
    return summary, examples


def episode_relationship_summary(con) -> pd.DataFrame:
    """Classify adjacent rows for the same patient+code without assigning clinical meaning.

    Important: a previous missing STOP is reported separately. We do NOT infer that the
    earlier prescription/exposure remained clinically active through the next START.
    """
    return con.execute(
        """
        WITH ordered AS (
            SELECT
                PATIENT,
                CODE,
                DESCRIPTION,
                START,
                STOP,
                LAG(START) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION
                ) AS previous_start,
                LAG(STOP) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION
                ) AS previous_stop
            FROM medications
        ),
        relationships AS (
            SELECT *,
                CASE
                    WHEN previous_start IS NULL THEN 'first_record'
                    WHEN previous_stop IS NULL THEN 'previous_stop_missing'
                    WHEN previous_stop < START THEN 'gap_after_previous_stop'
                    WHEN previous_stop = START THEN 'boundary_touch'
                    WHEN previous_stop > START THEN 'overlap_with_previous'
                    ELSE 'unclassified'
                END AS relationship
            FROM ordered
        )
        SELECT
            relationship,
            COUNT(*) AS row_count
        FROM relationships
        GROUP BY relationship
        ORDER BY row_count DESC, relationship
        """
    ).fetchdf()


def episode_relationship_examples(con, relationship: str, limit: int = 20) -> pd.DataFrame:
    return con.execute(
        """
        WITH ordered AS (
            SELECT
                PATIENT,
                CODE,
                DESCRIPTION,
                START,
                STOP,
                LAG(START) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION
                ) AS previous_start,
                LAG(STOP) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION
                ) AS previous_stop
            FROM medications
        ),
        relationships AS (
            SELECT *,
                CASE
                    WHEN previous_start IS NULL THEN 'first_record'
                    WHEN previous_stop IS NULL THEN 'previous_stop_missing'
                    WHEN previous_stop < START THEN 'gap_after_previous_stop'
                    WHEN previous_stop = START THEN 'boundary_touch'
                    WHEN previous_stop > START THEN 'overlap_with_previous'
                    ELSE 'unclassified'
                END AS relationship
            FROM ordered
        )
        SELECT
            PATIENT,
            CODE,
            DESCRIPTION,
            previous_start,
            previous_stop,
            START AS current_start,
            STOP AS current_stop,
            relationship
        FROM relationships
        WHERE relationship = ?
        ORDER BY PATIENT, CODE, current_start
        LIMIT ?
        """,
        [relationship, limit],
    ).fetchdf()


def same_start_same_code_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH grouped AS (
            SELECT
                PATIENT,
                CODE,
                START,
                COUNT(*) AS row_count,
                COUNT(DISTINCT STOP) AS distinct_nonnull_stops,
                COUNT(DISTINCT DISPENSES) AS distinct_nonnull_dispenses,
                COUNT(DISTINCT REASONCODE) AS distinct_nonnull_reasoncodes
            FROM medications
            GROUP BY PATIENT, CODE, START
            HAVING COUNT(*) > 1
        )
        SELECT
            COUNT(*) AS patient_code_start_groups,
            COALESCE(SUM(row_count), 0) AS rows_in_groups,
            COALESCE(MAX(row_count), 0) AS largest_group
        FROM grouped
        """
    ).fetchdf()


def reference_patient_code_summary(con, patient_id: str) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            CODE,
            MIN(DESCRIPTION) AS description,
            COUNT(*) AS row_count,
            MIN(START) AS first_start,
            MAX(START) AS latest_start,
            MAX(STOP) AS latest_nonnull_stop,
            SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS source_open_rows,
            MIN(DISPENSES) AS min_dispenses,
            MAX(DISPENSES) AS max_dispenses,
            COUNT(DISTINCT REASONCODE) AS distinct_nonnull_reasons
        FROM medications
        WHERE PATIENT = ?
        GROUP BY CODE
        ORDER BY first_start, description, CODE
        """,
        [patient_id],
    ).fetchdf()


def main() -> None:
    con = get_connection()
    register_synthea_tables(con)
    require_medications_table(con)

    print_section("1. DATASET-LEVEL MEDICATION SUMMARY")
    print(dataset_summary(con).to_string(index=False))

    print_section("2. DISPENSES DISTRIBUTION")
    print(dispenses_summary(con).to_string(index=False))

    print_section("3. REPEATED PATIENT + MEDICATION CODE")
    print(repeated_patient_code_summary(con).to_string(index=False))
    print("\nMost repeated patient/code combinations:")
    print(most_repeated_patient_codes(con).to_string(index=False))

    print_section("4. EXACT DUPLICATE CANDIDATES")
    duplicate_summary, duplicate_examples = exact_duplicate_candidates(con)
    print(duplicate_summary.to_string(index=False))
    if not duplicate_examples.empty:
        print("\nExamples:")
        print(duplicate_examples.to_string(index=False))

    print_section("5. CODE / DESCRIPTION CONSISTENCY")
    mapping_summary, mapping_examples = code_description_consistency(con)
    print(mapping_summary.to_string(index=False))
    if not mapping_examples.empty:
        print("\nCodes with multiple descriptions:")
        print(mapping_examples.to_string(index=False))

    print_section("6. ADJACENT EPISODE RELATIONSHIPS FOR SAME PATIENT + CODE")
    relationships = episode_relationship_summary(con)
    print(relationships.to_string(index=False))
    for relationship in [
        "overlap_with_previous",
        "boundary_touch",
        "gap_after_previous_stop",
        "previous_stop_missing",
    ]:
        examples = episode_relationship_examples(con, relationship)
        if not examples.empty:
            print(f"\nExamples: {relationship}")
            print(examples.to_string(index=False))

    print_section("7. SAME PATIENT + CODE + START DATE MULTIPLICITY")
    print(same_start_same_code_summary(con).to_string(index=False))

    print_section(f"8. REFERENCE PATIENT CODE SUMMARY: {REFERENCE_PATIENT_ID}")
    patient_summary = reference_patient_code_summary(con, REFERENCE_PATIENT_ID)
    print(patient_summary.to_string(index=False))

    print_section(f"9. REFERENCE PATIENT RAW MEDICATION CHRONOLOGY: {REFERENCE_PATIENT_ID}")
    patient_history = get_patient_medications(con, REFERENCE_PATIENT_ID)
    print(f"rows={len(patient_history)}")
    print(patient_history.to_string(index=False))


if __name__ == "__main__":
    main()
