"""Community Cloud entrypoint for the Clinical Evidence Agent."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if not os.getenv("OPENAI_API_KEY"):
    try:
        key = st.secrets.get("OPENAI_API_KEY")
    except Exception:
        key = None
    if key:
        os.environ["OPENAI_API_KEY"] = key

# Local development continues to default to data/synthea. A checked-in
# curated public demo dataset is selected automatically when present.
public_demo = ROOT / "data" / "public_demo"
if not os.getenv("CLINICAL_EVIDENCE_DATA_DIR") and public_demo.exists():
    os.environ["CLINICAL_EVIDENCE_DATA_DIR"] = str(public_demo)

from clinical_evidence_agent.streamlit_app import main

if __name__ == "__main__":
    main()
