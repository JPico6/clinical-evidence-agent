from clinical_evidence_agent.streamlit_app import QUESTION_BY_INTENT, _display_name
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent


def test_streamlit_questions_cover_supported_intents():
    assert set(QUESTION_BY_INTENT) == {
        ClinicalEvidenceIntent.CURRENT_STATE,
        ClinicalEvidenceIntent.TRAJECTORY,
    }


def test_patient_display_name_uses_name_and_birth_date():
    assert _display_name(
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "birth_date": "1815-12-10",
        }
    ) == "Ada Lovelace · DOB 1815-12-10"


def test_patient_display_name_handles_missing_name():
    assert _display_name({"birth_date": None}) == "Synthetic patient"
