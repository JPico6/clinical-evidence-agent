"""Deterministic, model-facing evidence API.

This module is the boundary between validated evidence builders and the future
agent layer.  It intentionally contains no LLM, LangChain, or LangGraph logic.
The eventual agent tools should be thin adapters over :class:`EvidenceToolset`
so that orchestration cannot silently change clinical evidence semantics.
"""

from dataclasses import asdict, dataclass
from typing import Any

from clinical_evidence_agent import database


TOOL_CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class EvidenceToolContract:
    """Stable metadata describing one deterministic evidence capability."""

    name: str
    purpose: str
    parameters: tuple[str, ...]
    returns: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


EVIDENCE_TOOL_CONTRACTS: dict[str, EvidenceToolContract] = {
    "get_utilization_evidence": EvidenceToolContract(
        name="get_utilization_evidence",
        purpose=(
            "Compare patient encounter utilization across adjacent prior and "
            "recent patient-relative periods."
        ),
        parameters=("patient_id",),
        returns=(
            "Deterministic encounter counts, period totals, absolute changes, "
            "and evidence-sufficiency classification."
        ),
        limitations=(
            "Utilization arithmetic does not establish clinical improvement or worsening.",
            "Encounter counts do not establish severity, need, or appropriateness of care.",
            "Periods are anchored to the patient's latest observed event, not wall-clock time.",
        ),
    ),
    "get_lab_evidence": EvidenceToolContract(
        name="get_lab_evidence",
        purpose=(
            "Compare a specified numeric laboratory code across adjacent prior "
            "and recent patient-relative periods."
        ),
        parameters=("patient_id", "code", "unit"),
        returns=(
            "Deterministic summary statistics, change measures, unit handling, "
            "and evidence-sufficiency classification for one lab code."
        ),
        limitations=(
            "The caller must specify the laboratory code; this tool does not infer a code from a lab name.",
            "Multiple units are not silently combined.",
            "Same-code same-encounter multiple values may have unresolved provenance and are not silently collapsed into a clinical interpretation.",
            "Numeric change does not by itself establish clinical improvement or worsening.",
        ),
    ),
    "get_condition_evidence": EvidenceToolContract(
        name="get_condition_evidence",
        purpose=(
            "Summarize recorded condition episodes and identify condition "
            "concepts first observed within a patient-relative lookback."
        ),
        parameters=("patient_id", "lookback_days"),
        returns=(
            "Condition concept summaries plus newly observed condition concepts."
        ),
        limitations=(
            "A missing source STOP is represented as source-open and does not mean clinically active.",
            "Repeated condition rows are preserved as source-recorded episodes rather than assumed duplicates.",
            "First observed in the available data does not prove true clinical onset.",
        ),
    ),
    "get_medication_evidence": EvidenceToolContract(
        name="get_medication_evidence",
        purpose=(
            "Summarize source-recorded medication courses and identify newly "
            "observed or recurring recent medication patterns."
        ),
        parameters=("patient_id", "lookback_days"),
        returns=(
            "Medication concept summaries, deterministic course unions, newly "
            "observed medications, subsequent-course patterns, and source-open evidence."
        ),
        limitations=(
            "Medication records do not establish adherence, ingestion, persistence, or current use.",
            "A missing source STOP does not mean the medication is currently active.",
            "Source reasons are preserved as source attribution and are not asserted clinical indications.",
            "A course after a known gap is a source-course relationship, not proof of an intentional restart.",
        ),
    ),
    "get_procedure_evidence": EvidenceToolContract(
        name="get_procedure_evidence",
        purpose=(
            "Summarize source-recorded procedure events, recurring recent "
            "procedure patterns, and encounter-grouped procedure context."
        ),
        parameters=("patient_id", "lookback_days"),
        returns=(
            "Procedure concept summaries, newly observed procedures, recent "
            "patterns, and encounter-grouped event provenance."
        ),
        limitations=(
            "Repeated procedure rows are source-recorded events and are not automatically deduplicated.",
            "Frequency does not establish clinical importance.",
            "Source reasons are preserved as source attribution and are not asserted clinical indications.",
            "Encounter grouping preserves source encounter linkage even when procedure timestamps occur days after encounter start.",
        ),
    ),
    "get_recent_event_evidence": EvidenceToolContract(
        name="get_recent_event_evidence",
        purpose=(
            "Group recent first-observed condition, medication, and procedure "
            "signals by exact date to expose cross-domain event candidates."
        ),
        parameters=("patient_id", "lookback_days"),
        returns=(
            "Date-grouped event candidates with domain counts, signal counts, "
            "and provenance-preserving underlying signals."
        ),
        limitations=(
            "Same-day grouping is organizational evidence and does not establish causality.",
            "Multi-domain does not mean clinically important.",
            "Single-domain does not mean clinically unimportant.",
            "Longitudinal trends such as lab change, utilization change, and recurring procedure frequency remain in their native evidence domains.",
        ),
    ),
}


class EvidenceToolset:
    """Connection-bound deterministic evidence interface for future agent tools."""

    def __init__(self, con):
        self._con = con

    @property
    def contract_version(self) -> str:
        return TOOL_CONTRACT_VERSION

    def list_contracts(self) -> list[dict[str, Any]]:
        """Return model/tool metadata in deterministic name order."""
        return [
            EVIDENCE_TOOL_CONTRACTS[name].to_dict()
            for name in sorted(EVIDENCE_TOOL_CONTRACTS)
        ]

    def get_contract(self, name: str) -> dict[str, Any]:
        if name not in EVIDENCE_TOOL_CONTRACTS:
            raise KeyError(f"Unknown evidence tool: {name}")
        return EVIDENCE_TOOL_CONTRACTS[name].to_dict()

    @staticmethod
    def _validate_patient_id(patient_id: str) -> str:
        if not isinstance(patient_id, str) or not patient_id.strip():
            raise ValueError("patient_id must be a non-empty string")
        return patient_id.strip()

    @staticmethod
    def _validate_lookback_days(lookback_days: int) -> int:
        if isinstance(lookback_days, bool) or not isinstance(lookback_days, int):
            raise ValueError("lookback_days must be a positive integer")
        if lookback_days <= 0:
            raise ValueError("lookback_days must be a positive integer")
        return lookback_days

    @staticmethod
    def _validate_code(code: str) -> str:
        if not isinstance(code, str) or not code.strip():
            raise ValueError("code must be a non-empty string")
        return code.strip()

    @staticmethod
    def _validate_unit(unit: str | None) -> str | None:
        if unit is None:
            return None
        if not isinstance(unit, str) or not unit.strip():
            raise ValueError("unit must be None or a non-empty string")
        return unit.strip()

    def _patient_has_observed_data(self, patient_id: str) -> bool:
        return database.get_patient_latest_date(self._con, patient_id) is not None

    @staticmethod
    def _no_data(patient_id: str, **extra: Any) -> dict[str, Any]:
        return {
            "status": "no_data",
            "patient_id": patient_id,
            **extra,
        }

    def get_utilization_evidence(self, patient_id: str) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id)
        return database.build_utilization_evidence(self._con, patient_id)

    def get_lab_evidence(
        self,
        patient_id: str,
        code: str,
        unit: str | None = None,
    ) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        code = self._validate_code(code)
        unit = self._validate_unit(unit)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id, code=code)
        return database.build_lab_evidence(
            self._con,
            patient_id,
            code,
            unit=unit,
        )

    def get_condition_evidence(
        self,
        patient_id: str,
        lookback_days: int = 365,
    ) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        lookback_days = self._validate_lookback_days(lookback_days)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id)
        return database.build_condition_evidence(
            self._con,
            patient_id,
            lookback_days=lookback_days,
        )

    def get_medication_evidence(
        self,
        patient_id: str,
        lookback_days: int = 365,
    ) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        lookback_days = self._validate_lookback_days(lookback_days)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id)
        return database.build_medication_evidence(
            self._con,
            patient_id,
            lookback_days=lookback_days,
        )

    def get_procedure_evidence(
        self,
        patient_id: str,
        lookback_days: int = 365,
    ) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        lookback_days = self._validate_lookback_days(lookback_days)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id)
        return database.build_procedure_evidence(
            self._con,
            patient_id,
            lookback_days=lookback_days,
        )

    def get_recent_event_evidence(
        self,
        patient_id: str,
        lookback_days: int = 365,
    ) -> dict[str, Any]:
        patient_id = self._validate_patient_id(patient_id)
        lookback_days = self._validate_lookback_days(lookback_days)
        if not self._patient_has_observed_data(patient_id):
            return self._no_data(patient_id)
        return database.build_recent_event_evidence(
            self._con,
            patient_id,
            lookback_days=lookback_days,
        )
