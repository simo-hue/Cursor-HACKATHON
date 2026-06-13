from __future__ import annotations

from ..evidence import EvidencePack
from ..normalizers import extract_ids, normalize_text
from ..router import FastRoute
from . import Context
from .kb_handlers import handle_generic_kb


def handle_generic(question: str, route: FastRoute, ctx: Context) -> EvidencePack:
    hint = str(route.classification.get("verticale_hint") or "")
    if hint == "kb" or extract_ids(question)["doc_ids"]:
        return handle_generic_kb(question, ctx)
    q = normalize_text(question)
    if any(term in q for term in ("policy", "procedure", "product", "allergen", "quality")):
        return handle_generic_kb(question, ctx)
    return EvidencePack(
        False,
        route.verticale,
        {
            "answer": (
                "Not available from the provided Al Dente sources: I could not identify "
                "a reliable CRM, ERP, call-log, or knowledge-base lookup for this request."
            )
        },
        [],
        confidence=0.92,
    )
