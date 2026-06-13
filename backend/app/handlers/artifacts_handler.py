from __future__ import annotations

import html
from decimal import Decimal
from typing import Any

from ..artifacts import (
    ArtifactContent,
    artifact_url,
    render_inline_html,
    render_inline_markdown,
    write_binary,
)
from ..evidence import EvidencePack
from ..normalizers import (
    extract_ids,
    extract_customer_phrase,
    first_value,
    format_money,
    format_number,
    normalize_text,
    record_id,
    sort_records_newest,
)
from ..router import FastRoute
from . import Context, customer_id, customer_name, missing_customer_answer, resolve_customer
from .crm import MONEY_KEYS, _opportunity_value
from .kb_handlers import handle_generic_kb, handle_product_spec


def _list_html(items: list[str]) -> str:
    if not items:
        return "<p>No records found.</p>"
    return "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def _customer_deck(question: str, ctx: Context) -> tuple[ArtifactContent, list[str]]:
    resolved = resolve_customer(question, ctx)
    if not resolved.found or not resolved.record:
        raise ValueError(missing_customer_answer(resolved))
    customer = resolved.record
    cid = customer_id(customer)
    opportunities = (
        ctx.api.list_opportunities(customer_id=cid, stage="qualification")
        + ctx.api.list_opportunities(customer_id=cid, stage="negotiation")
    )
    total = sum((_opportunity_value(row) for row in opportunities), start=0)
    orders = sort_records_newest(ctx.api.list_orders(customer_id=cid))[:5]
    lots = sort_records_newest(ctx.api.list_production_orders(customer_id=cid))[:5]
    calls = sort_records_newest(ctx.api.list_calls(customer_id=cid))[:5]
    complaint_calls = [
        row
        for row in calls
        if str(first_value(row, "outcome", default="")) == "complaint_open"
        or "complaint" in normalize_text(" ".join(str(value) for value in row.values()))
    ]
    profile_items = [
        f"Account: {customer_name(customer)} ({cid})",
        f"Channel: {first_value(customer, 'channel', default='not available')}",
        f"Location: {first_value(customer, 'city', 'location', default='not available')}",
        f"Status: {first_value(customer, 'status', default='not available')}",
    ]
    deal_items = [
        (
            f"{record_id(row, 'opportunity_id')} · "
            f"{first_value(row, 'stage', default='unknown')} · "
            f"{format_money(first_value(row, *MONEY_KEYS, default=0))}"
        )
        for row in opportunities
    ]
    order_items = [
        (
            f"{record_id(row, 'order_id')} · "
            f"{first_value(row, 'status', default='unknown')}"
        )
        for row in orders
    ] + [
        (
            f"{record_id(row, 'lot_id')} · SKU {first_value(row, 'sku', default='n/a')} · "
            f"{first_value(row, 'status', default='unknown')}"
        )
        for row in lots
    ]
    call_items = [
        (
            f"{record_id(row, 'call_id')} · "
            f"{first_value(row, 'outcome', default='recorded')} · "
            f"{first_value(row, 'subject', 'summary', default='No complaint detail in metadata')}"
        )
        for row in complaint_calls
    ]
    table_rows: list[list[Any]] = []
    table_rows.extend(
        [
            "Opportunity",
            record_id(row, "opportunity_id"),
            first_value(row, "stage", default="unknown"),
            first_value(row, "title", "name", default=""),
            float(_opportunity_value(row)),
        ]
        for row in opportunities
    )
    table_rows.extend(
        [
            "Order",
            record_id(row, "order_id"),
            first_value(row, "status", default="unknown"),
            "",
            first_value(row, *MONEY_KEYS, default=""),
        ]
        for row in orders
    )
    table_rows.extend(
        [
            "Production lot",
            record_id(row, "lot_id"),
            first_value(row, "status", default="unknown"),
            f"SKU {first_value(row, 'sku', 'product_sku', default='n/a')}",
            "",
        ]
        for row in lots
    )
    table_rows.extend(
        [
            "Call",
            record_id(row, "call_id"),
            first_value(row, "outcome", default="recorded"),
            first_value(row, "summary", "topic", default=""),
            "",
        ]
        for row in complaint_calls
    )
    content = ArtifactContent(
        title=f"{customer_name(customer)} account brief",
        subtitle=(
            f"Sales visit briefing · {len(opportunities)} open opportunities · "
            f"{format_money(total)} pipeline"
        ),
        sections=[
            ("1 · Customer profile", _list_html(profile_items)),
            ("2 · Open deals", _list_html(deal_items)),
            ("3 · Orders and production", _list_html(order_items)),
            (
                "4 · Complaints and next steps",
                _list_html(call_items)
                if call_items
                else "<p><strong>No complaint calls are on record for this customer.</strong></p>",
            ),
        ],
        columns=["Record type", "ID", "Status / stage", "Description", "Value EUR"],
        rows=table_rows,
        sources=[
            "crm/customers",
            "crm/opportunities",
            "crm/orders",
            "erp/production-orders",
            "calls",
        ],
    )
    return content, content.sources


def _negotiation_report(ctx: Context) -> ArtifactContent:
    opportunities = ctx.api.list_opportunities(stage="negotiation")
    customers = ctx.api.search_customers()
    customers_by_id = {customer_id(row): row for row in customers}
    totals: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for opportunity in opportunities:
        customer = customers_by_id.get(
            str(first_value(opportunity, "customer_id", default=""))
        )
        channel = str(first_value(customer or {}, "channel", default="unknown"))
        totals[channel] = totals.get(channel, Decimal("0")) + _opportunity_value(
            opportunity
        )
        counts[channel] = counts.get(channel, 0) + 1
    ordered = ["GDO", "distributor", "horeca"]
    rows = [
        [channel, counts.get(channel, 0), float(totals.get(channel, Decimal("0")))]
        for channel in ordered
    ]
    return ArtifactContent(
        title="Negotiation pipeline by customer channel",
        subtitle=f"{len(opportunities)} negotiation-stage opportunities.",
        sections=[
            (
                "Executive summary",
                "; ".join(
                    f"{channel}: {counts.get(channel, 0)} opportunities, "
                    f"{format_money(totals.get(channel, Decimal('0')))}"
                    for channel in ordered
                ),
            )
        ],
        columns=["Customer channel", "Opportunity count", "Total value EUR"],
        rows=rows,
        sources=["crm/opportunities", "crm/customers"],
    )


def _inventory_report(ctx: Context) -> ArtifactContent:
    rows = ctx.api.list_inventory(below_min=True)
    table_rows: list[list[Any]] = []
    for row in rows:
        on_hand = first_value(
            row, "on_hand", "on_hand_qty", "quantity_on_hand", "quantity", "stock", default=0
        )
        minimum = first_value(
            row, "minimum_stock", "min_stock", "minimum_quantity", "min_quantity", default=0
        )
        table_rows.append(
            [
                first_value(row, "sku", "item_sku", default=""),
                first_value(row, "name", "product_name", "description", default=""),
                first_value(row, "type", default=""),
                float(on_hand) if str(on_hand).replace(".", "", 1).isdigit() else on_hand,
                float(minimum) if str(minimum).replace(".", "", 1).isdigit() else minimum,
                float(minimum) - float(on_hand)
                if str(on_hand).replace(".", "", 1).isdigit()
                and str(minimum).replace(".", "", 1).isdigit()
                else "",
            ]
        )
    return ArtifactContent(
        title="Below-minimum inventory",
        subtitle=f"{len(table_rows)} inventory items require attention.",
        sections=[
            (
                "Action",
                "Prioritize the largest stock gaps and verify current production and purchasing commitments before replenishment.",
            )
        ],
        columns=["SKU", "Item", "Type", "On hand", "Minimum", "Gap"],
        rows=table_rows,
        sources=["erp/inventory"],
    )


def _kb_report(question: str, ctx: Context) -> ArtifactContent:
    evidence = (
        handle_product_spec(question, ctx)
        if any(term in normalize_text(question) for term in ("sku", "product", "allergen", "shelf life"))
        else handle_generic_kb(question, ctx)
    )
    return ArtifactContent(
        title="Al Dente knowledge report",
        subtitle="Grounded summary from the company knowledge base.",
        sections=[("Executive summary", evidence.answer)],
        sources=evidence.sources,
    )


def handle_artifact(question: str, route: FastRoute, ctx: Context) -> EvidencePack:
    q = normalize_text(question)
    try:
        has_customer = bool(extract_ids(question)["customer_ids"]) or any(
            term in q for term in ("customer", "account", "sales rep", "visiting")
        ) or ("opportunit" in q and bool(extract_customer_phrase(question)))
        if "negotiation" in q and any(
            term in q for term in ("channel", "grouped", "pipeline")
        ):
            content = _negotiation_report(ctx)
            sources = content.sources
            verticale = "crm"
        elif has_customer and any(
            term in q
            for term in (
                "customer",
                "account",
                "sales rep",
                "visiting",
                "opportunit",
                "open deal",
                "order",
            )
        ):
            content, sources = _customer_deck(question, ctx)
            verticale = "crm"
        elif any(term in q for term in ("below minimum", "inventory", "stock", "procurement")):
            content = _inventory_report(ctx)
            sources = content.sources
            verticale = "erp"
        else:
            content = _kb_report(question, ctx)
            sources = content.sources
            verticale = "kb"
    except ValueError as exc:
        return EvidencePack(False, route.verticale, {"answer": str(exc)}, confidence=0.95)

    artifact_type = route.artifact_type or "html"
    if artifact_type in {"html", "markdown"}:
        answer = (
            render_inline_html(content)
            if artifact_type == "html"
            else render_inline_markdown(content)
        )
        return EvidencePack(
            True,
            verticale,
            {"answer": answer, "artifact_type": artifact_type},
            sources,
            confidence=0.96,
        )
    path = write_binary(content, artifact_type)
    url = artifact_url(ctx.settings, path)
    return EvidencePack(
        True,
        verticale,
        {"answer": f"Generated the requested {artifact_type.upper()} artifact.", "path": str(path)},
        sources,
        confidence=0.96,
        artifact_url=url,
    )
