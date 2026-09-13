"""Deterministic cross-domain recent event evidence."""

from clinical_evidence_agent.data_access import get_patient_latest_date
from clinical_evidence_agent.evidence.conditions import build_condition_evidence
from clinical_evidence_agent.evidence.medications import build_medication_evidence
from clinical_evidence_agent.evidence.procedures import build_procedure_evidence


def get_patient_recent_event_signals(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Normalize recent first-observed evidence into cross-domain event signals.

    This function intentionally uses already-defined domain evidence contracts
    rather than joining raw longitudinal tables. A signal means only that a
    concept was first observed within the patient-relative lookback. It does
    not imply clinical importance, causality, severity, or that co-occurring
    signals are causally related.
    """
    anchor_date = get_patient_latest_date(con, patient_id)
    if anchor_date is None:
        return []

    condition_evidence = build_condition_evidence(
        con,
        patient_id,
        lookback_days=lookback_days,
    )
    medication_evidence = build_medication_evidence(
        con,
        patient_id,
        lookback_days=lookback_days,
    )
    procedure_evidence = build_procedure_evidence(
        con,
        patient_id,
        lookback_days=lookback_days,
    )

    signals = []

    for item in condition_evidence.get("newly_observed_conditions", []):
        signals.append(
            {
                "event_date": item["first_start"],
                "domain": "condition",
                "signal_type": "newly_observed_condition",
                "code": item["code"],
                "description": item["description"],
                "source_reasons": [],
                "source_details": {
                    "episode_count": item["episode_count"],
                },
            }
        )

    for item in medication_evidence.get("newly_observed_medications", []):
        signals.append(
            {
                "event_date": item["first_start"],
                "domain": "medication",
                "signal_type": "newly_observed_medication",
                "code": item["code"],
                "description": item["description"],
                "source_reasons": item["source_reasons"],
                "source_details": {},
            }
        )

    for item in procedure_evidence.get("newly_observed_procedures", []):
        signals.append(
            {
                "event_date": item["first_start"],
                "domain": "procedure",
                "signal_type": "newly_observed_procedure",
                "code": item["code"],
                "description": item["description"],
                "source_reasons": item["source_reasons"],
                "source_details": {
                    "event_count": item["event_count"],
                    "encounter_count": item["encounter_count"],
                },
            }
        )

    signals.sort(
        key=lambda item: (
            item["event_date"] or "",
            item["domain"],
            item["description"],
        ),
        reverse=True,
    )
    return signals

def build_recent_event_evidence(
    con,
    patient_id: str,
    lookback_days: int = 365,
):
    """Group recent first-observed domain signals into date-based candidates.

    Exact-date grouping is a provenance-preserving organizational rule, not a
    causal inference. ``multi_domain`` means two or more evidence domains have
    first-observed signals on the same date; it does not mean those signals
    are clinically related. Longitudinal trends such as lab change,
    utilization change, or recurring procedure frequency remain in their
    native domain evidence and are intentionally not converted into events.
    """
    anchor_date = get_patient_latest_date(con, patient_id)

    if anchor_date is None:
        return {
            "status": "no_data",
            "patient_id": patient_id,
        }

    signals = get_patient_recent_event_signals(
        con,
        patient_id,
        lookback_days=lookback_days,
    )

    grouped = {}
    for signal in signals:
        event_date = signal["event_date"]
        grouped.setdefault(event_date, []).append(signal)

    event_candidates = []
    for event_date, date_signals in grouped.items():
        domains = sorted({item["domain"] for item in date_signals})
        domain_signal_counts = {
            domain: sum(
                1 for item in date_signals if item["domain"] == domain
            )
            for domain in domains
        }

        ordered_signals = sorted(
            date_signals,
            key=lambda item: (
                item["domain"],
                item["description"],
                item["code"],
            ),
        )

        event_candidates.append(
            {
                "event_date": event_date,
                "multi_domain": len(domains) >= 2,
                "domain_count": len(domains),
                "domains": domains,
                "signal_count": len(ordered_signals),
                "domain_signal_counts": domain_signal_counts,
                "signals": ordered_signals,
            }
        )

    event_candidates.sort(
        key=lambda item: (
            item["event_date"] or "",
            item["domain_count"],
            item["signal_count"],
        ),
        reverse=True,
    )

    return {
        "status": "ok",
        "patient_id": patient_id,
        "anchor_date": anchor_date.isoformat(),
        "lookback_days": lookback_days,
        "source_signal_count": len(signals),
        "event_candidate_count": len(event_candidates),
        "multi_domain_event_candidate_count": sum(
            1 for item in event_candidates if item["multi_domain"]
        ),
        "event_candidates": event_candidates,
    }
