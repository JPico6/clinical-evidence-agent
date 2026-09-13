
## Run the Streamlit demo

With the Synthea CSV files available in the project's local `data/` directory
and `OPENAI_API_KEY` configured:

```powershell
uv run streamlit run src/clinical_evidence_agent/streamlit_app.py
```

The demo supports two evidence-grounded questions: the patient's current
medical situation and the patient's trajectory. Browsing patients is
deterministic and free of LLM calls; an uncached answer uses at most one
constrained synthesis call.
