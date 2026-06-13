# Coding Agent Hackathon powered by Cursor - Milano

**Participant brief - Company Brain Challenge**

| | |
| --- | --- |
| Organizer | Yellow Tech |
| Date | Saturday, June 13th 2026, 9:30 - 20:00 |
| Venue | Via Polidoro da Caravaggio 37, Milano |
| Work session | 6 hours |
| Format | Individual |
| Environment | Cursor |
| Prizes | 1st place 1,000 EUR - 2nd place 500 EUR |

> The top 15 overall also earn a direct pass to **Wave** (the Italian Hackathon League final), Turin, 7-9 October 2026.

## 1. The challenge

Build the **company brain** of a food company: an agent that answers requests about the company by querying multiple data sources **on its own**, producing both text answers and artifacts (HTML presentations, documents, and in some cases **downloadable docx / pptx / pdf / xlsx files**).

The company is *Al Dente S.r.l.*, a pasta maker selling dry pasta to supermarkets, distributors and restaurants. You don't know its data: your agent has to fetch it on the fly from the sources we give you.

The heart of the challenge is **orchestration**: building an **agent loop** that understands which tools it needs, calls our APIs efficiently, combines them with a knowledge base you build, and formats the requested output. You win by optimizing and iterating, not by pasting a prompt.

### Example requests

- "How many open opportunities does Supermercati Conti have, and what is their total value?"
- "For the customer with the highest-value open opportunity, what is the status of the related production lot?"
- "Does the quality complaint raised by phone by Supermercati Conti qualify for a return under the quality policy?"
- "Generate a 4-slide HTML deck for the sales rep visiting Supermercati Conti: profile, open deals, order status, complaints from recent calls."
- "Generate a one-page PDF with the products below minimum stock."

## 2. What you get (starter kit)

- **Our APIs** (CRM, call logs, ERP/production), documented, **read-only**, authenticated via header (`API.md`).
- The **company documents** (product specs and allergens, returns/quality policies, customer requirements, price list) to build your knowledge base on - already in the starter (`backend/data/kb/`).
- A **starter repo** with the `/ask` endpoint already wired (it returns 501: implementing it is the challenge), artifact serving via `/files/`, Cursor rules, `railway.json` and the deploy/Docker guides.
- **12 sample requests with answers** (`SAMPLE_QUESTIONS.md`) + the platform **self-test** (see section 7).
- Access to **Cursor** via coupon.
- **Runtime LLM providers**: **Regolo.ai** and **Mistral** (free tier, OpenAI-compatible APIs). You create the account, generate your key, put it in `.env`.
- A **personal token for our APIs**, from the platform dashboard: it authenticates your calls and identifies them, so we can measure your agent's efficiency.

## 3. What you build

1. **The agent (the brain)** - a loop that receives the request, decides which sources it needs, makes targeted API calls, queries your knowledge base and composes the answer or the artifact.
2. **The knowledge base (RAG)** - you build it over the provided documents. It is one of the agent's tools, next to the APIs.
3. **The public endpoint** - `POST /ask` with the starter's frozen schema; it is what the evaluation system queries.
4. **A working UI with a knowledge graph** - you build it and it **must work end-to-end**: a user opens it and gets answers without friction. It must include a **graph visualization** of the company's materials/knowledge (the network of customers, suppliers, products, materials and how they connect). This is a required deliverable, not a nice-to-have.

## 4. What is fixed and what is free

**Fixed:**
- the endpoint schema: `POST /ask` with `{question}` -> `{answer, sources, verticale, artifact_url?}` - already wired in the starter;
- our APIs are read-only and require the auth header;
- the only data sources are the ones we provide: no invented or external data.

**Free:**
- the agent architecture and orchestration strategy;
- the LLM (any model on Regolo.ai or Mistral);
- how you build the RAG;
- the UI design, stack and layout (the graph view is required, the look is yours);
- how you optimize your calls.

## 5. Our APIs (in short)

Full reference in `API.md`. In summary:

- **CRM** - customers, opportunities, orders, invoices (structured data, filters).
- **Call logs** - calls with **full transcripts**: long text, to be extracted surgically (search/pagination) instead of downloaded whole.
- **ERP / production** - lots, inventory, suppliers, bills of materials (BOM), shipments.

All require the `Authorization` header with **your token**. Your calls are counted server-side: how many you make and how much data you download feed the **efficiency** score (section 6). The right targeted call beats downloading everything.

## 6. How you are evaluated

Three levels, from fully automated to fully human.

**Level 1 - automated evaluation.** A set of **~45 hidden requests** is sent to your endpoint. An automated judge compares your answers against an **answer key** we prepared.
- What weighs most is **completeness of the requested data** (did you fetch the right facts?); prose quality matters less.
- **Inventing a wrong fact costs more** than an honest "not available" (some requests are traps).
- **Efficiency** (calls to our APIs, data downloaded - measured server-side on your token) counts as a secondary criterion.
- Each answer must arrive within **30 seconds**: over that, the request counts as wrong.
- The top projects move on to Level 2.

**Level 2 - human evaluation.** For the top projects, a jury scores what the automated layer cannot, on **three explicit criteria**:
1. **Functioning & usability** - the app works end-to-end and is pleasant to use: a user gets answers without friction.
2. **Wow & knowledge graph** - the graph visualization of the company's materials/knowledge and the overall visual impact (the "wow" factor).
3. **Quality of the deliverables** - the generated artifacts (presentations, documents, PDFs, Excel files) are correct and presentable to a client as is.

A working, polished UI with a strong graph view is exactly what pays off here.

**Level 3 - final pitch.** The top 3 finalists present their company brain live; the jury picks the winner.

## 7. Self-test

Two tools to verify, throughout the day, that your system answers correctly:

- the **12 sample requests with answers** in the starter (`SAMPLE_QUESTIONS.md`);
- the platform **self-test**: it runs a battery of requests against your deployed endpoint and returns a score with feedback. Use it in a loop: see where you fail, fix, rerun. The people who run this cycle most end up highest.

The platform also offers an **endpoint check** that validates the `/ask` contract (schema, no-auth, latency) before you submit.

## 8. Deploy

You publish the app to **Railway** as a **single service**, free for the day ($5 trial, no credit card).
- Locally you work natively (`uv`) or with the provided fallback `docker-compose` (`DOCKER.md`).
- In the cloud you don't write a Dockerfile: Railway builds on its own (Railpack + the `railway.json` already in the starter).
- Deploy to a **European region**: the 30-second limit per answer includes network travel, so a closer server leaves more time for real work.
- Step-by-step guide in `DEPLOY.md`, including a ready-made prompt to paste into Cursor. **Do your first deploy around hour 3**, not in the last hour.

## 9. What you submit

- The **public URL of your endpoint** (the one the evaluation system queries).
- Your **code repo** (for archive and verification - a GitHub link or a zip is fine, GitHub is not required) and a **short description** (~200 words) of your approach.
- **Deadline: 17:00** (end of the work session).

> Main risk: if your app is unreachable when the automated evaluation starts, you lose the Level 1 points. Deploy early and test.

## 10. Rules

- **Individual**: you work alone.
- **GitHub allowed** (but not required: the deploy goes via CLI).
- Runtime model **via Regolo.ai or Mistral** (free tier).
- The **only data sources** are our APIs and the provided documents: no external or invented data.
- The **endpoint schema** must stay exactly as in the starter.
- **Never share or commit credentials** (API token, LLM keys).

## 11. The day

| Time | What |
| --- | --- |
| 9:30 - 10:00 | Meetup and coffee |
| 10:15 - 11:00 | Kickoff and intro (plenary briefing, Q&A) |
| 11:00 - 13:30 | Build time |
| 13:30 - 14:30 | Lunch break (self-service) |
| 14:30 - 17:00 | Build time |
| 17:00 | Project submission deadline |
| 17:00 - 18:30 | Judging (automated evaluation + jury review) |
| 18:30 - 19:00 | Pitch time for the top 3 |
| 19:00 - 19:30 | Winners announcement and awards |
| 19:30 - 20:00 | Networking aperitivo |

> Internal timings may shift slightly on the day.

## 12. Strategy

- **MVP first**: get the agent answering one simple request end-to-end, then extend to more sources and to the traps.
- **Routing**: the value is in understanding which source is needed. Design the agent to choose well.
- **Pagination**: list endpoints return 50 items by default; for aggregates check `pagination.total` and page through, or the aggregate comes out wrong.
- **Arithmetic in code**: do sums and counts in Python, not in the prompt.
- **Surgical extraction**: on long transcripts don't download everything - search for the useful part.
- **Latency as a constraint**: a loop with many calls is slow; balance depth and time.
- **Self-test in a loop**: it is the fastest way up the leaderboard.
- **Deploy early**: surface infrastructure issues with hours of buffer.

## 13. FAQ

**Do I need to know how to code?** Yes, it is a technical challenge. Cursor and a frontier LLM accelerate you a lot, but you need solid architectural judgment.

**Can I use any model?** Yes, any model on Regolo.ai or Mistral (free tier) that supports tool calling. List the live ones with `GET {LLM_BASE_URL}/models` and pick one - choosing well is part of the challenge.

**Does the UI count for the score?** Yes. It must work end-to-end and include a knowledge graph of the company's materials. For the top projects the jury grades how usable and polished it is, the graph view and the overall wow factor (Level 2).

**What happens if the agent invents a fact?** Penalty. Better to answer "not available" when the information is not in the sources.

**How do I deliver docx/pptx/pdf/xlsx files?** Your backend generates them and serves them from `/files/`; the response schema has the `artifact_url` field. The pattern is already wired in the starter. Excel (xlsx) is supported too: it is great for tabular deliverables (e.g. a purchasing sheet of raw materials below minimum stock, with a sheet per section).

**Can I add libraries or change the stack?** Yes, as long as the endpoint schema stays as in the starter and the app deploys to Railway.
