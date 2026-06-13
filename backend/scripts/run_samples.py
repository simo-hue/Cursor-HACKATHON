from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

import httpx


@dataclass
class Sample:
    number: int
    question: str
    verticale: str
    check: Callable[[dict], bool]
    api_required: bool = True


def contains_all(*needles: str) -> Callable[[dict], bool]:
    def check(payload: dict) -> bool:
        text = str(payload.get("answer", "")).lower().replace(",", "")
        return all(needle.lower().replace(",", "") in text for needle in needles)

    return check


SAMPLES = [
    Sample(1, "How many open opportunities does Primato Supermercati S.p.A. (CUST-0132) have, and what is their total value?", "crm", contains_all("4", "740000", "EUR")),
    Sample(2, "Is SKU PAS-PEN-500 (Penne Rigate n.73 - 500g box) below its minimum stock? Give the on-hand quantity.", "erp", contains_all("yes", "462", "2000")),
    Sample(3, "In the last call with NordSpesa S.p.A. (CUST-0137), what was the complaint and which lot did it concern?", "calls", contains_all("broken pasta", "LOT-2026-0658", "CALL-58020", "2026-06-06", "Fettuccine", "PAS-FET-500")),
    Sample(4, "What is the shelf life (TMC) and the declared allergens for Spaghetti n.5 - 500g box (SKU PAS-SPA-500)?", "kb", contains_all("36 months", "gluten", "soy", "mustard"), False),
    Sample(5, "Does the complaint from that last NordSpesa S.p.A. call qualify for a return under the quality policy?", "calls", contains_all("yes", "15", "replacement", "credit note")),
    Sample(6, "Total value of opportunities in the negotiation stage, grouped by customer channel (GDO / distributor / horeca).", "crm", contains_all("3301000", "22 opportunities", "1931000", "12 opportunities", "3040000", "18 opportunities")),
    Sample(7, "What is the profit margin on lot LOT-2026-0658?", "erp", contains_all("not available", "profit margin")),
    Sample(8, "What is the status of the order for Supermercati Bianchi?", "crm", contains_all("could not find", "Supermercati Bianchi")),
    Sample(9, "Generate a 4-slide HTML deck for the sales rep visiting Primato Supermercati S.p.A. (CUST-0132): profile, open deals, order/lot status, recent call complaints.", "crm", lambda p: "<html" in p.get("answer", "").lower() and p.get("artifact_url") is None),
    Sample(10, "Which semolina does SKU PAS-SPA-500 use (per its bill of materials), which supplier provides it, and is that raw material below minimum stock?", "erp", contains_all("RAW-SEM-003", "Molino San Giorgio", "not below")),
    Sample(11, "Across ALL recorded calls, count how many quality complaints concern the defect 'broken pasta'. Give the exact number.", "calls", contains_all("80", "9")),
    Sample(12, "GranMercato S.p.A. (also written 'Gran Mercato S.p.A.' in some notes) asked about the price of Fusilli n.98 (PAS-FUS-500). A call mentions one figure and the official 2026 wholesale price list mentions another. Which is the correct list price, and why?", "kb", contains_all("8.07", "DOC-015", "authoritative")),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    has_token = bool(os.getenv("MOCK_API_TOKEN"))
    hostname = urlparse(base_url).hostname
    is_local = hostname in {"localhost", "127.0.0.1", "::1"}
    passed = failed = skipped = 0
    with httpx.Client(timeout=args.timeout) as client:
        for sample in SAMPLES:
            if sample.api_required and not has_token and is_local:
                print(f"SKIP {sample.number:02d} - MOCK_API_TOKEN is not configured")
                skipped += 1
                continue
            try:
                response = client.post(f"{base_url}/ask", json={"question": sample.question})
                payload = response.json()
                schema_ok = (
                    response.status_code == 200
                    and set(("answer", "sources", "verticale", "artifact_url")) <= payload.keys()
                    and payload.get("verticale") == sample.verticale
                )
                ok = schema_ok and sample.check(payload)
            except Exception as exc:
                print(f"FAIL {sample.number:02d} - {exc}")
                failed += 1
                continue
            if ok:
                print(f"PASS {sample.number:02d} [{sample.verticale}]")
                passed += 1
            else:
                print(f"FAIL {sample.number:02d} [{sample.verticale}] {payload}")
                failed += 1
    print(f"\nSummary: {passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
