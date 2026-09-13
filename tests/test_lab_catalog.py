from clinical_evidence_agent.database import (
    get_connection,
    get_patient_numeric_lab_catalog,
    register_synthea_tables,
)


RICH_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"


def test_lab_catalog_exposes_grounded_numeric_lab_metadata():
    con = get_connection()
    register_synthea_tables(con)
    catalog = get_patient_numeric_lab_catalog(con, RICH_PATIENT_ID)

    assert catalog["status"] == "ok"
    assert catalog["anchor_date"] == "2026-08-12"
    assert catalog["lookback_days"] == 365
    assert catalog["lab_count"] == len(catalog["labs"])
    assert catalog["lab_count"] > 0

    for lab in catalog["labs"]:
        assert lab["code"]
        assert lab["description"]
        assert lab["measurement_count"] >= lab["recent_measurement_count"] >= 0
        assert lab["first_date"] <= lab["last_date"]
        assert lab["available_units"]
        assert "value" not in lab
        assert "latest_value" not in lab

    con.close()


def test_lab_catalog_preserves_multiple_units_for_egfr():
    con = get_connection()
    register_synthea_tables(con)
    catalog = get_patient_numeric_lab_catalog(con, RICH_PATIENT_ID)
    egfr = next(lab for lab in catalog["labs"] if lab["code"] == "33914-3")

    assert egfr["multiple_units"] is True
    assert {item["unit"] for item in egfr["available_units"]} == {
        "mL/min",
        "mL/min/{1.73_m2}",
    }
    con.close()


def test_lab_catalog_is_ranked_by_recent_then_lifetime_frequency():
    con = get_connection()
    register_synthea_tables(con)
    catalog = get_patient_numeric_lab_catalog(con, RICH_PATIENT_ID)
    ranking = [
        (lab["recent_measurement_count"], lab["measurement_count"])
        for lab in catalog["labs"]
    ]

    assert ranking == sorted(ranking, reverse=True)
    con.close()


def test_lab_catalog_uses_code_identity_despite_description_variants():
    con = get_connection()
    register_synthea_tables(con)
    catalog = get_patient_numeric_lab_catalog(con, RICH_PATIENT_ID)

    bun_entries = [lab for lab in catalog["labs"] if lab["code"] == "6299-2"]
    assert len(bun_entries) == 1
    assert bun_entries[0]["measurement_count"] == 164
    assert len(bun_entries[0]["source_descriptions"]) == 2

    con.close()
