# Al Dente Company Brain - Starter

Starter project for the Coding Agent Hackathon powered by Cursor. Build the **company brain** of Al Dente S.r.l.: an agent that answers questions about the company by orchestrating its CRM / ERP / call-log APIs and a knowledge base you build.

> **Read `BRIEF.md` first** (the challenge, evaluation, rules). Then **`AGENTS.md`** (full technical spec - Cursor reads it automatically as project context). `API.md` documents the company APIs; `SAMPLE_QUESTIONS.md` shows what the evaluator asks.
> For deployment read `DEPLOY.md`; for the Docker fallback read `DOCKER.md`. This README is only setup and quick start.

## Prerequisites

- **Cursor** with the event coupon redeemed
- **Railway account** (free, https://railway.com) + **Railway CLI** - see `DEPLOY.md`
- **Python 3.12+ and [uv](https://docs.astral.sh/uv/)** (`curl -LsSf https://astral.sh/uv/install.sh | sh`) - or **Docker Desktop** as fallback (`DOCKER.md`)
- An **LLM provider key** (Regolo.ai or Mistral free tier - see `BRIEF.md`)
- Your **mock-API token** from the event platform dashboard

## Quick start (native - recommended)

```bash
cd backend/
cp .env.example .env        # then fill in your keys and token
uv sync
uv run uvicorn main:app --reload --port 8000
```

Open http://localhost:8000 - a placeholder page (your minimal UI replaces it). API docs at http://localhost:8000/docs. `/ask` returns 501: implementing it is the challenge.

**Fallback with Docker**: `docker compose -f docker-compose.dev.yml up -d` from the starter root (see `DOCKER.md`).

## Working with Cursor

Open this folder in Cursor. The project rules (`.cursor/rules/` + `AGENTS.md`) are picked up automatically. Kickoff prompt for your first message:

```
Read AGENTS.md and API.md fully, confirm the constraints (frozen /ask
schema with artifact_url, 30s latency cap, verticali crm/erp/calls/kb,
honest abstention on traps, efficiency measured server-side).

Then implement POST /ask in backend/main.py as an agent loop:
- tools for the Al Dente APIs (use MOCK_API_TOKEN from .env, handle
  pagination: check pagination.total, don't aggregate a single page)
- a retrieval tool over backend/data/kb/ (documents are small - whole-doc
  retrieval is a fine start)
- routing: set "verticale" to the dominant source of the answer
- arithmetic in code, not in the prompt
- LLM via the OpenAI SDK with LLM_BASE_URL/LLM_API_KEY/MODEL from .env

Smoke-test against a sample question from SAMPLE_QUESTIONS.md and compare
with the reference answer.
```

Common things to ask Cursor: *"start the dev server"*, *"test /ask with sample question 3"*, *"tail the logs"*, *"deploy to Railway"* (it follows `DEPLOY.md`).

## Project layout

```
.
├── BRIEF.md                 # The challenge - read first
├── AGENTS.md                # Full technical spec (Cursor context)
├── API.md                   # Al Dente mock API reference
├── SAMPLE_QUESTIONS.md      # 12 public questions WITH answers
├── DEPLOY.md                # Railway deploy, step by step + Cursor prompt
├── DOCKER.md                # Docker fallback dev environment
├── docker-compose.dev.yml   # (fallback) dev container
├── Dockerfile.dev           # (fallback) dev image - NOT used by Railway
├── .cursor/rules/           # Cursor project rules
└── backend/                 # Everything you deploy
    ├── main.py              # FastAPI app - /ask is yours to implement
    ├── pyproject.toml       # deps (uv); RAG/artifact libs commented
    ├── railway.json         # Railway config (Railpack, no Dockerfile)
    ├── .env.example         # template for your keys
    ├── static/index.html    # placeholder - YOUR minimal UI goes here (required, not graded)
    ├── static/files/        # generated binary artifacts, served at /files/
    └── data/kb/             # 35 company documents - build your RAG here
```

## Constraints recap (details in `AGENTS.md`)

- `POST /ask`: `{"question"}` -> `{"answer", "sources", "verticale", "artifact_url"?}`. Frozen, public, no auth, no streaming, HTTP 200 always.
- **30 seconds** max per question.
- Only the provided sources (APIs + `data/kb/`). Never invent data - traps exist, honesty wins.
- Efficiency is measured **server-side** via your API token: targeted calls beat bulk downloads.
- Never commit `.env`.

## Submission

On the event platform, by **17:00**:

- Your **backend public URL** (Railway) - the evaluator hits `<url>/ask`
- Your **repo** (zip) and a short description of your approach (~200 words)

If the URL is down at evaluation time, Level 1 scores collapse. **Deploy around hour 3** (`DEPLOY.md`), run the platform endpoint check, keep it up.

## Troubleshooting

- **`uv: command not found`**: install uv (link above) or use the Docker fallback.
- **`/ask` returns 501**: expected - you haven't implemented it yet.
- **401 from the Al Dente APIs**: `MOCK_API_TOKEN` missing/wrong in `.env` - copy it from the platform dashboard.
- **LLM 401/404**: check `LLM_BASE_URL`, `LLM_API_KEY` and `MODEL` (Regolo ids are case-sensitive).
- **Deploy issues**: `DEPLOY.md` -> Common issues, or ask a Yellow Tech mentor in the room.
