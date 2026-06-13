from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from ..api_client import AlDenteAPI, APIError
from ..cache import TTLCache
from ..config import Settings
from ..kb import KnowledgeBase
from ..normalizers import (
    extract_customer_phrase,
    extract_ids,
    first_value,
    normalize_company_name,
    record_id,
)


@dataclass
class Context:
    settings: Settings
    api: AlDenteAPI
    kb: KnowledgeBase
    customer_cache: TTLCache[list[dict[str, Any]]]
    deadline: float

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())


@dataclass
class ResolvedEntity:
    found: bool
    record: dict[str, Any] | None = None
    requested: str | None = None
    confidence: float = 0.0
    ambiguous: list[str] | None = None


def customer_name(record: dict[str, Any]) -> str:
    return str(
        first_value(
            record,
            "name",
            "company_name",
            "legal_name",
            "customer_name",
            default=record_id(record, "customer_id"),
        )
    )


def customer_id(record: dict[str, Any]) -> str:
    return record_id(record, "customer_id", "id")


def unwrap_single(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    return payload


def get_customer_index(ctx: Context) -> list[dict[str, Any]]:
    cached = ctx.customer_cache.get("all-customers")
    if cached is not None:
        return cached
    rows = ctx.api.search_customers()
    ctx.customer_cache.set("all-customers", rows)
    return rows


def resolve_customer(question: str, ctx: Context) -> ResolvedEntity:
    ids = extract_ids(question)["customer_ids"]
    if ids:
        requested = ids[0]
        try:
            record = unwrap_single(ctx.api.get_customer(requested))
            if record and customer_id(record):
                return ResolvedEntity(True, record, requested, 0.99)
        except APIError as exc:
            if exc.status_code != 404:
                raise
        return ResolvedEntity(False, requested=requested, confidence=0.99)

    requested = extract_customer_phrase(question)
    if not requested:
        return ResolvedEntity(False, requested=None, confidence=0.3)
    search_terms = [requested]
    stripped = requested.replace("S.p.A.", "").replace("S.r.l.", "").strip()
    if stripped != requested:
        search_terms.append(stripped)
    candidates: list[dict[str, Any]] = []
    for term in search_terms:
        candidates = ctx.api.search_customers(search=term)
        if candidates:
            break

    wanted = normalize_company_name(requested)
    exact = [row for row in candidates if normalize_company_name(customer_name(row)) == wanted]
    if len(exact) == 1:
        return ResolvedEntity(True, exact[0], requested, 0.98)
    if len(candidates) == 1:
        score = fuzz.ratio(wanted, normalize_company_name(customer_name(candidates[0])))
        if score >= 82:
            return ResolvedEntity(True, candidates[0], requested, 0.88)

    index = get_customer_index(ctx)
    scored = sorted(
        (
            (
                fuzz.ratio(wanted, normalize_company_name(customer_name(row))),
                row,
            )
            for row in index
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if scored and scored[0][0] >= 88:
        gap = scored[0][0] - (scored[1][0] if len(scored) > 1 else 0)
        if gap >= 8:
            return ResolvedEntity(True, scored[0][1], requested, 0.8)
    ambiguous = [
        customer_name(row)
        for score, row in scored[:3]
        if score >= 75
    ]
    return ResolvedEntity(
        False,
        requested=requested,
        confidence=0.95,
        ambiguous=ambiguous or None,
    )


def missing_customer_answer(resolved: ResolvedEntity) -> str:
    requested = resolved.requested or "the requested customer"
    if resolved.ambiguous:
        return (
            f'The customer name "{requested}" is ambiguous in the CRM. '
            f"Possible matches: {', '.join(resolved.ambiguous)}."
        )
    return f'I could not find any customer named "{requested}" in the CRM.'
