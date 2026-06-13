from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .normalizers import extract_ids, is_artifact_request, normalize_text
from .schemas import Verticale


@dataclass
class FastRoute:
    handler: str
    verticale: Verticale
    confidence: float
    entities: dict[str, list[str]] = field(default_factory=dict)
    artifact_type: str | None = None
    classification: dict[str, Any] = field(default_factory=dict)


def classify_fast(question: str) -> FastRoute:
    q = normalize_text(question)
    entities = extract_ids(question)
    artifact, artifact_type = is_artifact_request(question)
    if artifact:
        dominant: Verticale = "crm" if any(
            term in q for term in ("sales rep", "customer", "opportunit", "account")
        ) else "erp" if any(
            term in q for term in ("inventory", "stock", "procurement", "below minimum")
        ) else "kb"
        return FastRoute("artifact", dominant, 0.98, entities, artifact_type)

    if any(term in q for term in ("profit margin", "gross margin", "net margin", "profitability")) or (
        "lot" in q and any(term in q for term in ("production cost", "manufacturing cost", "cost of"))
    ):
        return FastRoute("erp_margin_trap", "erp", 0.99, entities)
    if entities["opportunity_ids"]:
        return FastRoute("crm_opportunity_lookup", "crm", 0.98, entities)
    if "negotiation" in q and any(term in q for term in ("grouped by", "by customer channel", "gdo")):
        return FastRoute("crm_negotiation_by_channel", "crm", 0.99, entities)
    if "open opportunit" in q and any(term in q for term in ("how many", "total value", "worth")):
        return FastRoute("crm_open_opportunities", "crm", 0.99, entities)
    if any(term in q for term in ("account brief", "customer profile", "account profile")):
        return FastRoute("crm_account_brief", "crm", 0.95, entities)
    if entities["customer_ids"] and any(
        term in q for term in ("customer", "account", "who is", "tell me about")
    ):
        return FastRoute("crm_customer_lookup", "crm", 0.94, entities)
    if "customer" in q and any(
        term in q for term in ("find", "exists", "named", "called", "tell me about")
    ):
        return FastRoute("crm_customer_lookup", "crm", 0.9, entities)
    if "price" in q and any(
        term in q for term in ("call mentions", "phone call", "authoritative", "disagree", "conflict")
    ):
        return FastRoute("calls_price_conflict", "kb", 0.98, entities)
    if any(term in q for term in ("qualify for a return", "eligible for a return", "under the quality policy")):
        return FastRoute("calls_return_qualification", "calls", 0.99, entities)
    if "across all" in q and "call" in q and any(term in q for term in ("count", "how many", "defect")):
        return FastRoute("calls_defect_count", "calls", 0.99, entities)
    if "call" in q and any(term in q for term in ("complaint", "which lot", "last call", "latest call")):
        return FastRoute("calls_latest_complaint", "calls", 0.97, entities)
    if any(term in q for term in ("bill of materials", "bom", "which semolina", "raw material")) and (
        entities["skus"] or "sku" in q
    ):
        return FastRoute("erp_bom_chain", "erp", 0.98, entities)
    if entities["supplier_ids"] or (
        "supplier" in q and any(term in q for term in ("provide", "material", "supplies"))
    ):
        return FastRoute("erp_supplier_materials", "erp", 0.91, entities)
    if any(term in q for term in ("below minimum", "below its minimum", "minimum stock", "on hand", "on-hand")):
        return FastRoute("erp_inventory", "erp", 0.98, entities)
    if entities["lot_ids"] or (
        "lot" in q and any(term in q for term in ("status", "production", "blocked", "related"))
    ) or (
        entities["skus"] and "production" in q and "status" in q
    ):
        return FastRoute("erp_lot_status", "erp", 0.92, entities)
    if any(term in q for term in ("shelf life", "tmc", "allergen", "may contain", "product spec")):
        return FastRoute("kb_product_spec", "kb", 0.99, entities)
    if "price" in q and (entities["skus"] or "list price" in q):
        return FastRoute("kb_price", "kb", 0.94, entities)
    if "shipment" in q and any(term in q for term in ("status", "late", "delayed", "delivery")):
        return FastRoute("erp_shipment_status", "erp", 0.95, entities)
    if any(term in q for term in ("order status", "status of the order", "invoice", "shipment")):
        return FastRoute("crm_order_status", "crm", 0.95, entities)
    if any(
        term in q
        for term in (
            "policy",
            "procedure",
            "haccp",
            "quality",
            "label",
            "delivery window",
            "sustainability",
            "cleaning",
            "metal detection",
            "supplier agreement",
        )
    ):
        return FastRoute("kb_generic", "kb", 0.86, entities)

    loose = loose_route(q, entities)
    if loose is not None:
        return loose
    return FastRoute("generic", "crm", 0.2, entities)


# Keyword groups used by the loose matcher and the LLM-hint mapping. These are
# intentionally broad (synonyms, natural phrasings) because they only run after
# the strict rules above miss — the goal is to reach the right handler for
# "same shape, different wording" questions instead of abstaining.
_TRAP_TERMS = (
    "profit margin", "gross margin", "net margin", "profitability", "markup",
    "profit", "cogs", "cost of goods",
)
_CRM_TERMS = (
    "customer", "client", "account", "opportunit", "deal", "pipeline",
    "negotiation", "order", "invoice", "won", "lost",
)
_ERP_TERMS = (
    "stock", "inventory", "on hand", "on-hand", "warehouse", "supplier",
    "semolina", "raw material", "bill of material", "bom", "lot", "production",
    "shipment", "ingredient", "minimum",
)
_CALLS_TERMS = (
    "call", "complaint", "complain", "transcript", "defect", "phone", "spoke",
    "conversation",
)
_KB_TERMS = (
    "shelf life", "tmc", "allergen", "may contain", "spec", "policy",
    "procedure", "haccp", "label", "capitolato", "sustainab", "ingredient",
    "expiry", "expiration", "price", "list price",
)


def _has_cost_trap(q: str) -> bool:
    if any(term in q for term in _TRAP_TERMS):
        return True
    return "cost" in q and any(
        term in q for term in ("lot", "produc", "unit", "make", "manufactur", "per kg", "per carton")
    )


def pick_handler(q: str, verticale: Verticale, entities: dict[str, list[str]]) -> str:
    """Choose the most likely concrete handler for a (verticale, question) pair.

    Used by both the deterministic loose matcher and the LLM-hint fallback. Each
    verticale has a sensible default so a bare, paraphrased question still reaches
    a real data lookup rather than abstaining.
    """
    if _has_cost_trap(q):
        return "erp_margin_trap"
    if verticale == "crm":
        if entities.get("opportunity_ids"):
            return "crm_opportunity_lookup"
        if "negotiation" in q and any(
            t in q for t in ("channel", "gdo", "distributor", "horeca", "group", "segment", "by customer")
        ):
            return "crm_negotiation_by_channel"
        if any(t in q for t in ("opportunit", "deal", "pipeline")):
            return "crm_open_opportunities"
        if any(t in q for t in ("order", "invoice", "shipment", "delivery")):
            return "crm_order_status"
        if any(t in q for t in ("brief", "profile", "summary", "overview", "dossier", "everything about")):
            return "crm_account_brief"
        return "crm_customer_lookup"
    if verticale == "erp":
        if any(
            t in q
            for t in (
                "bom", "bill of material", "semolina", "raw material", "ingredient",
                "made of", "made from", "goes into", "composed of", "recipe", "durum",
            )
        ):
            return "erp_bom_chain"
        if entities.get("supplier_ids") or any(
            t in q for t in ("supplier", "supplies", "provided by", "provides", "vendor")
        ):
            return "erp_supplier_materials"
        if any(
            t in q
            for t in ("stock", "inventory", "on hand", "on-hand", "minimum", "quantity", "warehouse", "available")
        ):
            return "erp_inventory"
        if entities.get("lot_ids") or "lot" in q or any(t in q for t in ("production", "produced", "manufactur")):
            return "erp_lot_status"
        if "shipment" in q or "delivery" in q:
            return "erp_shipment_status"
        return "erp_inventory"
    if verticale == "calls":
        if any(t in q for t in ("qualify", "eligible", "return", "refund", "credit note", "warranty")):
            return "calls_return_qualification"
        if any(t in q for t in ("across all", "how many", "count", "number of", "total number")):
            return "calls_defect_count"
        if "price" in q:
            return "calls_price_conflict"
        return "calls_latest_complaint"
    if any(
        t in q
        for t in ("shelf life", "tmc", "allergen", "may contain", "spec", "expiry", "expiration")
    ):
        return "kb_product_spec"
    if "price" in q or "list price" in q:
        return "kb_price"
    return "kb_generic"


def _infer_verticale(q: str, entities: dict[str, list[str]]) -> Verticale | None:
    """Best-effort deterministic verticale guess from entity ids + keywords.

    Returns None when the signal is weak or ambiguous, so the LLM can decide.
    """
    if entities.get("lot_ids") or entities.get("supplier_ids"):
        return "erp"
    if entities.get("opportunity_ids"):
        return "crm"
    if entities.get("call_ids"):
        return "calls"
    scores = {
        "crm": sum(1 for t in _CRM_TERMS if t in q),
        "erp": sum(1 for t in _ERP_TERMS if t in q),
        "calls": sum(1 for t in _CALLS_TERMS if t in q),
        "kb": sum(1 for t in _KB_TERMS if t in q),
    }
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return None
    # Require a clear winner; ties go to the LLM.
    ordered = sorted(scores.values(), reverse=True)
    if len(ordered) > 1 and ordered[0] == ordered[1]:
        return None
    return best  # type: ignore[return-value]


def loose_route(q: str, entities: dict[str, list[str]]) -> FastRoute | None:
    """Deterministic broad matcher for paraphrased questions (no LLM, no latency).

    Runs only after the strict rules miss. Returns a concrete handler at moderate
    confidence, or None when the verticale is unclear (deferring to the LLM).
    """
    if _has_cost_trap(q):
        return FastRoute("erp_margin_trap", "erp", 0.8, entities)
    verticale = _infer_verticale(q, entities)
    if verticale is None:
        return None
    handler = pick_handler(q, verticale, entities)
    route_verticale: Verticale = "kb" if handler == "calls_price_conflict" else verticale
    return FastRoute(handler, route_verticale, 0.6, entities)


def route_from_hint(
    question: str,
    classification: dict[str, Any],
    entities: dict[str, list[str]],
) -> FastRoute | None:
    """Map an LLM classification into a concrete handler route.

    The model supplies the verticale (and a coarse intent / artifact flag); the
    deterministic ``pick_handler`` then selects the specific handler so even a
    naturally-worded structured query reaches a real data lookup.
    """
    hint = classification.get("verticale_hint")
    if hint not in {"crm", "erp", "calls", "kb"}:
        return None
    q = normalize_text(question)
    artifact_type = classification.get("artifact_type")
    if classification.get("intent") == "artifact" or artifact_type in {
        "html", "markdown", "pdf", "xlsx", "docx", "pptx",
    }:
        return FastRoute("artifact", hint, 0.9, entities, artifact_type or "html")
    handler = pick_handler(q, hint, entities)  # type: ignore[arg-type]
    route_verticale: Verticale = "kb" if handler == "calls_price_conflict" else hint  # type: ignore[assignment]
    return FastRoute(handler, route_verticale, 0.78, entities, classification=classification)


def needs_llm_classification(question: str, route: FastRoute) -> bool:
    return route.handler == "generic" and route.confidence < 0.5 and len(question) > 8
