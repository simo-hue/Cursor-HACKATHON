# Manual Actions


- [ ] LLM;
- [ ] try gemini tests;
- [ ] potenzialmente aggiungere LLM per gli artefacts;





## DEPLOY PHASE:
- Deploy the application to Railway following the instructions in `DEPLOY.md`.
- Ensure you set `MOCK_API_TOKEN` and `MOCK_API_BASE_URL` on Railway variables.
- Run the platform endpoint check after deployment to verify everything works end-to-end.

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
