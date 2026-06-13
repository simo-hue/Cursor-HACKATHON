# Al Dente Company Brain

## Local run

```bash
cp .env.example .env
# Fill the environment values listed below.
uv sync
uv run uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000`.

## Validation

```bash
uv run python scripts/smoke_test.py
uv run python scripts/run_samples.py --base-url http://localhost:8000
```

The smoke suite runs KB, artifact, schema, UI, and graph checks without credentials.
API-dependent checks are skipped until `MOCK_API_TOKEN` is configured.

Run the offline contract and pagination regressions with:

```bash
uv run python -m unittest discover -s tests -v
```

## Environment

```env
LLM_BASE_URL=https://api.regolo.ai/v1
LLM_API_KEY=
MODEL=
MOCK_API_BASE_URL=https://aldente.yellowtest.it
MOCK_API_TOKEN=
PUBLIC_BASE_URL=http://localhost:8000
```

The legacy event variable names `ALDENTE_API_BASE_URL` and `ALDENTE_API_KEY`
are accepted as fallbacks, but the documented `MOCK_API_*` names are preferred.

The deterministic evaluator paths do not require the LLM. The LLM is used only to
classify otherwise ambiguous requests.

## Railway

Deploy the `backend/` directory as one service:

```bash
railway init
railway up
railway variables --set LLM_BASE_URL=... --set LLM_API_KEY=... --set MODEL=... \
  --set MOCK_API_BASE_URL=https://aldente.yellowtest.it --set MOCK_API_TOKEN=...
railway domain
railway variables --set PUBLIC_BASE_URL=https://<generated-domain>
```

Then run the platform endpoint check and the sample runner against the public URL.

Do not include `.env` or the local `ADDITIONAL INFO ( to check everything is coherent )/`
reference export in a submission archive; that export may contain participant credentials.
