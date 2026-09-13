import json

import pytest

from clinical_evidence_agent.offline_evaluation_report import (
    HUMAN_RUBRIC,
    build_compact_review,
    build_human_score_template,
    load_evaluation_run,
    render_markdown_report,
    write_offline_review_artifacts,
)


def _finding(statement):
    return {"statement": statement, "evidence_refs": []}


def _payload():
    return {
        "evaluation_run_version": "1.0",
        "model_name": "test-model",
        "reasoning_effort": "medium",
        "lookback_days": 365,
        "summary": {
            "patient_count": 1,
            "intent_case_count": 2,
            "successful_intent_cases": 2,
            "failed_intent_cases": 0,
            "deterministic_pass_count": 2,
            "deterministic_fail_count": 0,
        },
        "patients": [
            {
                "patient_id": "p1",
                "cohort_label": "sparse_record",
                "rationale": "Sparse case.",
                "profile": {"anchor_date": "2026-06-30"},
                "intent_results": [
                    {
                        "intent": "current_state",
                        "status": "ok",
                        "selection": {
                            "intent": "current_state",
                            "selections": [
                                {"code": "123", "unit": "mg/dL", "rationale": "why"}
                            ],
                            "selection_notes": [],
                        },
                        "synthesis": {
                            "intent": "current_state",
                            "overall_assessment": _finding("Overall current state."),
                            "findings": [_finding("Finding one."), _finding("Finding two.")],
                            "uncertainties": [_finding("Uncertain one.")],
                        },
                        "deterministic_evaluation": {
                            "passed": True,
                            "checks": [
                                {"name": "a", "passed": True, "detail": "ok"},
                                {"name": "b", "passed": True, "detail": "ok"},
                            ],
                        },
                    },
                    {
                        "intent": "trajectory",
                        "status": "ok",
                        "selection": {
                            "intent": "trajectory",
                            "selections": [],
                            "selection_notes": [],
                        },
                        "synthesis": {
                            "intent": "trajectory",
                            "overall_assessment": _finding("Overall trajectory."),
                            "changes": [_finding("Change one.")],
                            "uncertainties": [],
                        },
                        "deterministic_evaluation": {
                            "passed": True,
                            "checks": [{"name": "a", "passed": True, "detail": "ok"}],
                        },
                    },
                ],
            }
        ],
    }


def test_compact_review_extracts_both_intent_shapes():
    review = build_compact_review(_payload())

    assert len(review["cases"]) == 2
    assert review["cases"][0]["finding_count"] == 2
    assert review["cases"][1]["finding_count"] == 1
    assert review["offline_review_summary"]["mean_finding_count"] == 1.5


def test_compact_review_preserves_numeric_selection_without_rationale_as_evidence():
    review = build_compact_review(_payload())
    case = review["cases"][0]

    assert case["selected_observation_count"] == 1
    assert case["selected_observations"] == ["123 [mg/dL]"]


def test_human_score_template_is_empty_and_separate_from_deterministic_results():
    template = build_human_score_template(build_compact_review(_payload()))

    assert set(template["cases"][0]["scores"]) == {d["id"] for d in HUMAN_RUBRIC}
    assert all(score is None for score in template["cases"][0]["scores"].values())
    assert "deterministic_evaluation" not in template["cases"][0]


def test_markdown_report_contains_rubric_and_case_sections():
    text = render_markdown_report(build_compact_review(_payload()))

    assert "# Multi-patient synthesis evaluation review" in text
    assert "Grounding / inference discipline" in text
    assert "Case 1: sparse_record / current_state" in text
    assert "Finding one." in text
    assert "Critical failure: yes / no" in text


def test_writer_creates_three_offline_artifacts(tmp_path):
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_payload()))

    written = write_offline_review_artifacts(source, output_dir=tmp_path / "review")

    assert set(written) == {
        "compact_review",
        "markdown_report",
        "human_score_template",
    }
    assert all(path.exists() for path in written.values())


def test_loader_rejects_missing_required_keys(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text(json.dumps({"patients": []}))

    with pytest.raises(ValueError, match="missing required keys"):
        load_evaluation_run(source)


def test_failed_case_is_retained_for_review():
    payload = _payload()
    payload["patients"][0]["intent_results"][1] = {
        "intent": "trajectory",
        "status": "error",
        "error_type": "RuntimeError",
        "error_message": "boom",
    }

    review = build_compact_review(payload)
    failed = review["cases"][1]

    assert failed["status"] == "error"
    assert failed["error_type"] == "RuntimeError"


def test_report_generation_requires_no_evidence_bundle():
    # The report operates on already-saved synthesis/evaluation outputs and does
    # not need to duplicate the many-megabyte evidence bundle in its compact view.
    payload = _payload()
    assert "evidence_bundle" not in payload["patients"][0]["intent_results"][0]

    review = build_compact_review(payload)

    assert review["cases"][0]["overall_assessment"] == "Overall current state."
