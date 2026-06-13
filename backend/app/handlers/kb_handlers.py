from __future__ import annotations

from ..evidence import EvidencePack
from ..kb import extract_price_for_sku, extract_product_spec, relevant_excerpt
from ..normalizers import extract_ids, normalize_text
from . import Context


def handle_product_spec(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)
    query = ids["skus"][0] if ids["skus"] else question
    hits = ctx.kb.search_product(query)
    if not hits:
        return EvidencePack(
            False,
            "kb",
            {"answer": f"No product specification was found for {query}."},
            [],
            confidence=0.95,
        )
    hit = hits[0]
    spec = extract_product_spec(hit.doc.text)
    if not spec.get("shelf_life") and not spec.get("allergens"):
        return EvidencePack(
            False,
            "kb",
            {"answer": f"{hit.doc.doc_id} did not contain the requested product fields."},
            [hit.doc.doc_id],
            confidence=0.9,
        )
    allergens = ", ".join(spec["allergens"]) if spec["allergens"] else "none declared"
    may_contain = ", ".join(spec["may_contain"]) if spec["may_contain"] else "none declared"
    answer = (
        f"{spec['product']} ({spec['sku']}): shelf life {spec['shelf_life']}. "
        f"Declared allergens: {allergens}. May contain: {may_contain}."
    )
    return EvidencePack(
        True,
        "kb",
        {"answer": answer, "spec": spec, "document": hit.doc.doc_id},
        [hit.doc.doc_id],
        confidence=0.96,
    )


def handle_price(question: str, ctx: Context) -> EvidencePack:
    skus = extract_ids(question)["skus"]
    if not skus:
        product_hits = ctx.kb.search_product(question)
        skus = [product_hits[0].doc.sku] if product_hits and product_hits[0].doc.sku else []
    if not skus:
        return EvidencePack(False, "kb", {"answer": "I could not identify a unique SKU for the price lookup."}, confidence=0.9)
    doc = ctx.kb.search_by_id("DOC-015")
    if not doc:
        return EvidencePack(False, "kb", {"answer": "The official wholesale price list DOC-015 is unavailable."}, confidence=0.98)
    price = extract_price_for_sku(doc.text, skus[0])
    if price["price"] is None:
        return EvidencePack(
            False,
            "kb",
            {"answer": f"SKU {skus[0]} is not listed in the official 2026 wholesale price list."},
            ["DOC-015"],
            confidence=0.98,
        )
    answer = (
        f"The official 2026 wholesale list price for {skus[0]}"
        f"{f' ({price['product']})' if price['product'] else ''} is "
        f"{price['price']:.2f} EUR per carton of 20 retail units, excluding VAT."
    )
    return EvidencePack(True, "kb", {"answer": answer, "price": price}, ["DOC-015"], confidence=0.99)


def handle_generic_kb(question: str, ctx: Context) -> EvidencePack:
    doc_ids = extract_ids(question)["doc_ids"]
    normalized = normalize_text(question)
    authoritative_doc_id = None
    if (
        "return" in normalized
        and any(term in normalized for term in ("policy", "quality", "defect", "eligible"))
    ):
        authoritative_doc_id = "DOC-011"
    docs = (
        [ctx.kb.search_by_id(doc_ids[0])]
        if doc_ids
        else [ctx.kb.search_by_id(authoritative_doc_id)]
        if authoritative_doc_id
        else []
    )
    hits = ctx.kb.search(question, top_k=3)
    if not docs or not docs[0]:
        docs = [hit.doc for hit in hits if hit.score > 0.2]
    docs = [doc for doc in docs if doc]
    if not docs:
        return EvidencePack(
            False,
            "kb",
            {"answer": "I could not find this information in the provided knowledge-base documents."},
            [],
            confidence=0.9,
        )
    excerpts = []
    sources = []
    for doc in docs[:2]:
        excerpt = relevant_excerpt(doc.text, question)
        if excerpt:
            excerpts.append(f"{doc.title}: {excerpt}")
            sources.append(doc.doc_id)
    if not excerpts:
        return EvidencePack(
            False,
            "kb",
            {"answer": f"The closest document was {docs[0].doc_id}, but it did not contain a reliable answer to the question."},
            [docs[0].doc_id],
            confidence=0.88,
        )
    return EvidencePack(
        True,
        "kb",
        {"answer": " ".join(excerpts)},
        sources,
        confidence=0.78,
    )
