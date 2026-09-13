from clinical_evidence_agent.database import (
    get_connection,
    register_synthea_tables,
    build_condition_evidence,
)

RICH_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"

def test_condition_evidence_rich_patient():
    con = get_connection()
    register_synthea_tables(con)

    evidence = build_condition_evidence(
        con,
        RICH_PATIENT_ID,
    )

    assert evidence["status"] == "ok"
    assert evidence["anchor_date"] == "2026-08-12"
    assert evidence["condition_count"] == 53
    assert evidence["newly_observed_condition_count"] == 2

    new_conditions = {
        item["code"]: item
        for item in evidence["newly_observed_conditions"]
    }

    assert new_conditions["278558000"] == {
        "code": "278558000",
        "description": "Dental filling lost (finding)",
        "first_start": "2025-12-03",
        "episode_count": 1,
    }

    assert new_conditions["49436004"] == {
        "code": "49436004",
        "description": "Atrial fibrillation (disorder)",
        "first_start": "2026-05-04",
        "episode_count": 1,
    }


def test_condition_evidence_preserves_episode_summary():
    con = get_connection()
    register_synthea_tables(con)

    evidence = build_condition_evidence(
        con,
        RICH_PATIENT_ID,
    )

    conditions = {
        item["code"]: item
        for item in evidence["conditions"]
    }

    social_isolation = conditions["422650009"]

    assert social_isolation["episode_count"] == 15
    assert social_isolation["first_start"] == "2013-07-24"
    assert social_isolation["latest_start"] == "2026-06-24"
    assert social_isolation["latest_stop"] == "2026-04-29"
    assert social_isolation["source_open_episode_count"] == 1

