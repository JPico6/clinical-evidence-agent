"""Offline review artifacts for completed multi-patient evaluation runs.

This module performs no model calls and has no database dependency. It turns a
saved ``MultiPatientEvaluationRun`` JSON artifact into:

1. a compact Markdown review report for human inspection; and
2. a JSON score template for semantic review.

The saved benchmark remains the source of truth. Human semantic scores are kept
separate from deterministic checks so subjective review cannot overwrite
mechanically verified properties such as citation validity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


HUMAN_RUBRIC_VERSION = "1.0"
HUMAN_SCORE_MIN = 1
HUMAN_SCORE_MAX = 5

HUMAN_RUBRIC: tuple[dict[str, str], ...] = (
    {
        "id": "grounding_inference_discipline",
        "name": "Grounding / inference discipline",
        "question": (
            "Are substantive claims supported by the supplied evidence without "
            "turning source-open records, medication records, source reasons, "
            "numeric changes, or exact-date grouping into stronger clinical claims?"
        ),
        "score_1": "Material unsupported inference or guardrail violation.",
        "score_3": "Mostly grounded, with one meaningful overstatement or ambiguous inference.",
        "score_5": "Claims remain carefully bounded by the evidence and its provenance semantics.",
    },
    {
        "id": "major_issue_completeness",
        "name": "Major-issue completeness",
        "question": (
            "Does the synthesis capture the major evidence-supported issues or "
            "changes needed to answer the intent, without requiring exhaustive coverage?"
        ),
        "score_1": "Misses one or more central issues, substantially distorting the overall picture.",
        "score_3": "Captures the main picture but omits a meaningful issue or change.",
        "score_5": "Captures the major issues needed for the task; omissions are reasonably peripheral.",
    },
    {
        "id": "salience_materiality",
        "name": "Salience / materiality",
        "question": (
            "Are included findings materially useful for the task, with peripheral, "
            "frequency-driven, or weak numeric filler omitted?"
        ),
        "score_1": "Answer is dominated by peripheral/inventory-like content or misses obvious prioritization.",
        "score_3": "Generally prioritized, but includes one or more questionable lower-value findings.",
        "score_5": "Concise, strongly prioritized, and avoids filler even when more evidence is available.",
    },
    {
        "id": "uncertainty_calibration",
        "name": "Uncertainty calibration",
        "question": (
            "Does the synthesis preserve important missing, sparse, conflicting, "
            "ambiguous, or documentation-limited evidence without becoming evasive?"
        ),
        "score_1": "Important uncertainty is ignored/resolved without support, or uncertainty overwhelms useful conclusions.",
        "score_3": "Most uncertainty is handled appropriately, with some under- or over-emphasis.",
        "score_5": "Important uncertainty is explicit, proportionate, and tied to the evidence limitation.",
    },
    {
        "id": "temporal_reasoning",
        "name": "Temporal reasoning",
        "question": (
            "Does the answer correctly distinguish historical, recent, latest, repeated, "
            "and changing evidence relative to the patient's own anchor date?"
        ),
        "score_1": "Material temporal confusion changes the meaning of the record.",
        "score_3": "Overall chronology is sound but one temporal distinction is weak or unclear.",
        "score_5": "Temporal statements are accurate, patient-relative, and appropriately qualified.",
    },
)


def load_evaluation_run(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a completed evaluation artifact."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    required = {
        "evaluation_run_version",
        "model_name",
        "reasoning_effort",
        "lookback_days",
        "patients",
        "summary",
    }
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"evaluation artifact missing required keys: {missing}")
    if not isinstance(payload["patients"], list):
        raise TypeError("evaluation artifact patients must be a list")
    return payload


def _intent_findings(synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    if synthesis.get("intent") == "current_state":
        return list(synthesis.get("findings", []))
    return list(synthesis.get("changes", []))


def _deterministic_checks(result: dict[str, Any]) -> tuple[int, int]:
    evaluation = result.get("deterministic_evaluation") or {}
    checks = evaluation.get("checks") or []
    return sum(bool(check.get("passed")) for check in checks), len(checks)


def _selected_observation_labels(result: dict[str, Any]) -> list[str]:
    selection = result.get("selection") or {}
    labels: list[str] = []
    for item in selection.get("selections", []):
        code = str(item.get("code", ""))
        unit = item.get("unit")
        labels.append(f"{code} [{unit}]" if unit else code)
    return labels


def build_review_case(patient: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Build a compact non-generative view of one patient/intent result."""
    if result.get("status") != "ok":
        return {
            "patient_id": patient.get("patient_id"),
            "cohort_label": patient.get("cohort_label"),
            "intent": result.get("intent"),
            "status": result.get("status"),
            "error_type": result.get("error_type"),
            "error_message": result.get("error_message"),
        }

    synthesis = result.get("synthesis") or {}
    findings = _intent_findings(synthesis)
    uncertainties = list(synthesis.get("uncertainties", []))
    passed_checks, total_checks = _deterministic_checks(result)
    selection = result.get("selection") or {}

    return {
        "patient_id": patient.get("patient_id"),
        "cohort_label": patient.get("cohort_label"),
        "cohort_rationale": patient.get("rationale"),
        "anchor_date": (patient.get("profile") or {}).get("anchor_date"),
        "intent": result.get("intent"),
        "status": "ok",
        "selected_observation_count": len(selection.get("selections", [])),
        "selected_observations": _selected_observation_labels(result),
        "selection_notes": list(selection.get("selection_notes", [])),
        "overall_assessment": (synthesis.get("overall_assessment") or {}).get("statement"),
        "findings": [item.get("statement") for item in findings],
        "uncertainties": [item.get("statement") for item in uncertainties],
        "finding_count": len(findings),
        "uncertainty_count": len(uncertainties),
        "deterministic_passed": bool(
            (result.get("deterministic_evaluation") or {}).get("passed")
        ),
        "deterministic_checks_passed": passed_checks,
        "deterministic_checks_total": total_checks,
    }


def build_compact_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract all patient/intent cases into a compact offline review structure."""
    cases = [
        build_review_case(patient, result)
        for patient in payload["patients"]
        for result in patient.get("intent_results", [])
    ]
    ok_cases = [case for case in cases if case.get("status") == "ok"]
    finding_counts = [int(case["finding_count"]) for case in ok_cases]
    uncertainty_counts = [int(case["uncertainty_count"]) for case in ok_cases]
    selected_counts = [int(case["selected_observation_count"]) for case in ok_cases]

    def mean(values: list[int]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    return {
        "evaluation_run_version": payload["evaluation_run_version"],
        "model_name": payload["model_name"],
        "reasoning_effort": payload["reasoning_effort"],
        "lookback_days": payload["lookback_days"],
        "source_summary": payload["summary"],
        "offline_review_summary": {
            "case_count": len(cases),
            "ok_case_count": len(ok_cases),
            "mean_finding_count": mean(finding_counts),
            "min_finding_count": min(finding_counts) if finding_counts else None,
            "max_finding_count": max(finding_counts) if finding_counts else None,
            "mean_uncertainty_count": mean(uncertainty_counts),
            "mean_selected_observation_count": mean(selected_counts),
        },
        "cases": cases,
    }


def build_human_score_template(review: dict[str, Any]) -> dict[str, Any]:
    """Create an empty semantic scorecard without changing benchmark outputs."""
    return {
        "human_rubric_version": HUMAN_RUBRIC_VERSION,
        "source_evaluation_run_version": review["evaluation_run_version"],
        "model_name": review["model_name"],
        "reasoning_effort": review["reasoning_effort"],
        "score_range": {"min": HUMAN_SCORE_MIN, "max": HUMAN_SCORE_MAX},
        "rubric": list(HUMAN_RUBRIC),
        "cases": [
            {
                "patient_id": case["patient_id"],
                "cohort_label": case["cohort_label"],
                "intent": case["intent"],
                "status": case["status"],
                "scores": {
                    dimension["id"]: None for dimension in HUMAN_RUBRIC
                },
                "reviewer_notes": "",
                "critical_failure": False,
                "critical_failure_reason": "",
            }
            for case in review["cases"]
        ],
    }


def _md_escape(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown_report(review: dict[str, Any]) -> str:
    """Render a compact human-review report from an offline review object."""
    summary = review["offline_review_summary"]
    lines = [
        "# Multi-patient synthesis evaluation review",
        "",
        "This report is generated entirely offline from a completed evaluation JSON artifact. It performs no model calls and does not alter the frozen synthesis outputs.",
        "",
        "## Run summary",
        "",
        f"- Model: `{review['model_name']}`",
        f"- Reasoning effort: `{review['reasoning_effort']}`",
        f"- Lookback: {review['lookback_days']} days",
        f"- Cases: {summary['ok_case_count']}/{summary['case_count']} successful",
        f"- Mean substantive findings/changes: {summary['mean_finding_count']}",
        f"- Finding/change range: {summary['min_finding_count']}–{summary['max_finding_count']}",
        f"- Mean uncertainties: {summary['mean_uncertainty_count']}",
        f"- Mean selected numeric observations: {summary['mean_selected_observation_count']}",
        "",
        "## Semantic review rubric",
        "",
        "Score each dimension from 1–5. Deterministic checks remain separate and are not replaced by these subjective scores.",
        "",
    ]
    for dimension in HUMAN_RUBRIC:
        lines.extend(
            [
                f"### {dimension['name']}",
                "",
                dimension["question"],
                "",
                f"- **1:** {dimension['score_1']}",
                f"- **3:** {dimension['score_3']}",
                f"- **5:** {dimension['score_5']}",
                "",
            ]
        )

    lines.extend(["## Case index", "", "| # | Cohort | Intent | Anchor | Findings | Uncertainties | Numeric selections | Deterministic |", "|---:|---|---|---|---:|---:|---:|---|"])
    for index, case in enumerate(review["cases"], start=1):
        if case.get("status") != "ok":
            lines.append(
                f"| {index} | {_md_escape(case.get('cohort_label'))} | {_md_escape(case.get('intent'))} | — | — | — | — | ERROR |"
            )
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _md_escape(case["cohort_label"]),
                    _md_escape(case["intent"]),
                    _md_escape(case["anchor_date"]),
                    str(case["finding_count"]),
                    str(case["uncertainty_count"]),
                    str(case["selected_observation_count"]),
                    f"{case['deterministic_checks_passed']}/{case['deterministic_checks_total']} PASS",
                ]
            )
            + " |"
        )

    for index, case in enumerate(review["cases"], start=1):
        lines.extend(
            [
                "",
                f"## Case {index}: {case.get('cohort_label')} / {case.get('intent')}",
                "",
                f"- Patient: `{case.get('patient_id')}`",
            ]
        )
        if case.get("status") != "ok":
            lines.extend(
                [
                    f"- Status: ERROR — {case.get('error_type')}: {case.get('error_message')}",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                f"- Anchor date: {case.get('anchor_date')}",
                f"- Cohort purpose: {case.get('cohort_rationale')}",
                f"- Deterministic checks: {case['deterministic_checks_passed']}/{case['deterministic_checks_total']} passed",
                f"- Selected numeric observations ({case['selected_observation_count']}): "
                + (", ".join(f"`{label}`" for label in case["selected_observations"]) or "none"),
                "",
                "**Overall assessment**",
                "",
                case.get("overall_assessment") or "_None_",
                "",
                "**Findings / changes**",
                "",
            ]
        )
        if case["findings"]:
            lines.extend(f"{i}. {statement}" for i, statement in enumerate(case["findings"], start=1))
        else:
            lines.append("_None._")
        lines.extend(["", "**Uncertainties**", ""])
        if case["uncertainties"]:
            lines.extend(f"- {statement}" for statement in case["uncertainties"])
        else:
            lines.append("_None._")
        lines.extend(
            [
                "",
                "**Human review**",
                "",
                "- Grounding / inference discipline: __/5",
                "- Major-issue completeness: __/5",
                "- Salience / materiality: __/5",
                "- Uncertainty calibration: __/5",
                "- Temporal reasoning: __/5",
                "- Critical failure: yes / no",
                "- Notes:",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def write_offline_review_artifacts(
    source_path: str | Path,
    *,
    output_dir: str | Path,
) -> dict[str, Path]:
    """Write compact JSON, Markdown review, and empty human scorecard."""
    payload = load_evaluation_run(source_path)
    review = build_compact_review(payload)
    score_template = build_human_score_template(review)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    compact_path = output / "multipatient_evaluation_compact.json"
    report_path = output / "multipatient_evaluation_review.md"
    scores_path = output / "multipatient_evaluation_human_scores.json"

    compact_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    report_path.write_text(render_markdown_report(review), encoding="utf-8")
    scores_path.write_text(json.dumps(score_template, indent=2), encoding="utf-8")

    return {
        "compact_review": compact_path,
        "markdown_report": report_path,
        "human_score_template": scores_path,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate offline human-review artifacts from a completed evaluation JSON run."
    )
    parser.add_argument("source", help="Completed multipatient_evaluation.json")
    parser.add_argument(
        "--output-dir",
        default="evaluation_runs/review",
        help="Directory for offline review artifacts.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    written = write_offline_review_artifacts(args.source, output_dir=args.output_dir)
    print(json.dumps({name: str(path) for name, path in written.items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
