import pytest
from pydantic import ValidationError

from clinical_evidence_agent.synthesis_contract import (
    CurrentStateSynthesis,
    EvidenceReference,
    MAX_CURRENT_STATE_FINDINGS,
    MAX_TRAJECTORY_CHANGES,
    SynthesisFinding,
    TrajectorySynthesis,
    get_synthesis_guardrails,
)


def _finding(index: int = 0):
    return SynthesisFinding(
        statement=f"Finding {index}",
        evidence_refs=(
            EvidenceReference(
                tool_name="get_condition_evidence",
                path=("conditions", index),
            ),
        ),
    )


def test_current_state_contract_accepts_six_findings():
    synthesis = CurrentStateSynthesis(
        overall_assessment=_finding(),
        findings=tuple(_finding(i) for i in range(MAX_CURRENT_STATE_FINDINGS)),
    )
    assert len(synthesis.findings) == 6


def test_current_state_contract_rejects_more_than_six_findings():
    with pytest.raises(ValidationError):
        CurrentStateSynthesis(
            overall_assessment=_finding(),
            findings=tuple(
                _finding(i)
                for i in range(MAX_CURRENT_STATE_FINDINGS + 1)
            ),
        )


def test_trajectory_contract_accepts_five_changes():
    synthesis = TrajectorySynthesis(
        overall_assessment=_finding(),
        changes=tuple(_finding(i) for i in range(MAX_TRAJECTORY_CHANGES)),
    )
    assert len(synthesis.changes) == 5


def test_trajectory_contract_rejects_more_than_five_changes():
    with pytest.raises(ValidationError):
        TrajectorySynthesis(
            overall_assessment=_finding(),
            changes=tuple(
                _finding(i)
                for i in range(MAX_TRAJECTORY_CHANGES + 1)
            ),
        )


def test_guardrails_explicitly_prioritize_salience_over_exhaustiveness():
    guardrails = " ".join(get_synthesis_guardrails("current_state")).lower()

    assert "omit lower-priority evidence" in guardrails
    assert "frequency alone does not imply importance" in guardrails
    assert "do not create a separate finding merely because" in guardrails
