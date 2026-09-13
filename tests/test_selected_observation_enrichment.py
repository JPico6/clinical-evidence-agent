from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent
from clinical_evidence_agent.llm_synthesis import build_synthesis_messages
from clinical_evidence_agent.selected_observation_evidence import (
    SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL,
    build_citable_selected_observation_evidence,
    enrich_evidence_bundle_with_selected_observations,
)
from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    SynthesisFinding,
    validate_synthesis_against_bundle,
)


def _package():
    evidence = {
        "status": "ok",
        "code": "2160-0",
        "unit": "mg/dL",
        "latest_measurement": {
            "date": "2026-08-12",
            "value": 2.3,
            "ambiguous": False,
        },
    }
    return {
        "intent": "current_state",
        "selection_notes": ["Model-generated note that must not be citable."],
        "selected_observation_count": 1,
        "observations": [
            {
                "code": "2160-0",
                "unit": "mg/dL",
                "selection_rationale": "Model-generated rationale that must not be citable.",
                "evidence": evidence,
            }
        ],
    }


def _bundle():
    return {
        "patient_id": "patient-1",
        "intent": "current_state",
        "lookback_days": 365,
        "routing_notes": [],
        "conditional_tools": ["get_lab_evidence"],
        "tool_results": [],
        "evidence_by_tool": {
            "get_condition_evidence": {"status": "ok", "new_conditions": []}
        },
    }


def test_citable_payload_strips_selector_rationale_and_notes():
    payload = build_citable_selected_observation_evidence(_package())

    assert payload["selected_observation_count"] == 1
    assert "selection_notes" not in payload
    item = payload["observations"][0]
    assert set(item) == {"code", "unit", "evidence"}
    assert "selection_rationale" not in item


def test_enrichment_adds_deterministic_evidence_without_mutating_original_bundle():
    bundle = _bundle()
    enriched = enrich_evidence_bundle_with_selected_observations(
        bundle=bundle,
        package=_package(),
    )

    assert SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL not in bundle["evidence_by_tool"]
    assert SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL in enriched["evidence_by_tool"]
    assert (
        enriched["evidence_by_tool"][SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL]
        ["observations"][0]["evidence"]["latest_measurement"]["value"]
        == 2.3
    )


def test_selection_metadata_is_outside_citable_evidence_namespace():
    enriched = enrich_evidence_bundle_with_selected_observations(
        bundle=_bundle(),
        package=_package(),
    )

    metadata = enriched["numeric_observation_selection_metadata"]
    assert metadata["selection_notes"]
    assert metadata["selection_rationales"]
    assert "numeric_observation_selection_metadata" not in enriched["evidence_by_tool"]


def test_synthesis_prompt_receives_numeric_evidence_but_not_selection_metadata():
    enriched = enrich_evidence_bundle_with_selected_observations(
        bundle=_bundle(),
        package=_package(),
    )
    messages = build_synthesis_messages(enriched)
    human_text = messages[-1].content

    assert SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL in human_text
    assert '"value":2.3' in human_text
    assert "Model-generated rationale that must not be citable." not in human_text
    assert "Model-generated note that must not be citable." not in human_text


def test_validator_accepts_reference_into_numeric_observation_evidence():
    enriched = enrich_evidence_bundle_with_selected_observations(
        bundle=_bundle(),
        package=_package(),
    )
    ref = EvidenceReference(
        tool_name=SELECTED_NUMERIC_OBSERVATION_EVIDENCE_TOOL,
        path=("observations", 0, "evidence", "latest_measurement"),
    )
    finding = SynthesisFinding(
        statement="Latest creatinine was 2.3 mg/dL on 2026-08-12.",
        evidence_refs=(ref,),
    )
    synthesis = CurrentStateSynthesis(
        intent=ClinicalEvidenceIntent.CURRENT_STATE,
        overall_assessment=finding,
    )

    assert validate_synthesis_against_bundle(synthesis, enriched) is synthesis
