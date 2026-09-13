# Public repository audit

## Findings

**Good**
- No real PHI is part of the intended project scope; data is synthetic Synthea.
- `.env` and Streamlit secrets are ignored.
- The live UI is constrained to two supported questions.
- The shipping path uses one synthesis call at most on a cache miss.

**Cleaned / addressed by this patch**
- Root Streamlit entrypoint now adds `src/` explicitly for clean cloud installs.
- Local browser auto-launch is no longer disabled.
- The data directory can be selected with `CLINICAL_EVIDENCE_DATA_DIR`.
- A 10-patient public-demo dataset builder is provided.
- Full local Synthea data is excluded from Git.
- Large raw evaluation JSON files are excluded from Git.
- The README is consolidated; the temporary `README_STREAMLIT_APPEND.md`
  should not be committed.
- Public deployment instructions explicitly cover secrets and data.

**One required action before deployment**
- Run `uv run python scripts/build_public_demo_data.py` locally and confirm
  `data/public_demo/` contains the six required CSVs:
  `patients`, `encounters`, `conditions`, `medications`, `observations`,
  and `procedures`.

## Files that should stay local

- `.env`
- `data/synthea/`
- raw paid-evaluation payloads
- virtual environments, caches, IDE state
- `README_STREAMLIT_APPEND.md` (superseded by README.md)

## Files appropriate for the public repository

- source code
- tests
- curated `data/public_demo/*.csv`
- compact evaluation-review artifacts
- README / deployment documentation
- `.env.example`
