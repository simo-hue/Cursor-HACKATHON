# Deploy guide - Railway (one service)

> Step-by-step guide to deploy your company brain to Railway. **You can ask Cursor to do all of this for you** - paste the prompt at the bottom of this file into the chat.
> A Yellow Tech mentor team is in the room throughout the event for any deploy issue.
> **Don't leave the deploy for the last hour.** Plan your first deploy around hour 3, even if `/ask` still returns 501.

## No GitHub needed

The deploy is **direct from your local machine via the Railway CLI**. No GitHub account, no git remote, no public repo: `railway up` uploads your local folder straight to Railway, which builds and deploys it.

## One service, no Dockerfile

You deploy **one Railway service**: the FastAPI backend in `backend/`. It serves everything - `/ask` for the evaluator, the minimal UI at `/`, and your generated artifacts at `/files/`. No frontend service, no CORS, no build-time URL wiring.

Railway builds with **Railpack**: it detects the Python project from `pyproject.toml` + `uv.lock` and uses the `railway.json` already in `backend/`. You don't write a Dockerfile.

## 1. Create a free Railway account

Sign up at https://railway.com with your email. You get **$5 of free credit** on signup - no credit card, no payment method. That's plenty for the whole event.

**Right after signup**: avatar (top-right) -> **Account Settings** -> **Default Region** -> select **EU West Metal (Amsterdam)**. The event runs in Europe: EU region = lower latency against the 30s budget. Do this BEFORE creating the project.

## 2. Install the Railway CLI

**macOS / Linux:**

```bash
npm install -g @railway/cli
# or: brew install railway
```

**Windows**: see the [appendix](#appendix-railway-cli-on-windows) at the bottom (PowerShell, step by step).

Verify: `railway --version`.

## 3. Log in

```bash
railway login
```

Opens the browser for auth.

### Optional: Railway MCP server in Cursor

Railway also ships an MCP server, so Cursor's agent can drive Railway through native tools instead of shell commands. Entirely optional - everything in this guide works with the CLI alone, and the CLI flow is the one we battle-tested.

With the CLI installed and logged in (steps 2-3), run:

```bash
railway setup agent
```

It configures your editor in one step (`railway mcp install` is the variant that merges Railway into an existing MCP config). Then check Cursor Settings -> MCP to see the Railway server listed. The local server exposes, among others: `deploy`, `list-variables` / `set-variables`, `generate-domain`, `get-logs`, plus project/service/environment linking - i.e. steps 4-7 of this guide as agent tools. Destructive operations are intentionally excluded from the local server.

There is also a remote variant (`railway setup agent --remote`, endpoint `mcp.railway.com`) that needs no local CLI - but since you need the CLI anyway for `railway up`-style fallbacks, the local one is the natural choice here.

Full reference: https://docs.railway.com/reference/mcp-server

## 4. Create the project and deploy

```bash
cd backend/
railway init        # pick a name, e.g. company-brain-yourname
railway up          # uploads, builds (Railpack), deploys
```

> **Service naming**: the first service inherits the project name. Unique names get clean domains; generic names (`backend`) get a random suffix. Either works.

> **`--detach` warning**: plain `railway up` (foreground, live build logs) keeps the CLI linked to the service. If you use `railway up --detach`, re-link afterwards with `railway service <name>`.

## 5. Set the environment variables

Same vars as your local `backend/.env` (the `.env` itself is never uploaded):

```bash
railway variables \
  --set LLM_BASE_URL=https://api.regolo.ai/v1 \
  --set LLM_API_KEY=<your-key> \
  --set MODEL=<your-model-id> \
  --set MOCK_API_BASE_URL=https://aldente.yellowtest.it \
  --set MOCK_API_TOKEN=<your-token-from-the-platform-dashboard>
```

Or via dashboard: service -> **Variables** -> New Variable. Changing a variable triggers a redeploy.

## 6. Generate the public URL

```bash
railway domain
```

Copy the URL (e.g. `https://company-brain-yourname-production.up.railway.app`). Two things to do with it:

1. **This is the URL you submit** on the platform - the evaluator hits `<url>/ask`.
2. Set it as `PUBLIC_BASE_URL` so your binary artifacts get working links:

```bash
railway variables --set PUBLIC_BASE_URL=https://<your-url>
```

## 7. Smoke test

```bash
curl https://<your-url>/health
# {"status":"ok"}

curl -X POST https://<your-url>/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"test"}'
# 501 until you implement /ask - that's fine for the first deploy
```

Then run the **endpoint check** from the platform dashboard: it validates the full `/ask` contract (schema, no-auth, no streaming, latency) before you submit.

Once the service exists, every later deploy is just `railway up` from `backend/` - it takes seconds. Redeploy often.

## Useful CLI commands

```bash
railway whoami                       # which account is logged in
railway status                       # project + linked service
railway list                         # your projects
railway logs                         # runtime logs of the linked service
railway logs --build                 # build logs (when the deploy fails)
railway variables                    # list env vars
railway domain                       # print (or create) the public URL
```

## Common issues

| Issue | Fix |
| --- | --- |
| `railway: command not found` | `npm install -g @railway/cli` (Windows: see appendix) |
| `No service could be found` | The CLI lost the link (usually after `--detach`). `railway service <name>`. |
| Build fails | `railway logs --build`. Most often a typo in `pyproject.toml` deps. |
| Healthcheck failing | `GET /health` must return `{"status":"ok"}` (already in the template). If you do heavy work at startup (building an index), do it lazily or pre-build locally - the healthcheck times out otherwise. |
| `/ask` works locally, 401/500 on Railway | An env var is missing on the service: `railway variables` and compare with your local `.env`. |
| Artifact links point to localhost | You forgot `PUBLIC_BASE_URL` (step 6). |
| Upload huge (>100MB) or stalls | A `venv/` or `env/` folder (no leading dot) is being uploaded. Rename your virtualenv to `.venv` (auto-excluded). |
| Service deployed in US | `railway scale --service <name> --europe-west4=1` moves it to EU. Set the default region for next time. |
| First request slow after deploy | Cold start. Warm up with a couple of `/health` + easy `/ask` calls right after deploying. |

## Submission

Submit the **backend public URL** on the event platform (that's what the evaluator hits), plus your repo and the short description. If the URL is unreachable when the evaluation starts, every question scores zero-or-worse: deploy early, test, keep it up.

---

## Cursor prompt - let the agent handle it

Paste this into Cursor when you're ready to deploy:

```
Deploy this project to Railway as a single service. If the Railway MCP
server is configured in this workspace, prefer its tools (deploy,
set-variables, generate-domain, get-logs); otherwise use the CLI. Steps:

1. Verify the Railway CLI is installed (`railway --version`). If not,
   tell me how to install it for my OS (DEPLOY.md has a Windows appendix).

2. Run `railway login` and wait for me to confirm the browser auth.

3. BEFORE creating the project, tell me to set my Account default region
   to "EU West Metal (Amsterdam)" in railway.com -> Account Settings ->
   Default Region. Wait for me to confirm.

4. cd into backend/, run `railway init` (project name like
   "company-brain-mine"), then `railway up`. Railway builds with
   Railpack from pyproject.toml + railway.json - no Dockerfile.

5. Ask me for my LLM provider key and my mock-API token (from the
   platform dashboard), then set the variables:
   railway variables --set LLM_BASE_URL=... --set LLM_API_KEY=... \
     --set MODEL=... --set MOCK_API_BASE_URL=https://aldente.yellowtest.it \
     --set MOCK_API_TOKEN=...

6. Run `railway domain`, save the public URL, and set
   railway variables --set PUBLIC_BASE_URL=https://<that-url>

7. Smoke test:
   curl https://<url>/health           -> {"status":"ok"}
   curl -X POST https://<url>/ask -H 'Content-Type: application/json' \
     -d '{"question":"test"}'          -> 501 if /ask is not implemented yet

8. If anything errors, check `railway logs --build` and `railway logs`,
   and explain the issue in plain language.

9. Report the public URL back to me - it's what I submit on the platform.
```

---

## Appendix: Railway CLI on Windows

All commands in **PowerShell as Administrator** (Start menu -> search "PowerShell" -> right-click -> *Run as administrator*).

```powershell
# 1. Allow script execution (needed for npm-installed CLIs)
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
#    If a later step still complains about scripts being disabled:
#    Set-ExecutionPolicy Unrestricted -Scope LocalMachine -Force

# 2. Install Chocolatey (package manager)
powershell -c "irm https://community.chocolatey.org/install.ps1 | iex"

# 3. Install Node.js
choco install nodejs-lts -y

# 4. IMPORTANT: close and reopen PowerShell (as Administrator)
#    to reload PATH, then verify:
node -v
npm -v

# 5. Install and verify the Railway CLI
npm install -g @railway/cli
railway --version

# 6. Log in (opens the browser)
railway login
```

If `railway` is still not recognized after step 5, close and reopen the terminal once more (PATH refresh).
