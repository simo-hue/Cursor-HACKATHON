from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ..api_client import APIError
from ..evidence import EvidencePack
from ..kb import extract_price_for_sku, extract_return_policy_terms
from ..normalizers import (
    extract_ids,
    first_value,
    normalize_text,
    record_id,
    sort_records_newest,
)
from . import (
    Context,
    ResolvedEntity,
    customer_id,
    customer_name,
    missing_customer_answer,
    resolve_customer,
    unwrap_single,
)

COVERED_DEFECTS = ("broken pasta", "bloated packs", "foreign body", "mislabeling")


def _call_id(row: dict[str, Any]) -> str:
    return record_id(row, "call_id")


def _call_blob(row: dict[str, Any]) -> str:
    return " ".join(
        f"{key} {value}" for key, value in row.items() if value is not None
    )


def _latest_complaint_call(question: str, ctx: Context) -> tuple[Any, dict[str, Any] | None]:
    call_ids = extract_ids(question)["call_ids"]
    if call_ids:
        call = unwrap_single(ctx.api.get_call(call_ids[0]))
        cid = str(first_value(call, "customer_id", default=""))
        customer: dict[str, Any] = {"customer_id": cid, "name": cid or "Unknown customer"}
        if cid:
            try:
                customer = unwrap_single(ctx.api.get_customer(cid))
            except Exception:
                pass
        return ResolvedEntity(True, customer, cid, 0.99), call
    resolved = resolve_customer(question, ctx)
    if not resolved.found or not resolved.record:
        return resolved, None
    cid = customer_id(resolved.record)
    calls = ctx.api.list_calls(customer_id=cid, type="support")
    if not calls:
        calls = ctx.api.list_calls(customer_id=cid)
    calls = sort_records_newest(calls)
    preferred = [
        row
        for row in calls
        if str(first_value(row, "outcome", default="")) in {"complaint_open", "resolved"}
        or "complaint" in normalize_text(_call_blob(row))
    ]
    return resolved, (preferred or calls)[0] if calls else None


def _targeted_segments(call_id: str, ctx: Context, terms: list[str]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for term in terms:
        for segment in ctx.api.search_transcript(call_id, search=term, limit=30):
            key = (
                str(segment.get("speaker", "")),
                str(segment.get("text", "")),
            )
            if key not in seen:
                seen.add(key)
                segments.append(segment)
    return segments


def _segments_text(segments: list[dict[str, Any]]) -> str:
    return " ".join(str(first_value(row, "text", "content", default="")) for row in segments)


def _extract_defect(text: str) -> str | None:
    normalized = normalize_text(text)
    for defect in COVERED_DEFECTS:
        if defect in normalized:
            return defect
    match = re.search(
        r"(?:complaint|problem|defect|issue)(?:\s+(?:for|about|is|of))?\s+([a-z][a-z -]{2,40})",
        normalized,
    )
    return match.group(1).strip() if match else None


def handle_latest_complaint(question: str, ctx: Context) -> EvidencePack:
    resolved, call = _latest_complaint_call(question, ctx)
    if not resolved.found or not resolved.record:
        return EvidencePack(
            False,
            "calls",
            {"answer": missing_customer_answer(resolved)},
            ["crm/customers"],
            confidence=resolved.confidence,
        )
    if not call:
        return EvidencePack(
            False,
            "calls",
            {"answer": f"No calls were found for {customer_name(resolved.record)}."},
            ["crm/customers", "calls"],
            confidence=0.96,
        )
    cid = _call_id(call)
    metadata = _call_blob(call)
    metadata_defect = _extract_defect(metadata)
    segments = _targeted_segments(cid, ctx, [metadata_defect or "complaint"])
    text = f"{metadata} {_segments_text(segments)}"
    defect = _extract_defect(text)
    lot_id = str(first_value(call, "related_lot_id", "lot_id", default="")) or None
    if not lot_id:
        lots = re.findall(r"\bLOT-\d{4}-\d{4}\b", text.upper())
        lot_id = lots[0] if lots else None
    sku_match = re.search(r"\bPAS-[A-Z0-9-]{3,}\b", text.upper())
    product = str(first_value(call, "product_name", "product", default=""))
    if not product:
        product_match = re.search(
            r"\b([A-Z][A-Za-z0-9 .'-]+? - \d+g box)\b",
            text,
        )
        product = product_match.group(1) if product_match else ""
    description = defect or str(first_value(call, "subject", "summary", "notes", default="quality issue"))
    call_date = str(first_value(call, "date", "call_date", "datetime", default=""))
    rendered_date = call_date[:10] if call_date else ""
    answer = f"The latest relevant call with {customer_name(resolved.record)} was {cid}"
    if rendered_date:
        answer += f" on {rendered_date}"
    answer += ". "
    answer += f"The complaint concerned {description}"
    if lot_id:
        answer += f" on lot {lot_id}"
    if product:
        answer += f" for {product}"
    if sku_match:
        answer += f" (SKU {sku_match.group(0)})"
    answer += "."
    return EvidencePack(
        bool(defect and lot_id),
        "calls",
        {
            "answer": answer,
            "customer": resolved.record,
            "call": call,
            "segments": segments,
            "defect": defect,
            "lot_id": lot_id,
            "product": product,
            "sku": sku_match.group(0) if sku_match else None,
        },
        ["crm/customers", "calls", f"calls/{cid}/transcript"],
        missing=[name for name, value in (("defect", defect), ("lot number", lot_id)) if not value],
        confidence=0.96 if defect and lot_id else 0.66,
    )


def handle_return_qualification(question: str, ctx: Context) -> EvidencePack:
    complaint = handle_latest_complaint(question, ctx)
    if not complaint.facts.get("call"):
        return complaint
    policy_doc = ctx.kb.search_by_id("DOC-011")
    if not policy_doc:
        return EvidencePack(
            False,
            "calls",
            {"answer": "The complaint was found, but the returns policy DOC-011 is unavailable."},
            complaint.sources,
            confidence=0.95,
        )
    policy = extract_return_policy_terms(policy_doc.text)
    call = complaint.facts["call"]
    cid = _call_id(call)
    complaint_segments = complaint.facts.get("segments", [])
    current_text = normalize_text(
        f"{_call_blob(call)} {_segments_text(complaint_segments)}"
    )
    extra_terms: list[str] = []
    if "photo" not in current_text:
        extra_terms.append("photo")
    if not (
        re.search(r"\b\d{1,2}\s+days?\b", current_text)
        or "within the 15 day" in current_text
        or "within 15 day" in current_text
        or "last week" in current_text
    ):
        extra_terms.append("days ago")
    extra = _targeted_segments(cid, ctx, extra_terms)
    all_text = normalize_text(
        f"{_call_blob(call)} {_segments_text(complaint_segments)} {_segments_text(extra)}"
    )
    defect = complaint.facts.get("defect")
    lot_ok = bool(complaint.facts.get("lot_id"))
    photo_ok = bool(re.search(r"\bphoto\b", all_text)) and not bool(
        re.search(r"(?:no|missing|without)\s+photo|photo\s+(?:provided\s+)?false", all_text)
    )
    days_matches = [int(value) for value in re.findall(r"\b(\d{1,2})\s+days?\b", all_text)]
    days_matches.extend(
        int(value) for value in re.findall(r"days?\s+since\s+delivery\s+(\d{1,2})", all_text)
    )
    window_ok = (
        any(days <= policy["window_days"] for days in days_matches)
        or "within the 15 day" in all_text
        or "within 15 day" in all_text
        or "delivered last week" in all_text
        or "within return window true" in all_text
    )
    covered = bool(
        defect
        and any(normalize_text(defect) == normalize_text(item) for item in policy["covered_defects"])
    )
    excluded = any(normalize_text(item) in all_text for item in policy["exclusions"])
    qualifies = covered and lot_ok and photo_ok and window_ok and not excluded
    if qualifies:
        answer = (
            f"Yes. The {defect} complaint from call {cid} is covered, was reported "
            f"within the {policy['window_days']}-day window, and includes the required "
            f"lot number and photo. The policy allows replacement or a credit note, "
            f"and the affected lot must be blocked."
        )
        confidence = 0.97
    else:
        missing = []
        if not covered:
            missing.append("a covered defect")
        if not lot_ok:
            missing.append("lot number")
        if not photo_ok:
            missing.append("photo")
        if not window_ok:
            missing.append(f"evidence that it is within {policy['window_days']} days")
        if excluded:
            missing.append("absence of a policy exclusion")
        answer = (
            f"The complaint from call {cid} cannot be confirmed as return-eligible from "
            f"the available evidence. Missing or failing condition(s): {', '.join(missing)}."
        )
        confidence = 0.92
    sources = list(complaint.sources)
    if f"calls/{cid}/transcript" not in sources:
        sources.append(f"calls/{cid}/transcript")
    sources.append("DOC-011")
    return EvidencePack(
        qualifies,
        "calls",
        {
            "answer": answer,
            "qualifies": qualifies,
            "policy": policy,
            "complaint": complaint.facts,
        },
        sources,
        confidence=confidence,
    )


def _extract_defect_term(question: str) -> str | None:
    quoted = re.search(r"['\"]([^'\"]{3,60})['\"]", question)
    if quoted:
        return quoted.group(1)
    match = re.search(r"(?:defect|concern)\s+([a-z][a-z -]{2,40})", question, re.I)
    return match.group(1).strip(" .?") if match else None


def handle_defect_count(question: str, ctx: Context) -> EvidencePack:
    defect = _extract_defect_term(question)
    if not defect:
        return EvidencePack(False, "calls", {"answer": "I could not identify the defect term to count."}, confidence=0.9)
    calls = ctx.api.list_calls()

    def check(call: dict[str, Any]) -> tuple[str, bool | None]:
        cid = _call_id(call)
        try:
            segments = ctx.api.search_transcript(cid, search=defect, limit=10)
        except APIError:
            return cid, None
        if not segments:
            return cid, False
        wanted = normalize_text(defect)
        metadata = normalize_text(_call_blob(call))
        direct_metadata = any(
            phrase in metadata
            for phrase in (
                f"reports {wanted}",
                f"complaint {wanted}",
                f"complaint concerning {wanted}",
                f"quality complaint {wanted}",
            )
        )
        transcript_direct = False
        if str(first_value(call, "outcome", default="")) == "complaint_open":
            for segment in segments:
                text = normalize_text(
                    str(first_value(segment, "text", "content", default=""))
                )
                if f"not {wanted}" in text:
                    continue
                if any(
                    re.search(pattern, text)
                    for pattern in (
                        rf"(?:defect|complaint|problem|issue)\b.{{0,45}}\b{re.escape(wanted)}\b",
                        rf"(?:talking about|reports?|reported as)\s+{re.escape(wanted)}\b",
                        rf"\b{re.escape(wanted)}\b.{{0,45}}(?:affected|found|across|inside)",
                    )
                ):
                    transcript_direct = True
                    break
        return cid, direct_metadata or transcript_direct

    matched: list[str] = []
    failed: list[str] = []
    workers = min(32, max(1, len(calls)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(check, call) for call in calls]
        for future in as_completed(futures):
            cid, is_match = future.result()
            if is_match is None:
                failed.append(cid)
            elif is_match:
                matched.append(cid)
    if failed:
        return EvidencePack(
            False,
            "calls",
            {
                "answer": (
                    f"I could not produce an exact count because transcript search failed "
                    f"for {len(failed)} of {len(calls)} calls."
                )
            },
            ["calls"],
            missing=["complete transcript search coverage"],
            confidence=0.96,
        )
    matched.sort()
    return EvidencePack(
        True,
        "calls",
        {
            "answer": (
                f"Across all {len(calls)} recorded calls, {len(matched)} calls report "
                f"a quality complaint concerning '{defect}'."
            ),
            "count": len(matched),
            "call_ids": matched,
            "total_calls": len(calls),
        },
        ["calls", "calls/*/transcript"],
        confidence=0.97,
    )


def handle_price_conflict(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)
    sku = ids["skus"][0] if ids["skus"] else None
    if not sku:
        product_hits = ctx.kb.search_product(question)
        sku = product_hits[0].doc.sku if product_hits else None
    price_doc = ctx.kb.search_by_id("DOC-015")
    if not sku or not price_doc:
        return EvidencePack(
            False,
            "kb",
            {"answer": "I could not resolve both the product SKU and official price list."},
            ["DOC-015"] if price_doc else [],
            confidence=0.93,
        )
    official = extract_price_for_sku(price_doc.text, sku)
    if official["price"] is None:
        return EvidencePack(
            False,
            "kb",
            {"answer": f"SKU {sku} is not listed in DOC-015."},
            ["DOC-015"],
            confidence=0.98,
        )

    sources = ["DOC-015"]
    mentioned_price: str | None = None
    resolved = resolve_customer(question, ctx)
    if resolved.found and resolved.record:
        calls = sort_records_newest(ctx.api.list_calls(customer_id=customer_id(resolved.record)))[:10]
        calls.sort(
            key=lambda row: "price" in normalize_text(_call_blob(row)),
            reverse=True,
        )
        search_terms = [sku]
        if official.get("product"):
            search_terms.append(str(official["product"]).split(" - ")[0])
        for call in calls:
            cid = _call_id(call)
            segments = _targeted_segments(cid, ctx, search_terms[:1])
            if not segments and len(search_terms) > 1:
                segments = _targeted_segments(cid, ctx, search_terms[1:])
            text = _segments_text(segments)
            if text:
                price_match = re.search(r"(?:EUR|€)\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:EUR|€)", text, re.I)
                if price_match:
                    mentioned_price = (price_match.group(1) or price_match.group(2)).replace(",", ".")
                sources.extend(["crm/customers", "calls", f"calls/{cid}/transcript"])
                break
    answer = (
        f"The correct list price for {sku} is {official['price']:.2f} EUR per carton. "
        f"The official 2026 wholesale price list (DOC-015) is authoritative"
    )
    if mentioned_price:
        answer += f"; the {mentioned_price} EUR figure mentioned in the call is not the official list price"
    answer += "."
    return EvidencePack(
        True,
        "kb",
        {"answer": answer, "official_price": official, "call_price": mentioned_price},
        list(dict.fromkeys(sources)),
        confidence=0.99,
    )
