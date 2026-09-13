# Streamlit Community Cloud deployment

## 1. Validate locally

From the repository root:

```powershell
uv run pytest -q
uv run python scripts/build_public_demo_data.py
uv run streamlit run streamlit_app.py
```

Confirm both supported questions work for at least one synthetic patient.

## 2. Audit before GitHub

Confirm these are **not** committed:

- `.env`
- `.streamlit/secrets.toml`
- the full local `data/synthea/` export
- `evaluation_runs/multipatient_evaluation.json`
- `evaluation_runs/multipatient_smoke.json`
- `__pycache__/`, `.venv/`, IDE metadata

The curated `data/public_demo/*.csv` files are synthetic and are intended to
be committed for the public demo.

## 3. Push to GitHub

Create a repository and commit the code, tests, compact review artifacts,
and `data/public_demo/`.

## 4. Deploy in Streamlit Community Cloud

Create a new app from the GitHub repository and choose:

- branch: your main branch
- entrypoint: `streamlit_app.py`

In **Advanced settings -> Secrets**, add:

```toml
OPENAI_API_KEY = "your-real-key"
```

Never commit that value.

The root entrypoint adds `src/` to Python's import path and automatically
uses `data/public_demo/` when that directory is present.

## 5. Smoke-test the public URL

Verify:

- patient browsing works without an LLM call;
- current-state synthesis works;
- trajectory synthesis works;
- evidence references expand correctly;
- no secret or local path is visible;
- the synthetic/not-for-clinical-care warning is visible.

Then add the resulting `https://...streamlit.app` URL to the README.

## Public cost note

The live path permits one constrained synthesis call for an uncached
supported question and zero calls for ordinary patient browsing. Caching
reduces repeated calls within the running app process, but it is not a
durable cross-restart cost control.

If public traffic becomes meaningful, add stronger server-side rate limiting
or take the demo private rather than treating the two-button UI as a security
boundary.
