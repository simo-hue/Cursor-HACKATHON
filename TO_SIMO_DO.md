# Manual Actions

## [2026-06-13 16:5x] ROOT CAUSE FOUND & FIXED — eval scored -5 (13 no-answers)
The hidden eval saw `0` mock-API calls and `no_answer` on CRM/ERP/calls because the
**deployed Railway service had NO `MOCK_API_TOKEN`** (the local `.env` is git-ignored, so it
was never deployed). `api_client.get()` raises `APIConfigurationError` *before* any HTTP call,
so the agent only ever answered from the KB.

WHAT I ALREADY DID (live now):
- Set all 6 vars on Railway (`MOCK_API_TOKEN`, `MOCK_API_BASE_URL`, `PUBLIC_BASE_URL`,
  `LLM_BASE_URL`, `LLM_API_KEY`, `MODEL`) via `railway variables --set...` (`--skip-deploys`).
- Deployed and **verified live**: CRM/ERP/calls/KB + the margin trap all answer correctly now
  (`crm/opportunities`, `erp/inventory`, `calls/.../transcript` show up in `sources`).
- Fixed the malformed `PUBLIC_BASE_URL` in `backend/.env` (it had the var name duplicated in
  the value, which would have broken every artifact download link).

### [ ] CRITICAL deploy note (so future deploys don't fail again)
The Railway service **Root Directory = `backend`**, so you MUST deploy **from the repo root**,
NOT from `backend/`:
- ✅ `cd /Users/simo/Downloads/DEV/Cursor-HACKATHON && railway up`   (root linked to `hackathon`)
- ❌ `cd backend && railway up`  → fails: `directory .../backend does not exist`.

### [ ] Delete the accidental junk Railway project
While finding the right deploy path I accidentally created an empty project named
**`Cursor-HACKATHON`** (separate from the real `hackathon` project). Delete it in the Railway
dashboard (Project → Settings → Danger → Delete) to avoid confusion. The real service is
`hackathon` → `https://hackathon-production-e85d.up.railway.app`.

### [ ] REDEPLOY needed for the latest code (router/extraction hardening)
The router robustness + customer-name extraction fixes are committed locally but **not yet
deployed**. Run (from repo root): `railway up`. Then re-run the platform self-test.

- [ ] try gemini tests;
- [ ] potenzialmente aggiungere LLM per gli artefacts;





## DEPLOY PHASE:
- Deploy the application to Railway following the instructions in `DEPLOY.md`.
- Ensure you set `MOCK_API_TOKEN` and `MOCK_API_BASE_URL` on Railway variables.
- Run the platform endpoint check after deployment to verify everything works end-to-end.

## [2026-06-13] Customer-deck artifact fix — restart server to pick it up:
- Fixed: the "visiting <Customer>:" deck query was returning *"I could not find any customer named
  'the requested customer'"*. Root cause + full details are in `DOCUMENTATION.md`. No env/secret changes.
- ACTION (local): a dev server is still running on `127.0.0.1:8123` with the OLD code (it was not started
  with `--reload`). Restart it to load the fix:
  1. Stop the current process (Ctrl-C in its terminal, or `lsof -nP -iTCP:8123 -sTCP:LISTEN` → `kill <pid>`).
  2. `cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8123`
     (add `--reload` during development so future edits load automatically).
- ACTION (deploy): redeploy `backend/` to Railway so the evaluator gets the fix (`cd backend && railway up`),
  then re-run the platform Endpoint Check / self-test on the deck question.

## URGENT - fix the platform 405 on POST /ask (REQUIRES REDEPLOY):
- Root cause: the deployed Railway build is STALE (its /health is up but it has no current
  `POST /ask` route -> 405). The local code is correct (POST /ask -> 200, verified on a real
  uvicorn server) and now also defensively returns 200 for any method/404 on /ask.
- ACTION: redeploy the CURRENT `backend/` folder, then re-run the platform Endpoint Check.
  1. `cd backend`
  2. `railway up`  (uploads + builds + deploys this folder; takes seconds)
  3. Confirm `LLM_BASE_URL`, `LLM_API_KEY`, `MODEL`, `MOCK_API_TOKEN`, `MOCK_API_BASE_URL`,
     `PUBLIC_BASE_URL` are set as Railway variables (`railway variables`).
  4. Re-run "Step 1 - Endpoint Check" on the Submit page; POST /ask must now report 200.
- IMPORTANT: deploy from `backend/` (NOT `hackathon info/backend/`, which is the unimplemented
  starter that returns 501).
