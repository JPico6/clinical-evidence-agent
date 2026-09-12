from clinical_evidence_agent.database import (
    get_connection,
    register_synthea_tables,
    build_lab_evidence,
)


def test_single_point_lab_comparison():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "a45aa142-d1e9-d944-f2c7-05015c90762d"

    evidence = build_lab_evidence(
        con,
        patient_id,
        "33914-3",
    )

    assert evidence["status"] == "ok"
    assert evidence["evidence_sufficiency"] == "single_point_comparison"

    assert evidence["prior_period"]["statistics"]["measurement_count"] == 1
    assert evidence["recent_period"]["statistics"]["measurement_count"] == 1

    assert evidence["prior_period"]["statistics"]["iqr"] is None
    assert evidence["recent_period"]["statistics"]["iqr"] is None

    assert evidence["change"]["median_absolute"] == -13.8
    assert evidence["change"]["median_percent"] == -15.99
    assert evidence["change"]["iqr_change"] is None

    con.close()

def test_lab_with_historical_but_no_recent_data():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "239b0c86-371a-3080-fcd9-8379b296bc9a"

    evidence = build_lab_evidence(
        con,
        patient_id,
        "33914-3",
    )

    assert evidence["status"] == "ok"
    assert evidence["evidence_sufficiency"] == "no_recent_data"

    assert evidence["prior_period"]["statistics"] is None
    assert evidence["recent_period"]["statistics"] is None

    assert evidence["change"]["median_absolute"] is None
    assert evidence["change"]["median_percent"] is None
    assert evidence["change"]["iqr_change"] is None

    con.close()


def test_lab_with_multiple_units_requires_explicit_unit():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "bca1691f-8839-1d66-ed01-471134d55738"

    evidence = build_lab_evidence(
        con,
        patient_id,
        "33914-3",
    )

    assert evidence["status"] == "multiple_units"

    units = evidence["available_units"]

    assert len(units) == 2

    unit_names = {item["unit"] for item in units}

    assert "mL/min/{1.73_m2}" in unit_names
    assert "mL/min" in unit_names

    con.close()


def test_multi_point_lab_comparison_with_explicit_unit():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "bca1691f-8839-1d66-ed01-471134d55738"

    evidence = build_lab_evidence(
        con,
        patient_id,
        "33914-3",
        unit="mL/min/{1.73_m2}",
    )

    assert evidence["status"] == "ok"
    assert evidence["unit"] == "mL/min/{1.73_m2}"
    assert evidence["evidence_sufficiency"] == "multi_point_comparison"

    assert evidence["prior_period"]["statistics"]["measurement_count"] >= 2
    assert evidence["recent_period"]["statistics"]["measurement_count"] >= 2

    assert evidence["prior_period"]["statistics"]["iqr"] is not None
    assert evidence["recent_period"]["statistics"]["iqr"] is not None
    assert evidence["change"]["iqr_change"] is not None

    assert evidence["change"]["median_absolute"] is not None
    assert evidence["change"]["median_percent"] is not None

    con.close()

def test_lab_with_no_data():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "bca1691f-8839-1d66-ed01-471134d55738"

    evidence = build_lab_evidence(
        con,
        patient_id,
        "NONEXISTENT_LAB_CODE",
    )

    assert evidence == {
        "status": "no_data",
        "patient_id": patient_id,
        "code": "NONEXISTENT_LAB_CODE",
    }

    con.close()