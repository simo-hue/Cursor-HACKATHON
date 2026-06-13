# AGENTS.md - Company Brain Challenge

> Project spec and rules for AI coding agents (Cursor). Read this fully before any task.
> The participant is a developer: keep answers technical and concise.

## What you must build

The **company brain** of Al Dente S.r.l. - a pasta maker selling to supermarkets (GDO), distributors and restaurants (horeca). An agent that receives a question about the company, decides which data sources it needs, calls them efficiently, and returns an answer or an artifact.

Concretely:

1. **The agent loop** - receives the question, orchestrates tools (the Al Dente APIs + your knowledge base), composes the answer. This is the heart of the challenge.
2. **The knowledge base (RAG)** - you build it over the documents in `backend/data/kb/` (product specs, quality/returns policies, price list, customer requirements). It is one of the agent's tools, next to the APIs.
3. **The public endpoint** - `POST /ask`, frozen schema below. This is what the evaluator hits.
4. **A working UI with a knowledge graph** - you build it (a placeholder page sits at `GET /` - replace `backend/static/index.html` or serve your own frontend). It must work **end-to-end** (a user asks and gets answers without friction) and include a **graph visualization** of the company's materials/knowledge: the network of customers, suppliers, products, raw materials and how they connect. This is a **required, scored** deliverable (Level 2 jury), not an afterthought.

## The 4 verticali

Every question maps to the source that answers it:

1. `crm` - customers, opportunities, orders, invoices
2. `erp` - production lots, inventory, suppliers, bill of materials, shipments
3. `calls` - call logs with full transcripts (complaints, negotiations)
4. `kb` - the documents in `backend/data/kb/`

Multi-source questions exist (e.g. complaint in a call -> returns policy in the KB). For those, pick the **dominant** source as `verticale`.

## Endpoint /ask - frozen schema (DO NOT change the signature)

```python
# Request
{
  "question": str
}

# Response
{
  "answer": str,                 # natural-language answer (or inline HTML/markdown artifact)
  "sources": list[str],          # endpoints / document ids you used, e.g. ["crm/opportunities", "DOC-004"]
  "verticale": str,              # one of: "crm", "erp", "calls", "kb"
  "artifact_url": str | None     # ONLY for docx/pptx/pdf/xlsx questions - absolute URL to the file
}
```

### Hard constraints on `/ask` (non-negotiable)

The evaluator does **one** `POST` and reads **one** JSON response. Any deviation = that question scores as wrong.

- **Path**: exactly `/ask` at the root. Not `/api/ask`, not `/v1/ask`.
- **Method**: `POST` only.
- **Request body**: a single JSON object `{"question": "<string>"}`. No extra required fields, no required headers beyond `Content-Type`.
- **Auth**: `/ask` must be **publicly callable with no authentication**. (The Al Dente APIs require YOUR token; your endpoint must not require one.)
- **Response status**: HTTP `200` for any answer, including "not available". Never signal "no info" with 4xx/5xx.
- **Response body**: a single JSON object with `answer`, `sources`, `verticale` (and `artifact_url` when a file is requested). Extra keys are ignored.
- **No streaming** (no SSE, no NDJSON, no `stream=True` forwarded chunks). The evaluator calls `response.json()` once.
- **No async/job pattern**. The answer must be in the body of the first response.
- **Latency**: full response within **30 seconds** per question.

If you are tempted to "improve" any of the above for security or elegance: don't. The contract is locked because the evaluator is locked.

Use the platform's **endpoint check** (dashboard) to validate your deployed contract before submitting.

## Latency: 30 seconds per question

Responses over 30s score as wrong. A clean agent run takes 4-10s on a fast tool-calling model (p95 ~26s in our tests), so 30s is a real ceiling, not a comfortable one. Treat it as a hard design constraint: cap your loop steps, keep system prompts short, and prefer one targeted API call over five broad ones.

## The Al Dente mock APIs

Full reference in `API.md` (endpoints, filters, pagination). Essentials:

- Base URL: `https://aldente.yellowtest.it` (set via `MOCK_API_BASE_URL`).
- Every call needs `Authorization: Bearer $MOCK_API_TOKEN`. Your personal token is on the **platform dashboard**. Without it: `401 access_denied`.
- All endpoints are **read-only**, JSON, paginated: `{"data": [...], "pagination": {"offset", "limit", "total"}}`. Default `limit=50`, max `200`.
- **Your calls are metered server-side** (count + bytes downloaded, per token). Efficiency is part of the score: targeted, filtered calls beat bulk downloads.

### Watch out: pagination on aggregates

`limit` defaults to 50 and **caps at 200**. If a question asks "how many X / total value of X", check `pagination.total` and page through (or filter server-side) before aggregating. Counting only the first page is the single most common wrong answer in our tests.

### Watch out: transcripts are long

Call transcripts have hundreds of segments. `GET /calls/{id}/transcript?search=...` extracts the relevant part; downloading the full transcript wastes time, tokens and efficiency points.

### Do arithmetic in code, not in the prompt

LLMs sum wrong even with the right addends. For aggregates (totals, counts, group-bys), fetch the rows and compute in Python; hand the model the computed result.

## Knowledge base (`backend/data/kb/`)

35 markdown documents: product spec sheets (shelf life, allergens), quality and returns policies, customer requirements (capitolati), the price list. You build the retrieval over them - any approach works (BM25, embeddings, or both). Note: the documents are small and similar to each other (many near-identical spec sheets). Over-aggressive chunking hurts: retrieving a **whole document** often beats retrieving fragments, and keeps shelf life + allergens together.

The only data sources allowed are these documents and the mock APIs. **No external data, no invented data.**

## Honesty beats hallucination (traps exist)

Some evaluation questions are **traps by design**: they ask about a customer that doesn't exist, or a figure that is not in any source (e.g. profit margins). Inventing an answer scores heavily negative; an honest, specific "this is not available in the sources" scores full marks on a trap. Build the agent to verify premises and to say "not found" with confidence - a generic "I don't know" is worth less than "there is no customer named X in the CRM".

## Artifacts

Generation questions ask for a deliverable, in two flavors:

- **HTML / markdown** (e.g. a 4-slide HTML deck): return it **inline in `answer`**. `artifact_url` stays null.
- **Binary files - docx / pptx / pdf / xlsx** (a few hidden questions, explicit about the format): generate the file, save it under `backend/static/files/`, and return an **absolute** `artifact_url` like `f"{PUBLIC_BASE_URL}/files/report.pdf"`. This backend already serves `/files/` - no external storage. Libraries (`python-docx`, `python-pptx`, `fpdf2`, `openpyxl` for Excel) are commented in `pyproject.toml`.

Either way, the content is judged first on **facts** (the real data must be in there) and on respecting the requested format; visual style is judged by humans later, on the top projects.

After deploying, set `PUBLIC_BASE_URL` to your Railway URL, or your artifact links will point to localhost.

## LLM provider

Runtime models come from **Regolo.ai** or **Mistral** (free tier, OpenAI-compatible - see `BRIEF.md`). Use the OpenAI SDK with a custom base URL:

```python
from openai import OpenAI
client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"])
```

Pick a model that supports **function/tool calling** - not every model on either provider does, and a model that ignores tools will quietly fail the whole agent loop. Don't trust your training data on model names: `GET {LLM_BASE_URL}/models` lists what's live, and choosing well is part of the challenge. Favour a capable instruct model over a tiny one for the agentic loop. **Regolo model ids are case-sensitive.**

Provider gotchas seen in our calibration:

- **Some reasoning models** can return an empty `content` with the text in `reasoning_content`. Handle both, and nudge the model to conclude when it rambles.
- **Mistral free tier is rate-limited (~1 req/s)**. Sequential agent loops are fine; parallel self-test batteries are not.
- On API errors: retry with backoff, then **fall back to HTTP 200 with an honest "I cannot answer right now"** - a 5xx scores worse than an abstention.

## Environment variables

All read from `backend/.env` (copy `backend/.env.example`). On Railway, set them with `railway variables --set` (see `DEPLOY.md`).

| Var | What |
| --- | --- |
| `LLM_BASE_URL` | `https://api.regolo.ai/v1` or `https://api.mistral.ai/v1` |
| `LLM_API_KEY` | your provider key |
| `MODEL` | model id (case-sensitive on Regolo) |
| `MOCK_API_BASE_URL` | `https://aldente.yellowtest.it` |
| `MOCK_API_TOKEN` | your personal token, from the platform dashboard |
| `PUBLIC_BASE_URL` | public URL of this backend (for `artifact_url`) |

**Never commit `.env`** (already git-ignored). **Never hardcode keys.**

## Code conventions

- Code, identifiers, comments, docs: **English**.
- Evaluation questions are in English; answer in English.
- Keep the whole backend in `backend/` - that folder is what gets deployed.

## What is already set up

- `POST /ask` route with the frozen schema (returns 501 until you implement it)
- `/files/` static serving for binary artifacts + `PUBLIC_BASE_URL` pattern
- Placeholder page at `GET /` (replace it with your working UI + knowledge graph)
- `railway.json` for a one-command deploy (no Dockerfile needed - Railpack)
- Fallback Docker dev environment (`DOCKER.md`)
- The KB documents in `backend/data/kb/`

## What you build

- The agent loop and tool definitions (API callers, KB search)
- The retrieval over `data/kb/`
- Routing logic for `verticale`
- Artifact generation (inline HTML + binary files)
- The UI + knowledge-graph visualization (required, graded at L2)
- Prompts, caching, efficiency strategy

## Workflow and pacing (6 hours)

1. **Hour 0-1**: env up (`uv sync`, `.env`, run the backend), first end-to-end answer on one simple CRM question.
2. **Hour 1-2**: cover the 4 verticali; wire the KB retrieval.
3. **Hour 2-3**: **first Railway deploy** (see `DEPLOY.md`), even if rough. Run the platform endpoint check. Surface infra issues with hours of buffer.
4. **Hour 3-5**: iterate with the self-test on the platform: aggregates with pagination, multi-source chains, traps, artifacts. Redeploy after each improvement (`railway up` takes seconds).
5. **Hour 5-6**: final self-test pass, verify artifact URLs work on the deployed app, submit the backend URL + repo + description. **Deadline 17:00.**

The self-test loop on the platform is the fastest way up the leaderboard: run, read the feedback, fix, rerun.

## Going beyond MVP

After the baseline answers all 4 verticali, pick upgrades that change answers the evaluator sees:

- **Pagination-aware aggregation helpers** | the most common failure; deterministic code, big win
- **Premise verification for traps** | check the entity exists before answering
- **Hybrid retrieval (BM25 + embeddings) on the KB** | catches code-exact matches (SKU, lot ids)
- **Query decomposition for multi-source chains** | lot -> SKU -> BOM -> supplier -> stock
- **Caching identical questions** | the self-test repeats; sub-second on repeats
- **Artifact templates** (docx/pptx/pdf/xlsx) | the points that separate the top

Do NOT over-engineer the backend: each agent/RAG upgrade must visibly change an evaluator-facing answer. The UI is the exception - it is a **graded L2 deliverable** (functioning & usability, wow & the knowledge graph, quality of the artifacts), so a working, polished UI with a strong graph view earns real points.
