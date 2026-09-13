"""Create the small synthetic dataset used by the public portfolio demo.

Run from the repository root while the full local Synthea export is still
available in data/synthea:

    uv run python scripts/build_public_demo_data.py

The output is written to data/public_demo and contains only the curated
synthetic patients used in the frozen multi-patient evaluation cohort.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "synthea"
OUTPUT = ROOT / "data" / "public_demo"

PATIENT_IDS = ['bca1691f-8839-1d66-ed01-471134d55738', 'ee4b7339-ca58-b6af-c199-04b6d5761c73', '57efda89-b582-bb08-8a2d-e06b2c184bfc', '3314e296-2326-2826-271d-a7be5b896db9', '5693c080-f485-91e7-54b9-ad9a8c12af62', '355a4d50-2628-aa65-c336-deacf4d606fb', '0b786670-17af-32e1-b2d2-f77c33874b30', '2211f478-b7b4-7711-16cf-84ffb52b9d2b', '7af6b271-f16d-21e1-882a-7bff71005a7b', '716c6d0a-2a5d-0aaa-9ced-312ed6a943da']

TABLE_PATIENT_COLUMN = {
    "patients": "Id",
    "encounters": "PATIENT",
    "conditions": "PATIENT",
    "medications": "PATIENT",
    "observations": "PATIENT",
    "procedures": "PATIENT",
    # Claims are not required by the current evidence path, but include them
    # when the common Synthea PATIENTID/PATIENT field is available.
    "claims": None,
}

REQUIRED_TABLES = {
    "patients",
    "encounters",
    "conditions",
    "medications",
    "observations",
    "procedures",
}


def patient_column(table: str, fieldnames: list[str]) -> str | None:
    configured = TABLE_PATIENT_COLUMN[table]
    if configured:
        return configured
    for candidate in ("PATIENTID", "PATIENT"):
        if candidate in fieldnames:
            return candidate
    return None


def subset_table(table: str) -> int:
    source = SOURCE / f"{table}.csv"
    target = OUTPUT / f"{table}.csv"

    if not source.exists():
        if table in REQUIRED_TABLES:
            raise FileNotFoundError(f"Missing required Synthea table: {source}")
        return 0

    with source.open("r", encoding="utf-8-sig", newline="") as src:
        reader = csv.DictReader(src)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {source}")

        column = patient_column(table, reader.fieldnames)
        if column is None:
            # Optional table with an unfamiliar schema: skip it rather than
            # accidentally publishing unrelated rows.
            return 0

        OUTPUT.mkdir(parents=True, exist_ok=True)
        count = 0
        with target.open("w", encoding="utf-8", newline="") as dst:
            writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                if row.get(column) in PATIENT_IDS:
                    writer.writerow(row)
                    count += 1
        return count


def main() -> None:
    print(f"Source: {SOURCE}")
    print(f"Output: {OUTPUT}")
    total = 0
    for table in TABLE_PATIENT_COLUMN:
        count = subset_table(table)
        if count:
            print(f"{table}: {count} rows")
            total += count
    print(f"Done: {total} rows across the public synthetic demo dataset.")


if __name__ == "__main__":
    main()
