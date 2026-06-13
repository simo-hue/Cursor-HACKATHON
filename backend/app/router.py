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
    return FastRoute("generic", "crm", 0.2, entities)


def needs_llm_classification(question: str, route: FastRoute) -> bool:
    return route.handler == "generic" and route.confidence < 0.5 and len(question) > 8
