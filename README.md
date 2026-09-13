# Clinical Evidence Agent

## Portfolio shipping configuration

The interactive application uses a cost-conscious path that is intentionally
different from the high-quality evaluation benchmark.

- Patient browsing and deterministic evidence retrieval do **not** invoke an LLM.
- Numeric observation candidates are selected deterministically.
- Each uncached `current_state` or `trajectory` request uses at most **one**
  constrained synthesis call.
- Repeated requests are cached by patient, patient-relative anchor, intent, and
  synthesis configuration.
- Live defaults are `gpt-5.6-luna` with `low` reasoning effort. Override them
  with `CLINICAL_EVIDENCE_MODEL` and `CLINICAL_EVIDENCE_REASONING_EFFORT`.
- The completed Sol/medium multi-patient evaluation remains the frozen
  quality-oriented benchmark; it is not the default live configuration.

This project uses synthetic Synthea data only and is a portfolio engineering
exercise. It is not intended for real patient information, clinical care, or
clinical decision-making.

