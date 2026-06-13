from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from ..evidence import EvidencePack
from ..normalizers import (
    as_decimal,
    extract_ids,
    first_value,
    format_money,
    record_id,
    sort_records_newest,
)
from . import (
    Context,
    customer_id,
    customer_name,
    missing_customer_answer,
    resolve_customer,
)

MONEY_KEYS = ("value", "value_eur", "amount", "amount_eur", "total_value", "expected_value")


def _opportunity_value(row: dict[str, Any]) -> Decimal:
    return as_decimal(first_value(row, *MONEY_KEYS, default=0))


def handle_customer_lookup(question: str, ctx: Context) -> EvidencePack:
    resolved = resolve_customer(question, ctx)
    if not resolved.found or not resolved.record:
        return EvidencePack(
            False,
            "crm",
            {"answer": missing_customer_answer(resolved)},
            ["crm/customers"],
            confidence=resolved.confidence,
        )
    customer = resolved.record
    cid = customer_id(customer)
    details = [
        f"{customer_name(customer)} ({cid})",
        f"channel {first_value(customer, 'channel', default='not recorded')}",
        f"status {first_value(customer, 'status', default='not recorded')}",
    ]
    city = first_value(customer, "city", "location")
    if city:
        details.append(f"location {city}")
    return EvidencePack(
        True,
        "crm",
        {"answer": "; ".join(details) + ".", "customer": customer},
        ["crm/customers"],
        confidence=resolved.confidence,
    )


def handle_opportunity_lookup(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)["opportunity_ids"]
    opportunity_id = ids[0] if ids else None
    if not opportunity_id:
        return EvidencePack(
            False,
            "crm",
            {"answer": "I could not identify an opportunity ID."},
            confidence=0.95,
        )
    rows = ctx.api.list_opportunities()
    opportunity = next(
        (row for row in rows if record_id(row, "opportunity_id") == opportunity_id),
        None,
    )
    if not opportunity:
        return EvidencePack(
            False,
            "crm",
            {"answer": f"I could not find opportunity {opportunity_id} in the CRM."},
            ["crm/opportunities"],
            confidence=0.98,
        )
    cid = str(first_value(opportunity, "customer_id", default=""))
    customer = None
    if cid:
        try:
            customer = resolve_customer(cid, ctx).record
        except Exception:
            customer = None
    stage = str(first_value(opportunity, "stage", default="unknown")).replace("_", " ")
    title = str(first_value(opportunity, "title", "name", default="untitled opportunity"))
    answer = (
        f"{opportunity_id} is '{title}', currently in {stage}, with a value of "
        f"{format_money(_opportunity_value(opportunity))}"
    )
    if customer:
        answer += f" for {customer_name(customer)} ({cid})"
    elif cid:
        answer += f" for customer {cid}"
    answer += "."
    return EvidencePack(
        True,
        "crm",
        {"answer": answer, "opportunity": opportunity, "customer": customer},
        ["crm/opportunities"] + (["crm/customers"] if customer else []),
        confidence=0.97,
    )


def handle_open_opportunities(question: str, ctx: Context) -> EvidencePack:
    resolved = resolve_customer(question, ctx)
    if not resolved.found or not resolved.record:
        return EvidencePack(
            False,
            "crm",
            {"answer": missing_customer_answer(resolved)},
            ["crm/customers"],
            confidence=resolved.confidence,
        )
    cid = customer_id(resolved.record)
    qualification = ctx.api.list_opportunities(customer_id=cid, stage="qualification")
    negotiation = ctx.api.list_opportunities(customer_id=cid, stage="negotiation")
    rows = qualification + negotiation
    total = sum((_opportunity_value(row) for row in rows), Decimal("0"))
    answer = (
        f"{customer_name(resolved.record)} has {len(rows)} open "
        f"{'opportunity' if len(rows) == 1 else 'opportunities'} "
        f"(qualification + negotiation) worth {format_money(total)} in total."
    )
    if rows:
        deals = "; ".join(
            (
                f"{record_id(row, 'opportunity_id')} "
                f"({first_value(row, 'title', 'name', default='untitled')}, "
                f"{format_money(_opportunity_value(row))})"
            )
            for row in sorted(rows, key=lambda item: record_id(item, "opportunity_id"))
        )
        answer += f" Deals: {deals}."
    return EvidencePack(
        True,
        "crm",
        {"answer": answer, "customer": resolved.record, "opportunities": rows, "total": total},
        ["crm/customers", "crm/opportunities"],
        confidence=min(resolved.confidence, 0.98),
    )


def handle_negotiation_by_channel(question: str, ctx: Context) -> EvidencePack:
    opportunities = ctx.api.list_opportunities(stage="negotiation")
    opportunity_customer_ids = {
        str(first_value(row, "customer_id", default=""))
        for row in opportunities
        if first_value(row, "customer_id")
    }
    customers = []
    for channel in ("GDO", "distributor", "horeca"):
        customers.extend(ctx.api.search_customers(channel=channel))
    channel_by_customer_id = {
        customer_id(row): str(first_value(row, "channel", default="unknown"))
        for row in customers
        if customer_id(row) in opportunity_customer_ids
    }
    totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    counts: defaultdict[str, int] = defaultdict(int)
    missing_customers = 0
    for opportunity in opportunities:
        cid = str(first_value(opportunity, "customer_id", default=""))
        channel = channel_by_customer_id.get(cid)
        if not channel:
            missing_customers += 1
            continue
        totals[channel] += _opportunity_value(opportunity)
        counts[channel] += 1
    ordered = ["GDO", "distributor", "horeca"]
    parts = [
        f"{channel}: {format_money(totals[channel])} across {counts[channel]} opportunities"
        for channel in ordered
    ]
    extras = sorted(channel for channel in totals if channel not in ordered)
    parts.extend(
        f"{channel}: {format_money(totals[channel])} across {counts[channel]} opportunities"
        for channel in extras
    )
    warnings = (
        [f"{missing_customers} opportunities referenced customers not returned by CRM."]
        if missing_customers
        else []
    )
    return EvidencePack(
        True,
        "crm",
        {
            "answer": "Negotiation-stage opportunities by customer channel: "
            + "; ".join(parts)
            + ".",
            "totals": totals,
            "counts": counts,
        },
        ["crm/opportunities", "crm/customers"],
        warnings=warnings,
        confidence=0.96 if not missing_customers else 0.75,
    )


def handle_order_status(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)
    order_id = ids["order_ids"][0] if ids["order_ids"] else None
    resolved = resolve_customer(question, ctx)
    if not resolved.found and resolved.requested:
        return EvidencePack(
            False,
            "crm",
            {"answer": missing_customer_answer(resolved)},
            ["crm/customers"],
            confidence=resolved.confidence,
        )

    filters: dict[str, Any] = {}
    if resolved.record:
        filters["customer_id"] = customer_id(resolved.record)
    orders = ctx.api.list_orders(**filters)
    if order_id:
        orders = [row for row in orders if record_id(row, "order_id") == order_id]
    orders = sort_records_newest(orders)
    if "shipment" in question.lower() or "delivery" in question.lower():
        shipment_filters: dict[str, Any] = {}
        if order_id:
            shipment_filters["order_id"] = order_id
        elif resolved.record:
            shipment_filters["customer_id"] = customer_id(resolved.record)
        shipments = sort_records_newest(ctx.api.list_shipments(**shipment_filters))
        if not shipments:
            subject = order_id or (
                customer_name(resolved.record) if resolved.record else "the requested criteria"
            )
            return EvidencePack(
                False,
                "erp",
                {"answer": f"No ERP shipment was found for {subject}."},
                ["crm/customers", "erp/shipments"] if resolved.record else ["erp/shipments"],
                confidence=0.96,
            )
        shipment = shipments[0]
        shipment_id = record_id(shipment, "shipment_id")
        status = str(first_value(shipment, "status", default="unknown")).replace("_", " ")
        days_late = first_value(shipment, "days_late")
        answer = f"Shipment {shipment_id or 'record'} is {status}"
        if days_late is not None:
            answer += f" ({days_late} days late)" if as_decimal(days_late) > 0 else " and is not late"
        answer += "."
        return EvidencePack(
            True,
            "erp",
            {"answer": answer, "shipment": shipment},
            ["crm/customers", "erp/shipments"] if resolved.record else ["erp/shipments"],
            confidence=0.95,
        )
    if not orders:
        subject = order_id or (
            customer_name(resolved.record) if resolved.record else "the requested criteria"
        )
        return EvidencePack(
            False,
            "crm",
            {"answer": f"No CRM order was found for {subject}."},
            ["crm/customers", "crm/orders"] if resolved.record else ["crm/orders"],
            confidence=0.96,
        )
    order = orders[0]
    oid = record_id(order, "order_id")
    status = str(first_value(order, "status", default="unknown"))
    details = [f"Order {oid} is {status.replace('_', ' ')}"]
    amount = first_value(order, *MONEY_KEYS)
    if amount is not None:
        details.append(f"value {format_money(amount)}")
    invoices = ctx.api.list_invoices(order_id=oid)
    if invoices:
        invoice_states = sorted(
            {str(first_value(row, "status", default="unknown")) for row in invoices}
        )
        details.append(f"invoice status {', '.join(invoice_states)}")
    return EvidencePack(
        True,
        "crm",
        {"answer": "; ".join(details) + ".", "order": order, "invoices": invoices},
        ["crm/customers", "crm/orders", "crm/invoices"]
        if resolved.record
        else ["crm/orders", "crm/invoices"],
        confidence=0.94,
    )


def handle_account_brief(question: str, ctx: Context) -> EvidencePack:
    resolved = resolve_customer(question, ctx)
    if not resolved.found or not resolved.record:
        return EvidencePack(
            False,
            "crm",
            {"answer": missing_customer_answer(resolved)},
            ["crm/customers"],
            confidence=resolved.confidence,
        )
    customer = resolved.record
    cid = customer_id(customer)
    open_opportunities = (
        ctx.api.list_opportunities(customer_id=cid, stage="qualification")
        + ctx.api.list_opportunities(customer_id=cid, stage="negotiation")
    )
    total = sum((_opportunity_value(row) for row in open_opportunities), Decimal("0"))
    orders = sort_records_newest(ctx.api.list_orders(customer_id=cid))[:3]
    calls = sort_records_newest(ctx.api.list_calls(customer_id=cid))[:3]
    latest_order = (
        f"{record_id(orders[0], 'order_id')} ({first_value(orders[0], 'status', default='unknown')})"
        if orders
        else "none found"
    )
    complaint_count = sum(
        1
        for row in calls
        if str(first_value(row, "outcome", default="")) == "complaint_open"
        or "complaint" in str(first_value(row, "subject", "summary", default="")).lower()
    )
    answer = (
        f"{customer_name(customer)} ({cid}) is a "
        f"{first_value(customer, 'channel', default='channel not recorded')} account"
        f"{f' in {first_value(customer, 'city', 'location')}' if first_value(customer, 'city', 'location') else ''}. "
        f"It has {len(open_opportunities)} open opportunities worth {format_money(total)}. "
        f"Latest order: {latest_order}. Recent complaint calls: {complaint_count}."
    )
    return EvidencePack(
        True,
        "crm",
        {
            "answer": answer,
            "customer": customer,
            "opportunities": open_opportunities,
            "orders": orders,
            "calls": calls,
        },
        ["crm/customers", "crm/opportunities", "crm/orders", "calls"],
        confidence=0.95,
    )
