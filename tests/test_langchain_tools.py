from clinical_evidence_agent.evidence_tools import (
    EVIDENCE_TOOL_CONTRACTS,
    EvidenceToolset,
)
from clinical_evidence_agent.langchain_tools import (
    LabEvidenceInput,
    PatientEvidenceInput,
    PatientLookbackEvidenceInput,
    build_langchain_evidence_tools,
    get_langchain_evidence_tool_map,
)


PATIENT_ID = "patient-1"


class DummyConnection:
    pass


def make_stubbed_toolset(monkeypatch):
    toolset = EvidenceToolset(DummyConnection())

    monkeypatch.setattr(
        toolset,
        "get_utilization_evidence",
        lambda patient_id: {
            "status": "ok",
            "patient_id": patient_id,
            "domain": "utilization",
        },
    )
    monkeypatch.setattr(
        toolset,
        "get_lab_evidence",
        lambda patient_id, code, unit=None: {
            "status": "ok",
            "patient_id": patient_id,
            "domain": "lab",
            "code": code,
            "unit": unit,
        },
    )

    for method_name, domain in (
        ("get_condition_evidence", "condition"),
        ("get_medication_evidence", "medication"),
        ("get_procedure_evidence", "procedure"),
        ("get_recent_event_evidence", "recent_event"),
    ):
        monkeypatch.setattr(
            toolset,
            method_name,
            lambda patient_id, lookback_days=365, domain=domain: {
                "status": "ok",
                "patient_id": patient_id,
                "domain": domain,
                "lookback_days": lookback_days,
            },
        )

    return toolset


def test_langchain_tool_catalog_matches_deterministic_contract_catalog(monkeypatch):
    toolset = make_stubbed_toolset(monkeypatch)
    tools = build_langchain_evidence_tools(toolset)

    assert len(tools) == 6
    assert [tool.name for tool in tools] == [
        "get_utilization_evidence",
        "get_lab_evidence",
        "get_condition_evidence",
        "get_medication_evidence",
        "get_procedure_evidence",
        "get_recent_event_evidence",
    ]
    assert {tool.name for tool in tools} == set(EVIDENCE_TOOL_CONTRACTS)


def test_langchain_descriptions_preserve_contract_guardrails(monkeypatch):
    toolset = make_stubbed_toolset(monkeypatch)
    tools = get_langchain_evidence_tool_map(toolset)

    medication_description = tools["get_medication_evidence"].description
    assert "adherence" in medication_description
    assert "missing source STOP" in medication_description

    recent_event_description = tools["get_recent_event_evidence"].description
    assert "causality" in recent_event_description
    assert "Multi-domain does not mean clinically important" in recent_event_description

    utilization_description = tools["get_utilization_evidence"].description
    assert "clinical improvement or worsening" in utilization_description


def test_langchain_tools_use_explicit_input_schemas(monkeypatch):
    toolset = make_stubbed_toolset(monkeypatch)
    tools = get_langchain_evidence_tool_map(toolset)

    assert tools["get_utilization_evidence"].args_schema is PatientEvidenceInput
    assert tools["get_lab_evidence"].args_schema is LabEvidenceInput
    assert tools["get_condition_evidence"].args_schema is PatientLookbackEvidenceInput
    assert tools["get_medication_evidence"].args_schema is PatientLookbackEvidenceInput
    assert tools["get_procedure_evidence"].args_schema is PatientLookbackEvidenceInput
    assert tools["get_recent_event_evidence"].args_schema is PatientLookbackEvidenceInput


def test_langchain_invocation_returns_underlying_evidence_unchanged(monkeypatch):
    toolset = make_stubbed_toolset(monkeypatch)
    tools = get_langchain_evidence_tool_map(toolset)

    utilization = tools["get_utilization_evidence"].invoke(
        {"patient_id": PATIENT_ID}
    )
    assert utilization == {
        "status": "ok",
        "patient_id": PATIENT_ID,
        "domain": "utilization",
    }

    lab = tools["get_lab_evidence"].invoke(
        {
            "patient_id": PATIENT_ID,
            "code": "33914-3",
            "unit": "mL/min/{1.73_m2}",
        }
    )
    assert lab == {
        "status": "ok",
        "patient_id": PATIENT_ID,
        "domain": "lab",
        "code": "33914-3",
        "unit": "mL/min/{1.73_m2}",
    }

    condition = tools["get_condition_evidence"].invoke(
        {"patient_id": PATIENT_ID, "lookback_days": 180}
    )
    assert condition == {
        "status": "ok",
        "patient_id": PATIENT_ID,
        "domain": "condition",
        "lookback_days": 180,
    }


def test_langchain_schema_validation_happens_before_toolset_invocation(monkeypatch):
    toolset = make_stubbed_toolset(monkeypatch)
    tools = get_langchain_evidence_tool_map(toolset)

    schema = tools["get_condition_evidence"].args_schema

    assert schema.model_json_schema()["properties"]["lookback_days"]["exclusiveMinimum"] == 0
    assert schema.model_json_schema()["properties"]["lookback_days"]["default"] == 365

    lab_schema = tools["get_lab_evidence"].args_schema.model_json_schema()
    assert set(lab_schema["required"]) == {"patient_id", "code"}
