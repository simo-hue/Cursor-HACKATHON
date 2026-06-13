"""Temporary diagnostic: probe router robustness on paraphrased questions.

Hits a running /ask and reports routed verticale + whether a real source was
used (vs. a generic abstention), to find shapes that fail to reach a handler.
"""
from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"

PROBES = [
    # CRM — reworded, some name-only (no explicit ID)
    "Tell me about Primato Supermercati.",
    "What's the total pipeline value of Primato Supermercati's deals still in play?",
    "Which sales channel is customer CUST-0137 in?",
    "List every negotiation-stage deal broken down by the customer's channel.",
    # ERP
    "How much PAS-PEN-500 do we currently have in stock?",
    "What semolina goes into making PAS-SPA-500, and who supplies it?",
    "Give me the production status of lot LOT-2026-0658.",
    "Which materials does supplier SUP-001 provide?",
    # Calls
    "What did NordSpesa complain about most recently?",
    "How many recorded calls reported broken pasta?",
    # KB
    "What are the allergens in Spaghetti n.5?",
    "What's our policy on product returns?",
    # Global-ish shapes
    "How many customers do we have in total?",
]


def main() -> None:
    with httpx.Client(timeout=30.0) as client:
        for q in PROBES:
            try:
                r = client.post(f"{BASE}/ask", json={"question": q})
                p = r.json()
            except Exception as exc:  # noqa: BLE001
                print(f"ERR  {q[:55]:55} {exc}")
                continue
            ans = str(p.get("answer", ""))
            vert = p.get("verticale")
            srcs = p.get("sources") or []
            low = ans.lower()
            abstained = (not srcs) and (
                "could not identify" in low
                or "not available from" in low
                or "not configured" in low
            )
            flag = "ABSTAIN" if abstained else ("OK " if srcs else "?  ")
            print(f"{flag} [{str(vert):5}] src={len(srcs)} | {q[:52]}")
            print(f"        -> {ans[:150].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()
