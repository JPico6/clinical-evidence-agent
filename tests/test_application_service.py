from clinical_evidence_agent.application_service import (
    DEFAULT_SHIPPING_MODEL,
    DEFAULT_SHIPPING_REASONING_EFFORT,
)


def test_shipping_defaults_are_cost_conscious():
    assert DEFAULT_SHIPPING_MODEL == "gpt-5.6-luna"
    assert DEFAULT_SHIPPING_REASONING_EFFORT == "low"
