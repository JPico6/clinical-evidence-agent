from clinical_evidence_agent.database import (
    get_connection,
    register_synthea_tables,
    build_utilization_evidence,
)


def test_utilization_evidence_multi_class_change():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "bca1691f-8839-1d66-ed01-471134d55738"

    evidence = build_utilization_evidence(
        con,
        patient_id,
    )

    assert evidence["status"] == "ok"
    assert evidence["anchor_date"] == "2026-08-12"

    assert evidence["prior_period"]["total_encounters"] == 74
    assert evidence["recent_period"]["total_encounters"] == 68
    assert evidence["total_change"]["absolute"] == -6

    classes = {
        item["encounter_class"]: item
        for item in evidence["by_encounter_class"]
    }

    assert classes["ambulatory"]["prior_count"] == 49
    assert classes["ambulatory"]["recent_count"] == 38
    assert classes["ambulatory"]["absolute_change"] == -11

    assert classes["emergency"]["prior_count"] == 0
    assert classes["emergency"]["recent_count"] == 10
    assert classes["emergency"]["absolute_change"] == 10

    assert classes["urgentcare"]["absolute_change"] == 0

    con.close()

def test_utilization_evidence_with_no_prior_utilization():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "6c4283c9-228b-2774-7d25-fbb5a14bdc1b"

    evidence = build_utilization_evidence(
        con,
        patient_id,
    )

    assert evidence["status"] == "ok"
    assert evidence["evidence_sufficiency"] == "no_prior_utilization"

    assert evidence["prior_period"]["total_encounters"] == 0
    assert evidence["recent_period"]["total_encounters"] == 1
    assert evidence["total_change"]["absolute"] == 1

    assert evidence["by_encounter_class"] == [
        {
            "encounter_class": "wellness",
            "prior_count": 0,
            "recent_count": 1,
            "absolute_change": 1,
        }
    ]

    con.close()

def test_utilization_evidence_sparse_comparison():
    con = get_connection()
    register_synthea_tables(con)

    patient_id = "65cbad6a-eb9d-420e-9bab-b4f9c6aab7db"

    evidence = build_utilization_evidence(
        con,
        patient_id,
    )

    assert evidence["status"] == "ok"
    assert evidence["evidence_sufficiency"] == "sparse_comparison"

    assert evidence["prior_period"]["total_encounters"] == 1
    assert evidence["recent_period"]["total_encounters"] == 1
    assert evidence["total_change"]["absolute"] == 0

    assert evidence["by_encounter_class"] == [
        {
            "encounter_class": "wellness",
            "prior_count": 1,
            "recent_count": 1,
            "absolute_change": 0,
        }
    ]

    con.close()