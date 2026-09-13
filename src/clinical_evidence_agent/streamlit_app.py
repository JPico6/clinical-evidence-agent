"""Streamlit portfolio application for the Clinical Evidence Agent."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

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

EVIDENCE_LABELS = {
    "get_recent_event_evidence": "Recent events",
    "get_utilization_evidence": "Healthcare utilization",
    "get_condition_evidence": "Conditions",
    "get_medication_evidence": "Medications",
    "get_procedure_evidence": "Procedures",
    "get_selected_numeric_observation_evidence": "Measurements & labs",
    "get_lab_evidence": "Measurements & labs",
}


@st.cache_resource
def get_service() -> ClinicalEvidenceApplicationService:
    return ClinicalEvidenceApplicationService()


def _format_date(value: Any) -> str:
    """Return a compact human-readable date without exposing midnight timestamps."""
    if value is None or value == "":
        return "Unknown"

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    parsed: date | datetime | None = None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = date.fromisoformat(text[:10])
            except ValueError:
                return text

    if parsed is None:
        return str(value)

    # Avoid %-d because it is not portable to Windows.
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"


def _gender_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    return {
        "F": "Female",
        "M": "Male",
    }.get(text, str(value or "Unknown"))


def _display_name(patient: dict[str, Any]) -> str:
    first = patient.get("first_name") or ""
    last = patient.get("last_name") or ""
    name = f"{first} {last}".strip() or "Synthetic patient"
    birth = patient.get("birth_date")
    return f"{name} · DOB {_format_date(birth)}" if birth else name


def _synthesis_payload(synthesis: Any) -> dict[str, Any]:
    if hasattr(synthesis, "model_dump"):
        return synthesis.model_dump(mode="json")
    return dict(synthesis)


def _iter_synthesis_findings(payload: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    assessment = payload.get("overall_assessment")
    if isinstance(assessment, Mapping):
        yield dict(assessment)

    items = payload.get("findings")
    if items is None:
        items = payload.get("changes", [])
    for item in items or []:
        if isinstance(item, Mapping):
            yield dict(item)

    for item in payload.get("uncertainties", []) or []:
        if isinstance(item, Mapping):
            yield dict(item)


def _ref_key(ref: Mapping[str, Any]) -> tuple[str, tuple[Any, ...]]:
    return (
        str(ref.get("tool_name", "")),
        tuple(ref.get("path", []) or []),
    )


def _build_reference_index(payload: Mapping[str, Any]) -> dict[tuple[str, tuple[Any, ...]], int]:
    index: dict[tuple[str, tuple[Any, ...]], int] = {}
    for finding in _iter_synthesis_findings(payload):
        for ref in finding.get("evidence_refs", []) or []:
            if not isinstance(ref, Mapping):
                continue
            key = _ref_key(ref)
            if key not in index:
                index[key] = len(index) + 1
    return index


def _citation_suffix(
    finding: Mapping[str, Any],
    reference_index: Mapping[tuple[str, tuple[Any, ...]], int],
) -> str:
    numbers: list[int] = []
    for ref in finding.get("evidence_refs", []) or []:
        if isinstance(ref, Mapping):
            number = reference_index.get(_ref_key(ref))
            if number is not None and number not in numbers:
                numbers.append(number)
    if not numbers:
        return ""
    return " " + " ".join(f"[{number}]" for number in numbers)


def _resolve_path(payload: Any, path: Sequence[Any]) -> Any:
    current = payload
    for part in path:
        if isinstance(part, str):
            if not isinstance(current, Mapping) or part not in current:
                return None
            current = current[part]
        elif isinstance(part, int) and not isinstance(part, bool):
            if (
                not isinstance(current, Sequence)
                or isinstance(current, (str, bytes, bytearray))
                or part < 0
                or part >= len(current)
            ):
                return None
            current = current[part]
        else:
            return None
    return current


def _anchor_date(bundle: Mapping[str, Any]) -> Any | None:
    for payload in (bundle.get("evidence_by_tool") or {}).values():
        if isinstance(payload, Mapping) and payload.get("anchor_date"):
            return payload["anchor_date"]
    return None


def _human_evidence_label(tool_name: str) -> str:
    return EVIDENCE_LABELS.get(
        tool_name,
        tool_name.replace("get_", "").replace("_evidence", "").replace("_", " ").title(),
    )


def _render_synthesis(
    synthesis: Any,
) -> tuple[dict[str, Any], dict[tuple[str, tuple[Any, ...]], int]]:
    payload = _synthesis_payload(synthesis)
    reference_index = _build_reference_index(payload)

    assessment = payload.get("overall_assessment")
    if isinstance(assessment, Mapping):
        statement = assessment.get("statement", "")
        if statement:
            st.markdown(
                f"### {statement}{_citation_suffix(assessment, reference_index)}"
            )
    elif assessment:
        st.markdown(f"### {assessment}")

    items = payload.get("findings")
    if items is None:
        items = payload.get("changes", [])

    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        statement = item.get("statement", "")
        if statement:
            st.markdown(f"- {statement}{_citation_suffix(item, reference_index)}")

    uncertainties = payload.get("uncertainties", [])
    if uncertainties:
        st.markdown("#### Important uncertainties")
        for item in uncertainties:
            if not isinstance(item, Mapping):
                continue
            statement = item.get("statement", "")
            if statement:
                st.markdown(f"- {statement}{_citation_suffix(item, reference_index)}")

    return payload, reference_index


def _render_cited_evidence(
    bundle: Mapping[str, Any],
    reference_index: Mapping[tuple[str, tuple[Any, ...]], int],
) -> None:
    evidence = bundle.get("evidence_by_tool") or {}
    if not reference_index:
        st.info("The synthesis did not contain evidence references.")
        return

    ordered = sorted(reference_index.items(), key=lambda item: item[1])
    for (tool_name, path), number in ordered:
        source_payload = evidence.get(tool_name)
        resolved = _resolve_path(source_payload, path) if source_payload is not None else None
        label = _human_evidence_label(tool_name)
        path_text = " → ".join(str(part) for part in path)

        with st.expander(f"[{number}] {label}", expanded=False):
            st.caption(f"Source path: {path_text}")
            if resolved is None:
                st.warning("The cited evidence location could not be resolved for display.")
            elif isinstance(resolved, (Mapping, list, tuple)):
                st.json(resolved)
            else:
                st.write(resolved)


def _render_raw_evidence(bundle: Mapping[str, Any]) -> None:
    evidence = bundle.get("evidence_by_tool", {})
    if not evidence:
        st.info("No deterministic evidence was returned.")
        return

    for tool_name, payload in evidence.items():
        with st.expander(_human_evidence_label(tool_name), expanded=False):
            st.caption(f"Technical tool: `{tool_name}`")
            st.json(payload)


def main() -> None:
    st.title("Clinical Evidence Agent")
    st.caption(
        "Deterministic longitudinal evidence retrieval with constrained LLM synthesis."
    )
    st.warning(
        "Synthetic Synthea data · Engineering demonstration only · Not for clinical care",
        icon="⚠️",
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

    # Store answers by patient so switching patients does not accidentally display
    # another patient's result.
    state_key = f"answer::{patient_id}"
    stored = st.session_state.get(state_key)
    stored_bundle = stored[1].evidence_bundle if stored is not None else {}
    evidence_through = _anchor_date(stored_bundle)

    first = selected.get("first_name") or ""
    last = selected.get("last_name") or ""
    name = f"{first} {last}".strip() or "Synthetic patient"
    gender = _gender_label(selected.get("gender"))
    dob = _format_date(selected.get("birth_date"))

    with st.container(border=True):
        st.markdown(f"### {name}")
        details = f"**{gender}** · DOB {dob}"
        if evidence_through:
            details += f" · Evidence through **{_format_date(evidence_through)}**"
        st.markdown(details)
        st.caption(f"Synthetic patient ID: {patient_id}")

    st.subheader("Ask about this patient")
    st.write(
        "Patient evidence is computed deterministically first. "
        "The language model receives structured evidence rather than raw longitudinal rows."
    )

    c1, c2 = st.columns(2)
    requested_intent = None
    with c1:
        if st.button(
            "Describe current medical situation",
            type="primary",
            use_container_width=True,
            help=QUESTION_BY_INTENT[ClinicalEvidenceIntent.CURRENT_STATE],
        ):
            requested_intent = ClinicalEvidenceIntent.CURRENT_STATE
    with c2:
        if st.button(
            "Explain patient trajectory",
            use_container_width=True,
            help=QUESTION_BY_INTENT[ClinicalEvidenceIntent.TRAJECTORY],
        ):
            requested_intent = ClinicalEvidenceIntent.TRAJECTORY

    if requested_intent is not None:
        with st.spinner("Building evidence and synthesizing the answer..."):
            try:
                answer = service.answer(patient_id=patient_id, intent=requested_intent)
                st.session_state[state_key] = (requested_intent, answer)
                stored = (requested_intent, answer)
            except Exception as exc:
                st.error("The answer could not be generated.")
                with st.expander("Technical details"):
                    st.exception(exc)
                return

    if stored is None:
        st.divider()
        st.caption(
            "Choose one of the two supported questions to generate an evidence-grounded answer."
        )
        return

    intent, answer = stored
    st.divider()
    st.caption(QUESTION_BY_INTENT[intent])
    _, reference_index = _render_synthesis(answer.synthesis)

    with st.expander("Supporting evidence cited in this answer", expanded=False):
        st.caption(
            "Each numbered reference maps a synthesis statement to a mechanically "
            "validated location in the deterministic evidence bundle."
        )
        _render_cited_evidence(answer.evidence_bundle, reference_index)

    with st.expander("How this answer was produced", expanded=False):
        st.write(
            "Core evidence and numeric candidates were computed deterministically. "
            "On a cache miss, the application permits one constrained synthesis call."
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Model", answer.model_name)
        m2.metric("Reasoning", answer.reasoning_effort)
        m3.metric("Cache", "Hit" if answer.cache_hit else "Miss")
        m4.metric("Elapsed", f"{answer.elapsed_seconds:.1f}s")

    with st.expander("Advanced technical details", expanded=False):
        st.markdown("#### Deterministic evidence bundle")
        _render_raw_evidence(answer.evidence_bundle)
        st.markdown("#### Deterministic numeric candidates")
        st.json(answer.numeric_selection)


if __name__ == "__main__":
    main()
