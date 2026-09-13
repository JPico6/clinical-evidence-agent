"""Focused diagnostics for unresolved Synthea medication interval edge cases.

This script is exploratory only. It inspects the small number of overlapping
same-patient/same-code intervals and same-start multiplicity groups discovered
by medication_diagnostics.py. It does not define production medication-course
semantics.

Run from the repository root with:
    uv run python scripts/medication_edge_case_diagnostics.py
"""

from __future__ import annotations

import pandas as pd

from clinical_evidence_agent.database import get_connection, register_synthea_tables


REFERENCE_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def print_section(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def require_medications_table(con) -> None:
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    if "medications" not in tables:
        raise RuntimeError(
            "The medications view is not registered. Expected local Synthea data at "
            "data/synthea/medications.csv."
        )


def medication_schema(con) -> pd.DataFrame:
    return con.execute("DESCRIBE medications").fetchdf()


def overlapping_adjacent_pairs(con) -> pd.DataFrame:
    """Return all adjacent same-patient/code pairs where previous STOP > current START.

    Full source fields for both rows are retained. The diagnostic intentionally
    describes interval geometry only; it does not infer duplicate prescriptions,
    adherence, replacement, or clinical activity.
    """
    return con.execute(
        """
        WITH ordered AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS sequence_number,
                LAG(START) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS previous_start,
                LAG(STOP) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS previous_stop,
                LAG(ENCOUNTER) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS previous_encounter
            FROM medications
        ),
        overlap_keys AS (
            SELECT
                PATIENT,
                CODE,
                sequence_number,
                previous_start,
                previous_stop,
                previous_encounter,
                START AS current_start,
                STOP AS current_stop,
                ENCOUNTER AS current_encounter
            FROM ordered
            WHERE previous_stop IS NOT NULL
              AND previous_stop > START
        ),
        previous_rows AS (
            SELECT m.*, k.sequence_number
            FROM overlap_keys k
            JOIN medications m
              ON m.PATIENT = k.PATIENT
             AND m.CODE = k.CODE
             AND m.START = k.previous_start
             AND m.STOP IS NOT DISTINCT FROM k.previous_stop
             AND m.ENCOUNTER IS NOT DISTINCT FROM k.previous_encounter
        ),
        current_rows AS (
            SELECT m.*, k.sequence_number
            FROM overlap_keys k
            JOIN medications m
              ON m.PATIENT = k.PATIENT
             AND m.CODE = k.CODE
             AND m.START = k.current_start
             AND m.STOP IS NOT DISTINCT FROM k.current_stop
             AND m.ENCOUNTER IS NOT DISTINCT FROM k.current_encounter
        )
        SELECT
            k.PATIENT,
            k.CODE,
            k.sequence_number,
            k.previous_start,
            k.previous_stop,
            k.current_start,
            k.current_stop,
            DATE_DIFF('day', k.previous_start, k.previous_stop) AS previous_duration_days,
            DATE_DIFF('day', k.current_start, k.current_stop) AS current_duration_days,
            CASE
                WHEN k.current_stop IS NOT NULL
                 AND k.previous_start <= k.current_start
                 AND k.previous_stop >= k.current_stop
                THEN TRUE ELSE FALSE
            END AS current_fully_contained_in_previous,
            CASE
                WHEN p.ENCOUNTER IS NOT DISTINCT FROM c.ENCOUNTER THEN TRUE ELSE FALSE
            END AS same_encounter,
            p.ENCOUNTER AS previous_ENCOUNTER,
            c.ENCOUNTER AS current_ENCOUNTER,
            p.PAYER AS previous_PAYER,
            c.PAYER AS current_PAYER,
            p.DESCRIPTION AS previous_DESCRIPTION,
            c.DESCRIPTION AS current_DESCRIPTION,
            p.BASE_COST AS previous_BASE_COST,
            c.BASE_COST AS current_BASE_COST,
            p.PAYER_COVERAGE AS previous_PAYER_COVERAGE,
            c.PAYER_COVERAGE AS current_PAYER_COVERAGE,
            p.DISPENSES AS previous_DISPENSES,
            c.DISPENSES AS current_DISPENSES,
            p.TOTALCOST AS previous_TOTALCOST,
            c.TOTALCOST AS current_TOTALCOST,
            p.REASONCODE AS previous_REASONCODE,
            c.REASONCODE AS current_REASONCODE,
            p.REASONDESCRIPTION AS previous_REASONDESCRIPTION,
            c.REASONDESCRIPTION AS current_REASONDESCRIPTION
        FROM overlap_keys k
        JOIN previous_rows p
          ON p.PATIENT = k.PATIENT
         AND p.CODE = k.CODE
         AND p.sequence_number = k.sequence_number
        JOIN current_rows c
          ON c.PATIENT = k.PATIENT
         AND c.CODE = k.CODE
         AND c.sequence_number = k.sequence_number
        ORDER BY k.PATIENT, k.CODE, k.current_start
        """
    ).fetchdf()


def overlap_pattern_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH ordered AS (
            SELECT
                PATIENT,
                CODE,
                START,
                STOP,
                ENCOUNTER,
                LAG(START) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS previous_start,
                LAG(STOP) OVER (
                    PARTITION BY PATIENT, CODE
                    ORDER BY START, STOP NULLS LAST, DESCRIPTION, ENCOUNTER
                ) AS previous_stop
            FROM medications
        ),
        overlap_rows AS (
            SELECT *,
                DATE_DIFF('day', previous_start, previous_stop) AS previous_duration_days,
                DATE_DIFF('day', START, STOP) AS current_duration_days,
                CASE
                    WHEN STOP IS NOT NULL
                     AND previous_start <= START
                     AND previous_stop >= STOP
                    THEN TRUE ELSE FALSE
                END AS fully_contained
            FROM ordered
            WHERE previous_stop IS NOT NULL
              AND previous_stop > START
        )
        SELECT
            COUNT(*) AS overlap_pairs,
            COUNT(DISTINCT PATIENT) AS patients,
            COUNT(DISTINCT CODE) AS codes,
            SUM(CASE WHEN fully_contained THEN 1 ELSE 0 END) AS fully_contained_pairs,
            MIN(previous_duration_days) AS min_previous_duration_days,
            MEDIAN(previous_duration_days) AS median_previous_duration_days,
            MAX(previous_duration_days) AS max_previous_duration_days,
            MIN(current_duration_days) AS min_current_duration_days,
            MEDIAN(current_duration_days) AS median_current_duration_days,
            MAX(current_duration_days) AS max_current_duration_days
        FROM overlap_rows
        """
    ).fetchdf()


def same_start_groups(con) -> pd.DataFrame:
    """Return every source row in patient+code+START groups containing >1 row."""
    return con.execute(
        """
        WITH duplicated_starts AS (
            SELECT PATIENT, CODE, START
            FROM medications
            GROUP BY PATIENT, CODE, START
            HAVING COUNT(*) > 1
        )
        SELECT
            m.*,
            DATE_DIFF('day', m.START, m.STOP) AS duration_days
        FROM medications m
        JOIN duplicated_starts d
          ON m.PATIENT = d.PATIENT
         AND m.CODE = d.CODE
         AND m.START = d.START
        ORDER BY m.PATIENT, m.CODE, m.START, m.STOP NULLS LAST, m.ENCOUNTER
        """
    ).fetchdf()


def same_start_group_summary(con) -> pd.DataFrame:
    return con.execute(
        """
        WITH grouped AS (
            SELECT
                PATIENT,
                CODE,
                START,
                COUNT(*) AS row_count,
                COUNT(DISTINCT STOP) AS distinct_nonnull_stops,
                SUM(CASE WHEN STOP IS NULL THEN 1 ELSE 0 END) AS null_stop_rows,
                COUNT(DISTINCT ENCOUNTER) AS distinct_nonnull_encounters,
                COUNT(DISTINCT PAYER) AS distinct_nonnull_payers,
                COUNT(DISTINCT DESCRIPTION) AS distinct_descriptions,
                COUNT(DISTINCT DISPENSES) AS distinct_nonnull_dispenses,
                COUNT(DISTINCT REASONCODE) AS distinct_nonnull_reasoncodes,
                COUNT(DISTINCT BASE_COST) AS distinct_nonnull_base_costs,
                COUNT(DISTINCT PAYER_COVERAGE) AS distinct_nonnull_payer_coverages,
                COUNT(DISTINCT TOTALCOST) AS distinct_nonnull_total_costs
            FROM medications
            GROUP BY PATIENT, CODE, START
            HAVING COUNT(*) > 1
        )
        SELECT *
        FROM grouped
        ORDER BY PATIENT, CODE, START
        """
    ).fetchdf()


def reference_patient_simvastatin(con) -> pd.DataFrame:
    return con.execute(
        """
        SELECT
            *,
            DATE_DIFF('day', START, STOP) AS duration_days
        FROM medications
        WHERE PATIENT = ?
          AND CODE = 314231
        ORDER BY START, STOP NULLS LAST, ENCOUNTER
        """,
        [REFERENCE_PATIENT_ID],
    ).fetchdf()


def main() -> None:
    con = get_connection()
    register_synthea_tables(con)
    require_medications_table(con)

    print_section("1. MEDICATIONS SOURCE SCHEMA")
    print(medication_schema(con).to_string(index=False))

    print_section("2. OVERLAP PATTERN SUMMARY")
    print(overlap_pattern_summary(con).to_string(index=False))

    print_section("3. ALL OVERLAPPING ADJACENT SAME-PATIENT/CODE PAIRS")
    overlaps = overlapping_adjacent_pairs(con)
    print(f"rows={len(overlaps)}")
    print(overlaps.to_string(index=False))

    print_section("4. SAME PATIENT + CODE + START GROUP SUMMARY")
    same_start_summary = same_start_group_summary(con)
    print(f"groups={len(same_start_summary)}")
    print(same_start_summary.to_string(index=False))

    print_section("5. ALL SOURCE ROWS IN SAME-START GROUPS")
    same_start = same_start_groups(con)
    print(f"rows={len(same_start)}")
    print(same_start.to_string(index=False))

    print_section(
        f"6. REFERENCE PATIENT SIMVASTATIN 10 MG (CODE 314231): {REFERENCE_PATIENT_ID}"
    )
    print(reference_patient_simvastatin(con).to_string(index=False))


if __name__ == "__main__":
    main()
