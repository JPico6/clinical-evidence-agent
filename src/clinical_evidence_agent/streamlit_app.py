"""Streamlit portfolio application for the Clinical Evidence Agent."""

from __future__ import annotations

from datetime import date
from typing import Any

import streamlit as st

from clinical_evidence_agent.application_service import ClinicalEvidenceApplicationService
from clinical_evidence_agent.evidence_routing import ClinicalEvidenceIntent


st.set_page_config(
    page_title="Clinical Evidence Agent",
    page_icon="🩺",
    layout="wide",
)

QUESTION_BY_INTENT = {
    ClinicalEvidenceIntent.CURRENT_STATE: "Describe the patient's current medical situation",
    ClinicalEvidenceIntent.TRAJECTORY: "Explain how the patient is changing",
}


@st.cache_resource
def get_service() -> ClinicalEvidenceApplicationService:
    return ClinicalEvidenceApplicationService()


def _display_name(patient: dict[str, Any]) -> str:
    first = patient.get("first_name") or ""
    last = patient.get("last_name") or ""
    name = f"{first} {last}".strip() or "Synthetic patient"
    birth = patient.get("birth_date")
    return f"{name} · DOB {birth}" if birth else name


def _render_synthesis(synthesis: Any) -> None:
    payload = synthesis.model_dump(mode="json") if hasattr(synthesis, "model_dump") else synthesis
    assessment = payload.get("overall_assessment")
    if assessment:
        st.markdown(f"### {assessment}")

    items = payload.get("findings")
    if items is None:
        items = payload.get("changes", [])

    for item in items:
        statement = item.get("statement", "")
        if statement:
            st.markdown(f"- {statement}")

    uncertainties = payload.get("uncertainties", [])
    if uncertainties:
        st.markdown("#### Important uncertainties")
        for item in uncertainties:
            statement = item.get("statement", "")
            if statement:
                st.markdown(f"- {statement}")


def _render_evidence(bundle: dict[str, Any]) -> None:
    evidence = bundle.get("evidence_by_tool", {})
    if not evidence:
        st.info("No deterministic evidence was returned.")
        return

    for tool_name, payload in evidence.items():
        with st.expander(tool_name.replace("_", " ").title(), expanded=False):
            st.json(payload)


def main() -> None:
    st.title("Clinical Evidence Agent")
    st.caption(
        "A portfolio demonstration of deterministic longitudinal evidence retrieval "
        "with constrained LLM synthesis."
    )
    st.info(
        "Synthetic Synthea data only. This application is an engineering demonstration "
        "and is not intended for real patient information, clinical care, diagnosis, "
        "or treatment decisions.",
        icon="ℹ️",
    )

    try:
        service = get_service()
        patients = service.list_patients()
    except Exception as exc:
        st.error("The application could not initialize the local Synthea data.")
        with st.expander("Technical details"):
            st.exception(exc)
        return

    if not patients:
        st.warning("No synthetic patients were found.")
        return

    selected = st.selectbox(
        "Synthetic patient",
        patients,
        format_func=_display_name,
        index=0,
    )
    patient_id = selected["patient_id"]

    with st.container(border=True):
        cols = st.columns(4)
        cols[0].metric("Name", f"{selected.get('first_name') or ''} {selected.get('last_name') or ''}".strip())
        cols[1].metric("Birth date", str(selected.get("birth_date") or "Unknown"))
        cols[2].metric("Gender", str(selected.get("gender") or "Unknown"))
        cols[3].metric("Record", "Synthetic")

    st.subheader("Ask about this patient")
    st.write(
        "The application computes the patient evidence deterministically first. "
        "The language model receives structured evidence rather than raw longitudinal rows."
    )

    c1, c2 = st.columns(2)
    requested_intent = None
    with c1:
        if st.button(
            "Current medical situation",
            type="primary",
            use_container_width=True,
            help=QUESTION_BY_INTENT[ClinicalEvidenceIntent.CURRENT_STATE],
        ):
            requested_intent = ClinicalEvidenceIntent.CURRENT_STATE
    with c2:
        if st.button(
            "Patient trajectory",
            use_container_width=True,
            help=QUESTION_BY_INTENT[ClinicalEvidenceIntent.TRAJECTORY],
        ):
            requested_intent = ClinicalEvidenceIntent.TRAJECTORY

    state_key = f"answer::{patient_id}"
    if requested_intent is not None:
        with st.spinner("Building evidence and synthesizing the answer..."):
            try:
                answer = service.answer(patient_id=patient_id, intent=requested_intent)
                st.session_state[state_key] = (requested_intent, answer)
            except Exception as exc:
                st.error("The answer could not be generated.")
                with st.expander("Technical details"):
                    st.exception(exc)
                return

    stored = st.session_state.get(state_key)
    if stored is None:
        st.divider()
        st.caption("Choose one of the two supported questions to generate an evidence-grounded answer.")
        return

    intent, answer = stored
    st.divider()
    st.caption(QUESTION_BY_INTENT[intent])
    _render_synthesis(answer.synthesis)

    with st.expander("Supporting deterministic evidence", expanded=False):
        _render_evidence(answer.evidence_bundle)

    with st.expander("How this answer was produced", expanded=False):
        st.write(
            "Core evidence and numeric candidates were computed deterministically. "
            "One constrained synthesis call was permitted on a cache miss."
        )
        m1, m2, m3 = st.columns(3)
        m1.metric("Model", answer.model_name)
        m2.metric("Reasoning", answer.reasoning_effort)
        m3.metric("Cache", "Hit" if answer.cache_hit else "Miss")
        st.caption(f"Elapsed time: {answer.elapsed_seconds:.2f} seconds")
        with st.expander("Selected numeric candidates"):
            st.json(answer.numeric_selection)


if __name__ == "__main__":
    main()
