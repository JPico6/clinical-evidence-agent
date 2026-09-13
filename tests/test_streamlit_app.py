from datetime import datetime

from clinical_evidence_agent.streamlit_app import (
    QUESTION_BY_INTENT,
    _anchor_date,
    _build_reference_index,
    _citation_suffix,
    _display_name,
    _format_date,
    _gender_label,
    _human_evidence_label,
    _resolve_path,
)
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent


def test_streamlit_questions_cover_supported_intents():
    assert set(QUESTION_BY_INTENT) == {
        ClinicalEvidenceIntent.CURRENT_STATE,
        ClinicalEvidenceIntent.TRAJECTORY,
    }


def test_patient_display_name_formats_date_without_midnight_timestamp():
    assert _display_name(
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "birth_date": datetime(1815, 12, 10),
        }
    ) == "Ada Lovelace · DOB Dec 10, 1815"


def test_patient_display_name_handles_missing_name():
    assert _display_name({"birth_date": None}) == "Synthetic patient"


def test_format_date_accepts_iso_datetime_string():
    assert _format_date("1999-11-07 00:00:00") == "Nov 7, 1999"


def test_gender_label_expands_synthea_codes():
    assert _gender_label("F") == "Female"
    assert _gender_label("M") == "Male"


def test_reference_index_deduplicates_same_reference():
    payload = {
        "overall_assessment": {
            "statement": "A",
            "evidence_refs": [{"tool_name": "tool_a", "path": ["rows", 0]}],
        },
        "changes": [
            {
                "statement": "B",
                "evidence_refs": [
                    {"tool_name": "tool_a", "path": ["rows", 0]},
                    {"tool_name": "tool_b", "path": ["value"]},
                ],
            }
        ],
        "uncertainties": [],
    }
    index = _build_reference_index(payload)
    assert index == {
        ("tool_a", ("rows", 0)): 1,
        ("tool_b", ("value",)): 2,
    }
    assert _citation_suffix(payload["changes"][0], index) == " [1] [2]"


def test_resolve_path_returns_cited_payload():
    payload = {"rows": [{"value": 7}]}
    assert _resolve_path(payload, ["rows", 0, "value"]) == 7
    assert _resolve_path(payload, ["rows", 2]) is None


def test_anchor_date_uses_first_available_evidence_anchor():
    bundle = {
        "evidence_by_tool": {
            "a": {"status": "ok"},
            "b": {"anchor_date": "2026-02-28"},
        }
    }
    assert _anchor_date(bundle) == "2026-02-28"


def test_human_evidence_labels_hide_tool_implementation_names():
    assert _human_evidence_label("get_condition_evidence") == "Conditions"
    assert (
        _human_evidence_label("get_selected_numeric_observation_evidence")
        == "Measurements & labs"
    )
