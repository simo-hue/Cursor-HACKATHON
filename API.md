# Al Dente mock APIs - reference

The company's data sources, exposed as read-only JSON APIs. Interactive OpenAPI docs at `{MOCK_API_BASE_URL}/docs`.

- **Base URL**: `https://aldente.yellowtest.it`
- **Auth**: `Authorization: Bearer <your token>` on every call. Your personal token is on the **platform dashboard**. Missing/invalid token -> `401 {"error": "access_denied"}`.
- **Metering**: every authenticated call is logged per participant (count, bytes, latency). Efficiency is part of the score - the right filtered call beats downloading everything.

## Pagination

All list endpoints: `?limit=&offset=` (default `limit=50`, **max 200**). Response envelope:

```json
{ "data": [ ... ], "pagination": { "offset": 0, "limit": 50, "total": 137 } }
```

Always check `pagination.total` before aggregating - the first page is rarely the whole story.

## Endpoints

| Endpoint | Main filters (exact values) |
| --- | --- |
| `GET /crm/customers` | `search`, `channel` (`GDO` / `distributor` / `horeca`), `status` (`active` / `inactive` / `prospect`) |
| `GET /crm/customers/{id}` | - |
| `GET /crm/opportunities` | `customer_id`, `stage` (`qualification` / `negotiation` / `won` / `lost`), `owner` |
| `GET /crm/orders` | `customer_id`, `status` (`open` / `in_production` / `shipped` / `delivered` / `cancelled`), `from`, `to` |
| `GET /crm/invoices` | `customer_id`, `status` (`unpaid` / `paid` / `overdue`), `order_id` |
| `GET /calls` | `customer_id`, `type` (`sales` / `support`), `outcome` (`complaint_open` / `follow_up` / `order_placed` / `resolved`), `from`, `to` |
| `GET /calls/{id}` | - (metadata) |
| `GET /calls/{id}/transcript` | `search`, `speaker`, `offset`, `limit` (over segments) |
| `GET /erp/production-orders` | `customer_id`, `status` (`planned` / `in_progress` / `done` / `blocked`), `sku`, `from`, `to` |
| `GET /erp/inventory` | `type` (`finished_good` / `raw_material`), `below_min` (`true`), `search` |
| `GET /erp/suppliers` | `search`, `category` (`semolina` / `wheat` / `packaging` / `labels` / `ink` / `logistics`) |
| `GET /erp/bom` | `sku` (bill of materials of a finished SKU) |
| `GET /erp/shipments` | `customer_id`, `order_id`, `status` (`in_transit` / `delivered` / `delayed`) |
| `GET /health` | - (no auth) |

Filters are **exact-match and case-sensitive** (`channel=GDO` works, `channel=gdo` returns an empty list - no error). Date filters (`from` / `to`) take ISO dates (`YYYY-MM-DD`).

**Errors**: `401` (`access_denied`), `404` (`not_found`), `422` (bad parameters, e.g. non-numeric `limit`).

## Transcripts: extract, don't download

`GET /calls/{id}/transcript` is the long-text source: up to hundreds of segments per call (`total_segments` in the call metadata). Use `?search=<term>` and/or `?speaker=` + `offset/limit` to pull only the relevant segments. Downloading full transcripts burns time, tokens and your efficiency score.

Note: its response shape differs from the other lists - segments live under `segments`, not `data`:

```json
{ "call_id": "CALL-58020", "segments": [ {"speaker": "...", "text": "..."} ], "pagination": { ... } }
```

When `search`/`speaker` filters are active, `pagination.total` counts the **filtered** segments.

## ID conventions

| Entity | Format | Example |
| --- | --- | --- |
| Customer | `CUST-####` | `CUST-0132` |
| Opportunity | `OPP-####` | `OPP-2031` |
| Order | `ORD-2026-####` | `ORD-2026-0517` |
| Production lot | `LOT-2026-####` | `LOT-2026-0876` |
| Finished product SKU | `PAS-XXX-###` | `PAS-SPA-500` |
| Raw material SKU | `RAW-XXX-###` | `RAW-SEM-001` |
| Supplier | `SUP-###` | `SUP-014` |
| Call | `CALL-#####` | `CALL-58213` |
| KB document | `DOC-###` | `DOC-007` |

Cross-source links are real: orders reference customers, production lots reference orders and SKUs, BOM rows link finished SKUs to raw materials, raw materials link to suppliers, calls reference customers and lots. Multi-hop questions follow these chains.

## The knowledge base is NOT an API

The 35 documents in `backend/data/kb/` (specs, policies, price list, capitolati) are files in this repo. Retrieval over them is yours to build - see `AGENTS.md`.
