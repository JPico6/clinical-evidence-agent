import pytest

from clinical_evidence_agent import evidence_tools
from clinical_evidence_agent.evidence_tools import (
    EVIDENCE_TOOL_CONTRACTS,
    EvidenceToolset,
)


PATIENT_ID = "patient-1"


class DummyConnection:
    pass


def make_toolset(monkeypatch, has_data=True):
    monkeypatch.setattr(
        evidence_tools.database,
        "get_patient_latest_date",
        lambda con, patient_id: object() if has_data else None,
    )
    return EvidenceToolset(DummyConnection())


def test_contract_catalog_is_complete_and_guardrail_explicit():
    expected_names = {
        "get_utilization_evidence",
        "get_lab_evidence",
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
        "get_recent_event_evidence",
    }

    assert set(EVIDENCE_TOOL_CONTRACTS) == expected_names

    toolset = EvidenceToolset(DummyConnection())
    contracts = toolset.list_contracts()

    assert [item["name"] for item in contracts] == sorted(expected_names)
    assert all(item["purpose"] for item in contracts)
    assert all(item["returns"] for item in contracts)
    assert all(item["limitations"] for item in contracts)

    medication = toolset.get_contract("get_medication_evidence")
    assert any("adherence" in item for item in medication["limitations"])

    recent_events = toolset.get_contract("get_recent_event_evidence")
    assert any("causality" in item for item in recent_events["limitations"])


def test_toolset_delegates_to_domain_builders_without_reinterpreting(monkeypatch):
    toolset = make_toolset(monkeypatch)

    calls = []

    def fake_builder(con, patient_id, lookback_days=365):
        calls.append((con, patient_id, lookback_days))
        return {
            "status": "ok",
            "patient_id": patient_id,
            "marker": "domain-evidence",
        }

    monkeypatch.setattr(
        evidence_tools.database,
        "build_condition_evidence",
        fake_builder,
    )

    result = toolset.get_condition_evidence(PATIENT_ID, lookback_days=180)

    assert result == {
        "status": "ok",
        "patient_id": PATIENT_ID,
        "marker": "domain-evidence",
    }
    assert calls == [(toolset._con, PATIENT_ID, 180)]


def test_lab_tool_preserves_explicit_code_and_unit(monkeypatch):
    toolset = make_toolset(monkeypatch)
    calls = []

    def fake_lab_builder(con, patient_id, code, unit=None):
        calls.append((con, patient_id, code, unit))
        return {
            "status": "ok",
            "patient_id": patient_id,
            "code": code,
            "unit": unit,
        }

    monkeypatch.setattr(
        evidence_tools.database,
        "build_lab_evidence",
        fake_lab_builder,
    )

    result = toolset.get_lab_evidence(
        PATIENT_ID,
        "33914-3",
        unit="mL/min/{1.73_m2}",
    )

    assert result["code"] == "33914-3"
    assert result["unit"] == "mL/min/{1.73_m2}"
    assert calls == [
        (
            toolset._con,
            PATIENT_ID,
            "33914-3",
            "mL/min/{1.73_m2}",
        )
    ]


def test_no_patient_data_short_circuits_before_fragile_domain_logic(monkeypatch):
    toolset = make_toolset(monkeypatch, has_data=False)

    def should_not_run(*args, **kwargs):
        raise AssertionError("domain builder should not run")

    monkeypatch.setattr(
        evidence_tools.database,
        "build_utilization_evidence",
        should_not_run,
    )
    monkeypatch.setattr(
        evidence_tools.database,
        "build_lab_evidence",
        should_not_run,
    )

    assert toolset.get_utilization_evidence(PATIENT_ID) == {
        "status": "no_data",
        "patient_id": PATIENT_ID,
    }
    assert toolset.get_lab_evidence(PATIENT_ID, "33914-3") == {
        "status": "no_data",
        "patient_id": PATIENT_ID,
        "code": "33914-3",
    }


def test_boundary_validation_rejects_ambiguous_inputs(monkeypatch):
    toolset = make_toolset(monkeypatch)

    with pytest.raises(ValueError, match="patient_id"):
        toolset.get_condition_evidence("   ")

    with pytest.raises(ValueError, match="lookback_days"):
        toolset.get_medication_evidence(PATIENT_ID, lookback_days=0)

    with pytest.raises(ValueError, match="lookback_days"):
        toolset.get_procedure_evidence(PATIENT_ID, lookback_days=True)

    with pytest.raises(ValueError, match="code"):
        toolset.get_lab_evidence(PATIENT_ID, "")

    with pytest.raises(ValueError, match="unit"):
        toolset.get_lab_evidence(PATIENT_ID, "33914-3", unit="  ")

    with pytest.raises(KeyError, match="Unknown evidence tool"):
        toolset.get_contract("not_a_tool")
