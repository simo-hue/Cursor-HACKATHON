# Sample questions

12 public examples, representative of the hidden evaluation set, **with their reference answers** so you can check yourself. The hidden questions use different entities, but the same shapes: direct lookups, aggregates, multi-source chains, traps, generation.

Also use the platform **self-test** (dashboard): it runs a battery against your deployed endpoint and gives you scored feedback.

---

**1. [crm / aggregate]** How many open opportunities does Primato Supermercati S.p.A. (CUST-0132) have, and what is their total value?

> 4 open opportunities (qualification + negotiation) worth 740,000 EUR in total.

**2. [erp / single source]** Is SKU PAS-PEN-500 (Penne Rigate n.73 - 500g box) below its minimum stock? Give the on-hand quantity.

> Yes, below minimum. On-hand 462 cartons vs minimum 2000.

**3. [calls / single source]** In the last call with NordSpesa S.p.A. (CUST-0137), what was the complaint and which lot did it concern?

> A quality complaint for broken pasta, on lot LOT-2026-0658 (Fettuccine n.205 - 500g box). Call CALL-58020.

**4. [kb / single source]** What is the shelf life (TMC) and the declared allergens for Spaghetti n.5 - 500g box (SKU PAS-SPA-500)?

> Shelf life 36 months. Allergens: gluten. May contain: soy, mustard.

**5. [calls / multi source]** Does the complaint from that last NordSpesa S.p.A. call qualify for a return under the quality policy?

> Yes: "broken pasta" is covered, within the 15-day window, with lot number and photo. Outcome: replacement or credit note; lot blocked.

**6. [crm / aggregate]** Total value of opportunities in the negotiation stage, grouped by customer channel (GDO / distributor / horeca).

> GDO: 3,301,000 EUR; distributor: 1,931,000 EUR; horeca: 3,040,000 EUR.

**7. [erp / trap]** What is the profit margin on lot LOT-2026-0658?

> Not available: cost and profit margin are not stored on lots or anywhere in the sources. The honest answer states the figure is not available.

**8. [crm / trap]** What is the status of the order for Supermercati Bianchi?

> There is no customer named "Supermercati Bianchi" in the CRM. The honest answer surfaces that the customer does not exist.

**9. [crm / generation]** Generate a 4-slide HTML deck for the sales rep visiting Primato Supermercati S.p.A. (CUST-0132): profile, open deals, order/lot status, recent call complaints.

> An HTML deck (~4 slides), inline in `answer`: profile (GDO, Verona); the 4 open deals (740,000 EUR); order/lot status; complaints (none on record for this customer).

**10. [erp / multi source]** Which semolina does SKU PAS-SPA-500 use (per its bill of materials), which supplier provides it, and is that raw material below minimum stock?

> RAW-SEM-003 (Durum semolina - premium), supplied by Molino San Giorgio; it is not below minimum stock.

**11. [calls / aggregate]** Across ALL recorded calls (there are 80 - you must page through the entire call log, do not stop at the first page), count how many quality complaints concern the defect 'broken pasta'. Give the exact number.

> 9 calls report a 'broken pasta' defect.

**12. [kb / multi source]** GranMercato S.p.A. (also written 'Gran Mercato S.p.A.' in some notes) asked about the price of Fusilli n.98 (PAS-FUS-500). A call mentions one figure and the official 2026 wholesale price list mentions another. Which is the correct list price, and why? (When a phone call and an official document disagree, the official document is authoritative.)

> 8.07 EUR per carton. The official 2026 wholesale price list (DOC-015) is authoritative; the 8.50 EUR figure mentioned in the call is incorrect.

---

Notes:

- Traps (7, 8) are by design: the data does not exist. Inventing a number or a status scores heavily negative; a specific, honest "not available" scores full marks.
- A few hidden generation questions ask for a **downloadable file (docx / pptx / pdf / xlsx)** instead of inline HTML - return it via `artifact_url` (see `AGENTS.md` -> Artifacts).
- The entities in these samples (Primato, NordSpesa, ...) are reserved: the hidden set asks about **other** customers, lots and SKUs. Don't hardcode.
