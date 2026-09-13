import pytest

from clinical_evidence_agent.deterministic_numeric_selection import (
    select_numeric_observations_deterministically,
)


def _bundle(intent="current_state"):
    return {"intent": intent, "patient_id": "p1", "evidence_by_tool": {}}


def _catalog():
    return {
        "status": "ok",
        "labs": [
            {
                "code": "A",
                "last_date": "2026-08-10",
                "measurement_count": 10,
                "recent_measurement_count": 5,
                "available_units": [
                    {"unit": "u1", "measurement_count": 10, "recent_measurement_count": 5}
                ],
            },
            {
                "code": "B",
                "last_date": "2026-08-12",
                "measurement_count": 2,
                "recent_measurement_count": 2,
                "available_units": [
                    {"unit": "old", "measurement_count": 9, "recent_measurement_count": 0},
                    {"unit": "recent", "measurement_count": 2, "recent_measurement_count": 2},
                ],
            },
            {
                "code": "C",
                "last_date": "2025-01-01",
                "measurement_count": 100,
                "recent_measurement_count": 0,
                "available_units": [
                    {"unit": "u", "measurement_count": 100, "recent_measurement_count": 0}
                ],
            },
        ],
    }


def test_deterministic_selection_needs_no_model_and_prefers_recent_candidates():
    result = select_numeric_observations_deterministically(
        bundle=_bundle(),
        catalog=_catalog(),
        limit=2,
    )
    assert [item.code for item in result.selections] == ["B", "A"]
    assert result.selections[0].unit == "recent"
    assert all("Deterministic live-path candidate" in item.rationale for item in result.selections)


def test_deterministic_selection_excludes_no_recent_data():
    result = select_numeric_observations_deterministically(
        bundle=_bundle(),
        catalog=_catalog(),
        limit=8,
    )
    assert {item.code for item in result.selections} == {"A", "B"}


def test_deterministic_selection_respects_zero_limit():
    result = select_numeric_observations_deterministically(
        bundle=_bundle("trajectory"),
        catalog=_catalog(),
        limit=0,
    )
    assert result.intent.value == "trajectory"
    assert result.selections == ()


@pytest.mark.parametrize("bad", [-1, True, 1.5])
def test_deterministic_selection_rejects_invalid_limit(bad):
    with pytest.raises((TypeError, ValueError)):
        select_numeric_observations_deterministically(
            bundle=_bundle(),
            catalog=_catalog(),
            limit=bad,
        )
