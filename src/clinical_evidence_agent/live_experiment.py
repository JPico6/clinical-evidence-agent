"""Small live experiment for the first constrained clinical synthesis calls.

This module deliberately adds no new agent behavior. It wires together the
already-tested deterministic evidence workflow and constrained synthesis layer
so we can inspect real model output for the two supported tasks.

Usage::

    uv run python -m clinical_evidence_agent.live_experiment
    uv run python -m clinical_evidence_agent.live_experiment --intent trajectory
    uv run python -m clinical_evidence_agent.live_experiment --model gpt-5.6-sol

``OPENAI_API_KEY`` is read by ``ChatOpenAI``. ``.env`` is loaded when present.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from typing import Any

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from clinical_evidence_agent import database
from clinical_evidence_agent.evidence_routing import (
    ClinicalEvidenceIntent,
    DEFAULT_LOOKBACK_DAYS,
)
from clinical_evidence_agent.evidence_tools import EvidenceToolset
from clinical_evidence_agent.evidence_workflow import build_clinical_evidence_workflow
from clinical_evidence_agent.llm_synthesis import synthesize_evidence_bundle
from clinical_evidence_agent.synthesis_contract import ClinicalSynthesis


REFERENCE_PATIENT_ID = "bca1691f-8839-1d66-ed01-471134d55738"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"


def resolve_intents(intent: str) -> tuple[ClinicalEvidenceIntent, ...]:
    """Expand a CLI intent into one or both supported synthesis tasks."""
    if intent == "both":
        return (
            ClinicalEvidenceIntent.CURRENT_STATE,
            ClinicalEvidenceIntent.TRAJECTORY,
        )
    return (ClinicalEvidenceIntent(intent),)


def create_openai_model(
    *,
    model_name: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
) -> BaseChatModel:
    """Create the model used by the live experiment.

    Model construction is kept outside the synthesis boundary; the synthesis
    function still receives a dependency-injected ``BaseChatModel`` and grants
    it no tools.
    """
    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name must be a non-empty string")
    return ChatOpenAI(
        model=model_name.strip(),
        reasoning_effort=reasoning_effort,
    )


def run_synthesis_case(
    *,
    workflow: Any,
    model: BaseChatModel,
    patient_id: str,
    intent: ClinicalEvidenceIntent | str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> ClinicalSynthesis:
    """Run one deterministic evidence workflow followed by constrained synthesis."""
    intent = ClinicalEvidenceIntent(intent)
    state = workflow.invoke(
        {
            "patient_id": patient_id,
            "intent": intent.value,
            "lookback_days": lookback_days,
        }
    )
    if "evidence_bundle" not in state:
        raise RuntimeError("evidence workflow did not return evidence_bundle")
    return synthesize_evidence_bundle(
        model=model,
        bundle=state["evidence_bundle"],
    )


def synthesis_to_json(synthesis: ClinicalSynthesis) -> str:
    """Render validated structured synthesis for human inspection or capture."""
    return json.dumps(
        synthesis.model_dump(mode="json"),
        indent=2,
        sort_keys=False,
    )


def run_live_experiment(
    *,
    patient_id: str = REFERENCE_PATIENT_ID,
    intents: Iterable[ClinicalEvidenceIntent] = (
        ClinicalEvidenceIntent.CURRENT_STATE,
        ClinicalEvidenceIntent.TRAJECTORY,
    ),
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    model_name: str = DEFAULT_MODEL,
) -> dict[str, ClinicalSynthesis]:
    """Run the first live model experiment against the existing Synthea stack."""
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to the environment or local .env file."
        )

    con = database.get_connection()
    try:
        database.register_synthea_tables(con)
        toolset = EvidenceToolset(con)
        workflow = build_clinical_evidence_workflow(toolset)
        model = create_openai_model(model_name=model_name)

        results: dict[str, ClinicalSynthesis] = {}
        for intent in intents:
            resolved = ClinicalEvidenceIntent(intent)
            results[resolved.value] = run_synthesis_case(
                workflow=workflow,
                model=model,
                patient_id=patient_id,
                intent=resolved,
                lookback_days=lookback_days,
            )
        return results
    finally:
        con.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run constrained live synthesis over deterministic Synthea evidence."
    )
    parser.add_argument(
        "--patient-id",
        default=REFERENCE_PATIENT_ID,
        help="Synthea patient identifier (defaults to the rich reference patient).",
    )
    parser.add_argument(
        "--intent",
        choices=("current_state", "trajectory", "both"),
        default="both",
        help="Which supported synthesis task to run.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="Patient-relative lookback used by deterministic evidence tools.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("CLINICAL_EVIDENCE_MODEL", DEFAULT_MODEL),
        help=(
            "OpenAI model name. Defaults to CLINICAL_EVIDENCE_MODEL when set, "
            f"otherwise {DEFAULT_MODEL}."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    results = run_live_experiment(
        patient_id=args.patient_id,
        intents=resolve_intents(args.intent),
        lookback_days=args.lookback_days,
        model_name=args.model,
    )

    for index, (intent, synthesis) in enumerate(results.items()):
        if index:
            print()
        print(f"=== {intent} ===")
        print(synthesis_to_json(synthesis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
