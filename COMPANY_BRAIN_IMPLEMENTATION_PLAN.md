# Al Dente Company Brain — Production Implementation Plan for Coding Agents

> Use this file as the single source of truth for Codex/Cursor/coding agents.
> Goal: implement a robust, production-ready hackathon solution in the existing starter repo within ~5 hours.
> Optimize first for Level 1 automated correctness, then for Level 2 UI/knowledge-graph impact.

---

## 0. Non-negotiable challenge contract

1. Keep the evaluator endpoint exactly:

   ```http
   POST /ask
   Content-Type: application/json

   {"question": "<string>"}
   ```

2. Always return HTTP `200`, including errors, missing data, unsupported questions, or temporary LLM/API failures.

3. Response body must be one JSON object:

   ```json
   {
     "answer": "natural-language answer, or inline markdown/html artifact",
     "sources": ["crm/customers", "DOC-015"],
     "verticale": "crm",
     "artifact_url": null
   }
   ```

4. `verticale` must be one of: `crm`, `erp`, `calls`, `kb`.

5. `artifact_url` is `null` unless the user explicitly asks for a binary file: `pdf`, `xlsx`, `docx`, or `pptx`.

6. No auth on `/ask`. The backend uses `MOCK_API_TOKEN` internally for the Al Dente mock APIs.

7. No streaming, no background jobs, no async polling. The first `/ask` response must contain the final answer.

8. Full response must complete within 30 seconds.

9. Only use the provided sources:
   - Al Dente mock APIs.
   - Local KB markdown files in `backend/data/kb/`.

10. Never invent data. Honest, specific abstention is better than a plausible wrong answer.

11. Never commit `.env`, API tokens, LLM keys, or other secrets.

---

## 1. Implementation philosophy

Build a deterministic-first agent, not a fragile free-form autonomous loop.

1. Business facts must come from APIs, KB docs, or Python computations.
2. Arithmetic must be done in code, never by the LLM.
3. Pagination must be handled before any aggregate answer.
4. Entity existence must be verified before answering.
5. The LLM may classify, summarize, and polish, but must not invent facts.
6. Confidence must be evidence-based, not based on the LLM saying “I am confident”.
7. If evidence is insufficient, return a specific grounded abstention.
8. The UI can be impressive, but must not risk the `/ask` contract.

Recommended architecture:

```text
question
  -> deterministic router / intent extractor
  -> source-specific handlers
  -> API client + KB retrieval
  -> EvidencePack with facts, sources, confidence, missing data
  -> confidence gate
  -> deterministic/LLM final answer formatter
  -> frozen AskResponse JSON
```

---

## 2. Target repository structure

Repo-specific note for Simone's current tree: the root contains a duplicate reference copy under `hackathon info/`. Do **not** edit or deploy anything inside `hackathon info/`; treat it as archived source material only. Implement the product in the top-level `backend/` folder and root-level project files. Keep generated plans/prompts at the repository root.

Create a small modular backend under `backend/app/`. Keep `backend/main.py` thin.

```text
backend/
  main.py
  pyproject.toml
  .env.example
  data/kb/
  static/
    index.html
    files/
  app/
    __init__.py
    config.py
    schemas.py
    api_client.py
    cache.py
    kb.py
    llm.py
    router.py
    orchestrator.py
    evidence.py
    normalizers.py
    artifacts.py
    graph.py
    handlers/
      __init__.py
      crm.py
      erp.py
      calls.py
      kb_handlers.py
      artifacts_handler.py
      generic.py
  scripts/
    run_samples.py
    smoke_test.py
```

Keep all code, comments, identifiers, and generated answers in English.

---

## 3. Dependencies

The coding agent is allowed to modify `backend/pyproject.toml` freely.

Add minimal dependencies:

```bash
cd backend
uv add httpx openai python-dotenv pydantic rapidfuzz rank-bm25 fpdf2 openpyxl python-docx python-pptx
```

Notes:

1. `httpx`: API calls with timeouts/retries.
2. `openai`: Regolo OpenAI-compatible inference.
3. `rapidfuzz`: robust entity-name matching.
4. `rank-bm25`: fast whole-document KB retrieval.
5. `fpdf2`: PDF artifacts.
6. `openpyxl`: XLSX artifacts.
7. `python-docx`: DOCX fallback artifacts.
8. `python-pptx`: PPTX fallback artifacts.

Do not add heavyweight frontend tooling. The UI must be a single static `index.html` using CDN libraries.

---

## 4. Environment variables

Read all runtime config from environment variables.

Required:

```env
LLM_BASE_URL=https://api.regolo.ai/v1
LLM_API_KEY=<filled manually by the user>
MODEL=<filled manually by the user>
MOCK_API_BASE_URL=https://aldente.yellowtest.it
MOCK_API_TOKEN=<filled manually by the user>
PUBLIC_BASE_URL=http://localhost:8000
```

Implementation rules:

1. The user will fill `.env` manually.
2. Do not auto-switch models. Rely on `MODEL` from `.env`.
3. Use Regolo through the OpenAI-compatible SDK:

   ```python
   from openai import OpenAI

   client = OpenAI(
       api_key=settings.llm_api_key,
       base_url=settings.llm_base_url,
   )
   ```

4. If an env var is missing, `/health` should still work. `/ask` should return HTTP 200 with a clear configuration error in `answer`, not a 500.
5. Never expose tokens in logs or responses.

---

## 5. Workstream A — Core schemas and evidence model

Implement first.

### 5.1 `app/schemas.py`

Create Pydantic models:

```python
from pydantic import BaseModel, Field
from typing import Literal

Verticale = Literal["crm", "erp", "calls", "kb"]

class AskRequest(BaseModel):
    question: str = Field(min_length=1)

class AskResponse(BaseModel):
    answer: str
    sources: list[str]
    verticale: Verticale
    artifact_url: str | None = None
```

### 5.2 `app/evidence.py`

Create an internal evidence container:

```python
from dataclasses import dataclass, field
from typing import Any, Literal

Verticale = Literal["crm", "erp", "calls", "kb"]

@dataclass
class EvidencePack:
    answerable: bool
    verticale: Verticale
    facts: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    artifact_url: str | None = None

    def add_source(self, source: str) -> None:
        if source and source not in self.sources:
            self.sources.append(source)
```

### 5.3 Evidence confidence policy

Use evidence-based confidence:

| Evidence state | Confidence |
|---|---:|
| Exact ID/entity found + required fields found + computed result | `0.90-1.00` |
| Unique fuzzy entity match + required fields found | `0.75-0.89` |
| Strong KB hit by SKU/product/doc ID | `0.80-0.95` |
| Verified absence / trap abstention | `0.90-1.00` |
| Partial evidence, missing one non-critical field | `0.55-0.74` |
| LLM-only answer, no source evidence | forbidden |

Gate factual answers:

1. If `answerable=True` and `confidence >= 0.72`, answer normally.
2. If `answerable=True` but `confidence < 0.72`, abstain specifically.
3. If `answerable=False` because absence was verified, answer with a precise explanation and high confidence.
4. Generic “I don’t know” is not enough. Say what was checked.

Example abstention:

```text
Not available in the provided sources: I found lot LOT-2026-0658 in ERP production data, but the sources do not store cost or profit-margin fields for lots. I therefore cannot compute a profit margin.
```

---

## 6. Workstream B — Config, cache, and normalizers

### 6.1 `app/config.py`

Load `.env` locally with `python-dotenv`, but keep Railway env support.

```python
from functools import lru_cache
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseModel):
    llm_base_url: str | None = os.getenv("LLM_BASE_URL")
    llm_api_key: str | None = os.getenv("LLM_API_KEY")
    model: str | None = os.getenv("MODEL")
    mock_api_base_url: str = os.getenv("MOCK_API_BASE_URL", "https://aldente.yellowtest.it")
    mock_api_token: str | None = os.getenv("MOCK_API_TOKEN")
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    request_timeout_seconds: float = 12.0
    ask_timeout_seconds: float = 28.0
    cache_ttl_seconds: int = 900

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### 6.2 `app/cache.py`

Implement simple in-memory TTL cache:

1. Cache API GET responses by `(path, sorted(params))`.
2. Cache complete `/ask` answers by normalized question.
3. TTL: 15 minutes.
4. Include max size, e.g. 512 entries, to avoid memory growth.
5. Do not cache exceptions.

### 6.3 `app/normalizers.py`

Implement helpers:

```python
def normalize_text(s: str) -> str: ...
def normalize_company_name(s: str) -> str: ...
def extract_ids(question: str) -> dict[str, list[str]]: ...
def extract_money_stage_words(question: str) -> set[str]: ...
def is_artifact_request(question: str) -> tuple[bool, str | None]: ...
def is_aggregate_question(question: str) -> bool: ...
```

Extract patterns:

```text
CUST-####
OPP-####
ORD-2026-####
LOT-2026-####
PAS-XXX-###
RAW-XXX-###
SUP-###
CALL-#####
DOC-###
```

Normalize customer variants:

1. Lowercase.
2. Remove punctuation.
3. Collapse spaces.
4. Treat `S.p.A.`, `Spa`, `Srl`, `S.r.l.` as suffix noise during fuzzy matching.
5. Handle variants like `GranMercato` vs `Gran Mercato`.

---

## 7. Workstream C — Al Dente API client

Implement before handlers.

### 7.1 `app/api_client.py`

Use `httpx.Client` or `httpx.AsyncClient`. Simpler is fine; FastAPI can call sync functions for this hackathon.

Required client methods:

```python
class AlDenteAPI:
    def get(self, path: str, params: dict | None = None) -> dict: ...
    def list_page(self, path: str, params: dict | None = None, limit: int = 200, offset: int = 0) -> dict: ...
    def list_all(self, path: str, params: dict | None = None, max_pages: int | None = None) -> list[dict]: ...
```

Implementation rules:

1. Base URL from `MOCK_API_BASE_URL`.
2. `Authorization: Bearer <MOCK_API_TOKEN>` on every call except `/health`.
3. Timeout each API call.
4. Retry once on network/5xx errors with small backoff.
5. On API error, raise a typed internal exception with status and path.
6. Never log token.
7. Track sources as endpoint names, e.g. `crm/customers`, `erp/inventory`, `calls/CALL-58020/transcript`.
8. All list endpoints are paginated and max `limit=200`.
9. Always check `pagination.total` before aggregating.
10. For transcript endpoint, segments are under `segments`, not `data`.

### 7.2 Endpoint helpers

Create typed convenience methods:

```python
def search_customers(search=None, channel=None, status=None): ...
def get_customer(customer_id): ...
def list_opportunities(customer_id=None, stage=None, owner=None): ...
def list_orders(customer_id=None, status=None, from_date=None, to_date=None): ...
def list_invoices(customer_id=None, status=None, order_id=None): ...
def list_calls(customer_id=None, type=None, outcome=None, from_date=None, to_date=None): ...
def get_call(call_id): ...
def search_transcript(call_id, search=None, speaker=None, limit=20, offset=0): ...
def list_production_orders(customer_id=None, status=None, sku=None, from_date=None, to_date=None): ...
def list_inventory(type=None, below_min=None, search=None): ...
def list_suppliers(search=None, category=None): ...
def get_bom(sku): ...
def list_shipments(customer_id=None, order_id=None, status=None): ...
```

---

## 8. Workstream D — KB retrieval

Implement whole-document retrieval. Do not overchunk.

### 8.1 `app/kb.py`

Load all markdown docs from `backend/data/kb/` lazily on first query.

For each doc store:

```python
@dataclass
class KBDoc:
    doc_id: str          # e.g. DOC-015 if present in filename/content, else filename stem
    path: str
    title: str
    text: str
    tokens: list[str]
```

Implement:

```python
class KnowledgeBase:
    def search(self, query: str, top_k: int = 5) -> list[KBDocHit]: ...
    def search_by_id(self, doc_id: str) -> KBDoc | None: ...
    def search_product(self, sku_or_name: str) -> list[KBDocHit]: ...
    def search_policy(self, topic: str) -> list[KBDocHit]: ...
```

Use hybrid scoring:

1. Exact ID/SKU/doc-ID boost.
2. BM25 score.
3. Exact phrase boost.
4. Product name normalized boost.

Return whole documents. Include `DOC-###` in `sources` when known.

### 8.2 KB-specific extraction helpers

Implement deterministic extraction where possible:

```python
def extract_shelf_life_and_allergens(doc_text: str) -> dict: ...
def extract_price_for_sku(doc_text: str, sku: str) -> dict: ...
def extract_return_policy_terms(doc_text: str) -> dict: ...
```

If regex extraction fails, use LLM finalizer only with the retrieved doc text as evidence.

Authority rule:

1. Official KB documents beat call transcripts when they conflict.
2. For price-list questions, official 2026 wholesale price list is authoritative over phone-call mentions.

---

## 9. Workstream E — LLM wrapper through Regolo

### 9.1 `app/llm.py`

The product uses Regolo with OpenAI-compatible API.

Implement small wrapper:

```python
class LLMClient:
    def classify(self, question: str) -> dict: ...
    def final_answer(self, question: str, evidence: EvidencePack) -> str: ...
    def generate_artifact_html(self, question: str, evidence: EvidencePack) -> str: ...
```

Do not rely on tool/function calling for correctness.

Use normal chat completions and request JSON when classifying.

Classification prompt output schema:

```json
{
  "intent": "lookup|aggregate|multi_source|artifact|trap_or_unknown",
  "verticale_hint": "crm|erp|calls|kb|null",
  "entities": {
    "customer_names": [],
    "customer_ids": [],
    "skus": [],
    "lot_ids": [],
    "order_ids": [],
    "call_ids": [],
    "doc_ids": []
  },
  "artifact_type": "html|pdf|xlsx|docx|pptx|null",
  "needs": ["short descriptions of needed data"]
}
```

LLM guardrails:

1. Final-answer prompt must say: “Use only the evidence JSON. Do not add facts.”
2. If evidence says unavailable, phrase a clear abstention.
3. If numbers are provided, preserve them exactly.
4. Keep answers concise, human, executive-style.
5. Return English only.
6. On LLM error, use deterministic fallback templates.

### 9.2 Final answer style

Good answer:

```text
Primato Supermercati S.p.A. has 4 open opportunities: 2 in qualification and 2 in negotiation. Their total value is 740,000 EUR.
```

Bad answer:

```text
It seems like Primato might have several opportunities, likely around 740k EUR.
```

---

## 10. Workstream F — Entity resolution

Implement robust resolvers. This is critical for traps and hidden questions.

### 10.1 Customer resolver

```python
def resolve_customer(question: str, api: AlDenteAPI) -> ResolvedEntity:
    ...
```

Rules:

1. If `CUST-####` is present, call `/crm/customers/{id}`.
2. Else search `/crm/customers?search=<name>` if a likely company name exists.
3. If no exact search result, use fuzzy match over a limited customer list.
4. Verify uniqueness. If ambiguous, return `answerable=False` with candidates.
5. If none found, return high-confidence abstention: “There is no customer named X in the CRM.”

### 10.2 SKU/product resolver

Rules:

1. Exact SKU wins.
2. If product name is present, search inventory and KB.
3. Use KB product spec docs to map product names to SKUs when possible.
4. Avoid guessing if multiple SKUs match.

### 10.3 Lot/order/call/doc resolver

Rules:

1. Exact ID lookup if available.
2. If not found, return specific abstention.
3. Do not fabricate relationships.

---

## 11. Workstream G — Deterministic handlers, prioritized

The orchestrator should try handlers in this order.

Each handler must expose:

```python
def can_handle(question: str, classification: dict) -> bool: ...
def handle(question: str, ctx: Context) -> EvidencePack: ...
```

### 11.1 Artifact request handler

Detect:

```text
generate, create, make, deck, report, pdf, xlsx, excel, docx, document, pptx, presentation, slide, html
```

Route to artifact-specific data collection, then artifact generation.

Dominant `verticale` is the dominant source of the facts, not necessarily `kb`.

### 11.2 CRM: open opportunities by customer

Pattern examples:

```text
How many open opportunities does <customer> have, and what is their total value?
```

Implementation:

1. Resolve customer.
2. Fetch opportunities with `customer_id` and stage `qualification`.
3. Fetch opportunities with `customer_id` and stage `negotiation`.
4. Count all rows.
5. Sum value fields in Python.
6. Answer with count and total value.
7. Sources: `crm/customers`, `crm/opportunities`.
8. `verticale="crm"`.

Open opportunity = `qualification + negotiation`.

### 11.3 CRM: opportunities in negotiation grouped by channel

Pattern:

```text
Total value of opportunities in the negotiation stage, grouped by customer channel
```

Implementation:

1. Fetch all negotiation opportunities with pagination.
2. Fetch referenced customers.
3. Group opportunity value by customer channel: `GDO`, `distributor`, `horeca`.
4. Sum in Python.
5. Return exact totals.

Do not count only first page.

### 11.4 CRM: order/customer status traps

Pattern:

```text
What is the status of the order for <customer>?
```

Implementation:

1. Resolve customer first.
2. If customer missing, answer: “There is no customer named X in the CRM.”
3. If customer exists, fetch open/recent orders.
4. If no order, say no order found.
5. Never invent an order status.

### 11.5 ERP: inventory below minimum

Pattern:

```text
Is SKU <PAS-...> below its minimum stock? Give the on-hand quantity.
```

Implementation:

1. Search `/erp/inventory?search=<sku>`.
2. Find exact SKU row.
3. Compare on-hand quantity to minimum stock.
4. Answer yes/no with both numbers.
5. `verticale="erp"`.

### 11.6 ERP: BOM → raw material → supplier → stock

Pattern:

```text
Which semolina does SKU <PAS-...> use, which supplier provides it, and is that raw material below minimum stock?
```

Implementation:

1. Fetch `/erp/bom?sku=<finished_sku>`.
2. Find BOM row where raw material/category is semolina if requested.
3. Extract raw material SKU.
4. Search `/erp/inventory?search=<raw_sku>`.
5. Resolve supplier ID/name from inventory/BOM row if present; else search suppliers by category/name.
6. Answer raw material, supplier, below-min status.
7. Sources: `erp/bom`, `erp/inventory`, `erp/suppliers`.

### 11.7 ERP: production lot status

Patterns:

```text
status of lot LOT-...
status of related production lot
```

Implementation:

1. If lot ID present, query production orders or search by lot ID if API supports search fields in returned rows.
2. If customer/order context present, follow customer → orders → production orders.
3. Return lot status, SKU, order/customer if known.
4. If margin/profit/cost requested, abstain specifically because sources do not store it.

### 11.8 Calls: latest call complaint

Pattern:

```text
In the last call with <customer>, what was the complaint and which lot did it concern?
```

Implementation:

1. Resolve customer.
2. Fetch calls for `customer_id`, preferably type `support` or outcome `complaint_open` first.
3. If no complaint calls, fetch recent calls for customer.
4. Sort by call date/time descending.
5. Pick latest relevant call.
6. Search transcript with terms:
   - `complaint`
   - `quality`
   - `broken`
   - `lot`
   - `return`
7. Extract defect and lot ID from relevant segments.
8. Answer with complaint, lot, and call ID.
9. Do not download entire transcript unless targeted searches fail and segment total is small enough.

### 11.9 Calls + KB: return qualification

Pattern:

```text
Does the complaint from that last <customer> call qualify for a return under the quality policy?
```

Implementation:

1. Resolve customer.
2. Find latest complaint call and relevant transcript segments.
3. Extract defect, lot ID, date/window evidence, photo/evidence if mentioned.
4. Retrieve KB quality/returns policy.
5. Determine in Python whether policy conditions are met.
6. Answer yes/no with reason, required conditions, and outcome.
7. Sources: call metadata, call transcript, policy DOC.
8. Dominant `verticale="calls"` because the complaint is the central object.

### 11.10 Calls: count all calls with defect X

Pattern:

```text
Across ALL recorded calls, count how many quality complaints concern defect '<defect>'.
```

Implementation:

1. Page all `/calls` metadata. Do not stop at first page.
2. For each call, search transcript with defect term, e.g. `broken pasta`.
3. Count calls where relevant transcript segments indicate a quality complaint about that defect.
4. Count calls, not segments.
5. Return exact number.
6. Be efficient: avoid full transcript downloads.

### 11.11 KB: shelf life and allergens

Pattern:

```text
What is the shelf life (TMC) and declared allergens for <product/SKU>?
```

Implementation:

1. Search KB by exact SKU and product name.
2. Retrieve product spec doc.
3. Extract shelf life/TMC and allergens/may-contain fields.
4. Answer exactly.
5. Sources: product spec DOC.
6. `verticale="kb"`.

### 11.12 KB + Calls: official price conflict

Pattern:

```text
A call mentions one figure and official price list mentions another. Which is correct?
```

Implementation:

1. Resolve customer if present.
2. Resolve SKU/product.
3. Search calls/transcripts for SKU/product/price mention.
4. Search KB for official 2026 wholesale price list.
5. Extract official list price.
6. Answer that official KB price is authoritative over call mention.
7. Sources include call transcript and price-list DOC.
8. Dominant `verticale="kb"` because official document determines truth.

### 11.13 Generic fallback handler

Use this only after deterministic handlers fail.

1. Use classification result.
2. Retrieve likely source data conservatively.
3. Build EvidencePack.
4. If evidence is strong, answer.
5. Else abstain specifically.

Never allow LLM to answer from general knowledge.

---

## 12. Workstream H — Orchestrator

Implement `app/orchestrator.py`.

```python
class Orchestrator:
    def answer(self, question: str) -> AskResponse:
        ...
```

Flow:

1. Normalize question.
2. Check ask-response cache.
3. Validate env/config.
4. Extract IDs and obvious intents.
5. Run LLM classifier only if useful and fast.
6. Try handlers in priority order.
7. Apply confidence gate.
8. Generate final answer text.
9. Ensure `sources` is a list of strings.
10. Ensure `verticale` is valid.
11. Ensure `artifact_url` exists only for binary files.
12. Cache answer.
13. Return `AskResponse`.

Timeout strategy:

1. Use deadline tracking with `time.monotonic()`.
2. Keep 2 seconds buffer before 30-second evaluator limit.
3. If deadline is near, stop extra LLM calls and produce deterministic answer/abstention.

Error strategy:

1. Catch all exceptions at `/ask` boundary.
2. Log stack trace server-side.
3. Return HTTP 200:

   ```json
   {
     "answer": "I could not answer reliably because an internal data-source error occurred while checking the provided sources.",
     "sources": [],
     "verticale": "crm",
     "artifact_url": null
   }
   ```

4. Pick the best guessed `verticale` from routing if available; default to `crm` only when no hint exists.

---

## 13. Workstream I — Artifact generation

Implement after core handlers, but before UI polish.

### 13.1 General artifact rules

1. Inline HTML/markdown artifacts go directly in `answer`; `artifact_url=null`.
2. Binary artifacts must be saved under:

   ```text
   backend/static/files/
   ```

3. Binary artifact response:

   ```json
   {
     "answer": "Generated the requested PDF report.",
     "sources": [...],
     "verticale": "erp",
     "artifact_url": "https://<PUBLIC_BASE_URL>/files/<filename>.pdf"
   }
   ```

4. Use UUID/timestamp filenames:

   ```text
   artifact_20260613_143012_ab12cd.pdf
   ```

5. Ensure `PUBLIC_BASE_URL` has no trailing slash before building URL.
6. Verify the file exists before returning URL.

### 13.2 Priority 1 — Inline HTML deck

For requests like:

```text
Generate a 4-slide HTML deck for the sales rep visiting <customer>: profile, open deals, order/lot status, recent call complaints.
```

Return complete inline HTML in `answer`, styled with a coherent brand system.

Deck sections:

1. Customer profile.
2. Open opportunities/deals.
3. Orders/shipments/production lots.
4. Recent call complaints/risks/next steps.

Style:

1. Dark espresso background.
2. Semolina/gold highlights.
3. Tomato red accent.
4. Clean card layout.
5. “Pasta brain” visual motifs using CSS only.

### 13.3 Priority 2 — PDF reports

Use `fpdf2`.

Best hidden-test likely shape:

```text
Generate a one-page PDF with products below minimum stock.
```

Implementation:

1. Fetch `/erp/inventory?below_min=true` with pagination.
2. Build table: SKU, product/material name, type, on-hand, minimum, gap.
3. Save PDF.
4. Return artifact URL.

### 13.4 Priority 3 — XLSX reports

Use `openpyxl`.

Good use cases:

1. Below-min inventory report.
2. Purchase planning sheet.
3. Opportunities grouped by customer/channel.

Implementation:

1. Use styled headers.
2. Freeze top row.
3. Auto-size columns.
4. Use sheets by category/type when useful.

### 13.5 Priority 4 — DOCX/PPTX fallback

Implement basic fallback support:

1. DOCX: one-page narrative report with headings and tables.
2. PPTX: simple 4-slide presentation with title, cards, and source note.
3. Keep facts correct over visual complexity.

---

## 14. Workstream J — FastAPI app

### 14.1 `backend/main.py`

Keep thin and robust.

Required endpoints:

```python
GET /health
GET /
POST /ask
GET /files/{path}
GET /graph-data
```

Rules:

1. `/health` returns `{"status": "ok"}` quickly.
2. `/` serves `backend/static/index.html`.
3. `/ask` uses frozen schema and never raises uncaught errors.
4. `/files/` must serve generated artifacts.
5. `/graph-data` is allowed for UI only; do not change `/ask`.

Example route behavior:

```python
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    try:
        return orchestrator.answer(req.question)
    except Exception:
        logger.exception("ask failed")
        return AskResponse(
            answer="I could not answer reliably because an internal error occurred while checking the available sources.",
            sources=[],
            verticale="crm",
            artifact_url=None,
        )
```

---

## 15. Workstream K — Knowledge graph UI

Build from scratch. Do not clone an external template.

### 15.1 UI stack

Use one static file:

```text
backend/static/index.html
```

Use CDN:

```html
<script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
```

Optional CDN:

```html
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

No React/Vite/build step.

### 15.2 Visual concept

Name: **Al Dente Company Brain**.

Theme:

1. Dark espresso background.
2. Pasta/semolina gold highlights.
3. Tomato red accent.
4. Graph as a “pasta brain”: curved edges, glowing nodes, organic layout.
5. Professional executive feel, not childish.

### 15.3 UI layout

Implement:

1. Header/hero with product name and short tagline.
2. Ask input textarea.
3. Submit button.
4. Sample question chips.
5. Answer panel with markdown/HTML rendering.
6. Source badges.
7. Artifact download button when `artifact_url` is present.
8. Confidence/evidence note if returned internally or optionally rendered from answer metadata.
9. Knowledge graph panel.
10. Node details drawer.
11. Clicking a node should prefill and optionally submit a contextual question.

### 15.4 `/graph-data` endpoint

Implement in `app/graph.py`.

Return Cytoscape-compatible data:

```json
{
  "nodes": [
    {"data": {"id": "CUST-0132", "label": "Primato", "type": "customer"}}
  ],
  "edges": [
    {"data": {"id": "edge1", "source": "CUST-0132", "target": "OPP-2031", "label": "has opportunity"}}
  ]
}
```

Build a representative graph, not the entire database:

1. Active customers, limited to ~20.
2. Open opportunities, limited to useful examples.
3. Recent calls, limited to ~20.
4. Below-min inventory items.
5. A handful of finished product SKUs.
6. BOM links for selected SKUs.
7. Raw materials.
8. Suppliers.
9. Optional KB docs as document nodes.

Cache graph data for 15 minutes to avoid metered API waste.

### 15.5 Node click behavior

Generate contextual questions:

1. Customer node: `Give me a concise account brief for <customer>.`
2. SKU node: `Is SKU <sku> below minimum stock and what does its product spec say?`
3. Lot node: `What is the status of lot <lot_id>?`
4. Supplier node: `Which materials does supplier <supplier> provide?`
5. Call node: `Summarize the relevant complaint or outcome from call <call_id>.`
6. KB doc node: `Summarize the key operational rules in <doc_id>.`

---

## 16. Workstream L — Sample test runner

Implement `backend/scripts/run_samples.py`.

Purpose: quickly test local or deployed `/ask` against the 12 public sample questions.

Usage:

```bash
cd backend
uv run python scripts/run_samples.py --base-url http://localhost:8000
uv run python scripts/run_samples.py --base-url https://<railway-url>
```

For each sample:

1. POST to `/ask`.
2. Check HTTP 200.
3. Check JSON keys exist.
4. Check `verticale` is valid.
5. Check important facts/strings appear.
6. Print pass/fail summary.

Do not require exact prose match. Assert key facts.

Examples:

1. Sample 1 must include `4`, `740,000` or `740000`, `EUR`.
2. Sample 2 must include `462`, `2000`, and yes/below.
3. Sample 7 must include `not available` and `profit margin`.
4. Sample 8 must include no customer found.

Also implement `scripts/smoke_test.py`:

1. `/health` works.
2. `/` returns HTML.
3. `/ask` returns proper schema.
4. If artifact URL is returned, `GET artifact_url` succeeds.

---

## 17. Workstream M — Deployment instructions inside repo

Add/update a short `backend/IMPLEMENTATION_NOTES.md` or append to README only if time permits.

The product must deploy as one Railway service from `backend/`.

Commands:

```bash
cd backend
railway init
railway up
railway variables \
  --set LLM_BASE_URL=https://api.regolo.ai/v1 \
  --set LLM_API_KEY=<key> \
  --set MODEL=<model> \
  --set MOCK_API_BASE_URL=https://aldente.yellowtest.it \
  --set MOCK_API_TOKEN=<token>
railway domain
railway variables --set PUBLIC_BASE_URL=https://<railway-url>
```

Smoke test:

```bash
curl https://<railway-url>/health
curl -X POST https://<railway-url>/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Is SKU PAS-PEN-500 below its minimum stock? Give the on-hand quantity."}'
```

Deploy early even if not perfect, then iterate.

---

## 18. Performance and reliability requirements

1. Use API filters whenever possible.
2. Never bulk download transcripts unless absolutely necessary.
3. Page all list endpoints for aggregates.
4. Limit LLM calls:
   - 0 for deterministic direct answers if possible.
   - 1 for classification only when needed.
   - 1 for final polished answer only when useful.
5. Prefer deterministic templates for common answers.
6. Cache repeated API calls and repeated questions.
7. Keep startup light. Build KB index lazily, not during healthcheck.
8. Keep `/health` fast and independent of external services.
9. Guard every network call with timeout.
10. Return HTTP 200 on all `/ask` failures.

---

## 19. Trap handling checklist

Implement explicit trap protection.

### 19.1 Missing customer

If a question asks about a customer by name:

1. Search CRM.
2. If no match, answer:

   ```text
   There is no customer named "<name>" in the CRM, so I cannot report an order/status for it.
   ```

3. Do not search random orders without verified customer identity.

### 19.2 Unsupported financial metrics

If a question asks for:

```text
profit margin, margin, cost, profitability, gross margin, net margin
```

and sources do not expose those fields:

1. Check relevant entity exists if an ID is provided.
2. State that cost/profit-margin data is not stored in the available sources.
3. Do not estimate.

### 19.3 Ambiguous entities

If fuzzy matching returns multiple plausible customers/products:

1. Do not choose arbitrarily.
2. Say the entity is ambiguous and list candidates if useful.
3. Set high-confidence abstention if ambiguity is verified.

### 19.4 Unsupported external knowledge

If a question asks outside the provided company data:

1. Say it is not available from the provided Al Dente sources.
2. Do not use public internet or general knowledge.

---

## 20. Source tracking rules

Every handler must populate `sources`.

Use endpoint/document identifiers such as:

```text
crm/customers
crm/opportunities
erp/inventory
erp/bom
erp/suppliers
calls
calls/CALL-58020
calls/CALL-58020/transcript
DOC-015
```

Rules:

1. Include only sources actually used.
2. Include document IDs for KB docs.
3. Include transcript source if transcript segments informed the answer.
4. Source strings do not need URLs.
5. Avoid huge source lists; deduplicate.

---

## 21. Answer formatting rules

1. English only.
2. Concise, precise, human-sounding.
3. Include exact IDs when helpful.
4. Include exact numbers and units.
5. Format money as `740,000 EUR`.
6. Format quantities with units when available, e.g. `462 cartons`.
7. Avoid “I think”, “probably”, “seems”.
8. When abstaining, say exactly what is missing and what was checked.
9. Do not mention internal confidence scores unless the UI specifically displays them.
10. Do not expose prompts, tokens, stack traces, or secrets.

---

## 22. Priority implementation order

Follow this order strictly.

### Phase 1 — Make `/ask` correct and safe

1. Add dependencies.
2. Create schemas/config/evidence/cache.
3. Implement API client with pagination.
4. Implement KB whole-doc retrieval.
5. Implement entity resolvers.
6. Implement CRM open-opportunity aggregate handler.
7. Implement ERP inventory handler.
8. Implement KB shelf-life/allergen handler.
9. Implement calls latest-complaint handler.
10. Implement trap handlers.
11. Implement orchestrator and `/ask`.
12. Run first 4 sample questions.

### Phase 2 — Cover multi-source and aggregates

13. Negotiation opportunities grouped by channel.
14. Complaint return qualification using calls + KB policy.
15. BOM → supplier → inventory chain.
16. All-calls defect count with transcript search.
17. Price conflict: official KB document beats call transcript.
18. Run all 12 sample questions.

### Phase 3 — Artifacts

19. Inline HTML deck.
20. PDF below-min stock report.
21. XLSX below-min/procurement report.
22. Basic DOCX report.
23. Basic PPTX deck.
24. Verify `/files/` links.

### Phase 4 — UI and graph

25. Build static branded UI.
26. Add `/graph-data` with cached representative graph.
27. Add Cytoscape visualization.
28. Add node-click-to-ask.
29. Polish visual style.

### Phase 5 — Reliability and deploy

30. Add sample test runner.
31. Add smoke test.
32. Add robust error handling.
33. Add timing logs without secrets.
34. Deploy to Railway.
35. Set `PUBLIC_BASE_URL`.
36. Run endpoint check and platform self-test.
37. Iterate based on feedback.

---

## 23. Definition of done

The implementation is acceptable only when all items below pass.

### Backend contract

- [ ] `GET /health` returns `{"status":"ok"}` quickly.
- [ ] `GET /` serves the UI.
- [ ] `POST /ask` accepts exactly `{"question": "..."}`.
- [ ] `/ask` requires no auth.
- [ ] `/ask` always returns HTTP 200.
- [ ] `/ask` response has `answer`, `sources`, `verticale`, `artifact_url`.
- [ ] No streaming.
- [ ] No background jobs.
- [ ] Typical response under 10 seconds; hard cap under 30 seconds.

### Correctness

- [ ] Open opportunities count/sum works.
- [ ] Pagination-aware aggregates work.
- [ ] ERP inventory below-min works.
- [ ] BOM → raw material → supplier → inventory works.
- [ ] Last-call complaint extraction works.
- [ ] Return-policy qualification works.
- [ ] KB shelf-life/allergen works.
- [ ] Official price-list conflict works.
- [ ] Trap: missing customer handled.
- [ ] Trap: profit margin unavailable handled.

### Artifacts

- [ ] Inline HTML deck returned inside `answer`.
- [ ] PDF artifact saved and served.
- [ ] XLSX artifact saved and served.
- [ ] DOCX/PPTX basic support exists or fails gracefully with honest answer.
- [ ] `artifact_url` is absolute and uses `PUBLIC_BASE_URL`.

### UI

- [ ] UI can ask a question end-to-end.
- [ ] UI renders answer and sources.
- [ ] UI renders artifact link.
- [ ] UI shows Cytoscape knowledge graph.
- [ ] Graph includes customers, opportunities/orders/lots/products/materials/suppliers/calls where available.
- [ ] Clicking graph nodes creates useful questions.
- [ ] Visual style feels polished and pasta-branded.

### Deployment

- [ ] Railway deploy works from `backend/`.
- [ ] Env vars are set on Railway.
- [ ] `PUBLIC_BASE_URL` is set to Railway URL.
- [ ] Platform endpoint check passes.
- [ ] Platform self-test is run and feedback is used.

---

## 24. Suggested implementation details for hidden tests

Hidden tests will likely reuse the sample shapes with different entities. Do not hardcode sample entities.

Generalize every sample shape:

1. Any customer name or `CUST-####`.
2. Any SKU `PAS-XXX-###`.
3. Any raw material SKU `RAW-XXX-###`.
4. Any lot `LOT-2026-####`.
5. Any call `CALL-#####`.
6. Any defect term, not only `broken pasta`.
7. Any artifact type.

For entity names, always resolve via CRM/API/KB before answering.

For hidden aggregates, always page all data.

For hidden traps, first verify premise, then abstain specifically.

---

## 25. Coding-agent operating instructions

When executing this plan:

1. Read `AGENTS.md`, `API.md`, `BRIEF.md`, and `SAMPLE_QUESTIONS.md` first.
2. Do not change the `/ask` schema.
3. Do not ask the user for env keys; assume they will fill `.env` manually.
4. Implement in small, testable commits/steps.
5. After each phase, run the sample test script.
6. Prefer simple reliable code over clever agentic behavior.
7. Keep logs useful but never log secrets.
8. When uncertain, implement a deterministic fallback and a specific abstention.
9. Do not use external data sources.
10. Do not hardcode public sample answers.
11. Do not break Railway deployment.
12. Do not add frontend build tooling.
13. Use CDN for Cytoscape.js.
14. Keep generated artifacts factually correct even if visual polish is limited.
15. Optimize for evaluator-facing correctness first.

---

## 26. Minimal prompt snippets to use inside code

### 26.1 Classifier system prompt

```text
You classify questions for an Al Dente internal company brain.
Return JSON only. Do not answer the user.
Sources available: crm, erp, calls, kb.
Extract IDs, customer names, SKUs, lots, calls, document IDs, requested artifact type, and likely intent.
If uncertain, use null/empty arrays. Never invent entities.
```

### 26.2 Final-answer system prompt

```text
You write concise English answers for Al Dente company data questions.
Use only the evidence JSON provided by the backend.
Do not add facts, assumptions, estimates, or outside knowledge.
Preserve all IDs, numbers, currencies, quantities, and source-grounded conclusions exactly.
If the evidence says the answer is unavailable or unverified, explain specifically what is missing and what was checked.
Sound professional and human, not robotic.
```

### 26.3 Artifact-generation system prompt

```text
Create a polished client-ready artifact using only the provided evidence.
Do not invent facts.
Use a coherent Al Dente visual style: dark espresso, semolina gold, tomato accent, clean executive layout.
For inline HTML, return only the HTML snippet/document requested.
For binary artifacts, the backend will render the file; provide only structured content and copy.
```

---

## 27. Final strategic reminder

The winning implementation is not the one with the most autonomous LLM loop. It is the one that answers the hidden questions correctly, quickly, and honestly.

The strongest path:

1. Deterministic data retrieval.
2. Pagination-aware arithmetic.
3. Whole-document KB retrieval.
4. Premise verification.
5. Evidence confidence gate.
6. Professional concise final answers.
7. Useful artifacts.
8. Polished pasta-brain graph UI.

Build exactly that.
