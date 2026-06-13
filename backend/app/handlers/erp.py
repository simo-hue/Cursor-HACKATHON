from __future__ import annotations

import re
from typing import Any

from ..evidence import EvidencePack
from ..kb import extract_product_spec
from ..normalizers import (
    as_decimal,
    extract_customer_phrase,
    extract_ids,
    first_value,
    format_number,
    normalize_text,
    record_id,
    sort_records_newest,
)
from . import Context, customer_id, customer_name, resolve_customer


def _inventory_values(row: dict[str, Any]) -> tuple[Any, Any, str]:
    on_hand = first_value(
        row,
        "on_hand",
        "on_hand_qty",
        "quantity_on_hand",
        "stock_on_hand",
        "quantity",
        "stock",
        default=0,
    )
    minimum = first_value(
        row,
        "minimum_stock",
        "min_stock",
        "minimum_quantity",
        "min_quantity",
        "reorder_point",
        default=0,
    )
    unit = str(first_value(row, "unit", "uom", "unit_of_measure", default="units"))
    return on_hand, minimum, unit


def _find_exact_inventory(rows: list[dict[str, Any]], sku: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in rows
            if str(first_value(row, "sku", "item_sku", "material_sku", default="")).upper()
            == sku.upper()
        ),
        None,
    )


def handle_inventory(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)
    sku = (ids["skus"] or ids["raw_skus"] or [None])[0]
    query = sku
    if not query:
        product_hits = ctx.kb.search_product(question)
        query = product_hits[0].doc.sku if product_hits else None
    if not query:
        return EvidencePack(
            False,
            "erp",
            {"answer": "I could not identify a unique SKU to check in ERP inventory."},
            [],
            confidence=0.9,
        )
    rows = ctx.api.list_inventory(search=query)
    item = _find_exact_inventory(rows, query)
    if not item:
        return EvidencePack(
            False,
            "erp",
            {"answer": f"I could not find SKU {query} in ERP inventory."},
            ["erp/inventory"],
            confidence=0.98,
        )
    on_hand, minimum, unit = _inventory_values(item)
    below = as_decimal(on_hand) < as_decimal(minimum)
    name = str(first_value(item, "name", "product_name", "description", default=query))
    answer = (
        f"{'Yes' if below else 'No'}, SKU {query} ({name}) is "
        f"{'below' if below else 'not below'} minimum stock. "
        f"On-hand: {format_number(on_hand)} {unit}; minimum: {format_number(minimum)} {unit}."
    )
    return EvidencePack(
        True,
        "erp",
        {"answer": answer, "inventory": item, "below_minimum": below},
        ["erp/inventory"],
        confidence=0.98,
    )


def handle_bom_chain(question: str, ctx: Context) -> EvidencePack:
    skus = extract_ids(question)["skus"]
    sku = skus[0] if skus else None
    if not sku:
        hits = ctx.kb.search_product(question)
        sku = hits[0].doc.sku if hits else None
    if not sku:
        return EvidencePack(False, "erp", {"answer": "I could not identify the finished-product SKU."}, confidence=0.9)

    bom = ctx.api.get_bom(sku)
    if not bom:
        return EvidencePack(
            False,
            "erp",
            {"answer": f"No bill of materials was found for SKU {sku}."},
            ["erp/bom"],
            confidence=0.97,
        )
    wants_semolina = "semolina" in normalize_text(question)
    components = []
    for row in bom:
        text = normalize_text(" ".join(str(value) for value in row.values()))
        if not wants_semolina or "semolina" in text or "semola" in text:
            components.append(row)
    component = (components or bom)[0]
    raw_sku = str(
        first_value(
            component,
            "raw_material_sku",
            "raw_sku",
            "component_sku",
            "material_sku",
            "ingredient_sku",
            "sku_component",
            default="",
        )
    )
    raw_name = str(
        first_value(
            component,
            "raw_material_name",
            "component_name",
            "material_name",
            "description",
            "name",
            default=raw_sku,
        )
    )
    inventory_rows = ctx.api.list_inventory(search=raw_sku or raw_name)
    inventory = _find_exact_inventory(inventory_rows, raw_sku) if raw_sku else (
        inventory_rows[0] if len(inventory_rows) == 1 else None
    )
    on_hand, minimum, unit = _inventory_values(inventory or {})
    below = as_decimal(on_hand) < as_decimal(minimum)

    supplier_id = str(
        first_value(
            component,
            "supplier_id",
            default=first_value(inventory or {}, "supplier_id", default=""),
        )
    )
    supplier_name = str(
        first_value(
            component,
            "supplier_name",
            default=first_value(inventory or {}, "supplier_name", default=""),
        )
    )
    suppliers: list[dict[str, Any]] = []
    if supplier_id:
        suppliers = [
            row
            for row in ctx.api.list_suppliers()
            if record_id(row, "supplier_id") == supplier_id
        ]
    elif supplier_name:
        suppliers = ctx.api.list_suppliers(search=supplier_name)
    elif wants_semolina:
        suppliers = ctx.api.list_suppliers(category="semolina")
    if suppliers:
        supplier = next(
            (row for row in suppliers if record_id(row, "supplier_id") == supplier_id),
            suppliers[0],
        )
        supplier_name = str(first_value(supplier, "name", "supplier_name", default=supplier_id))

    answer = (
        f"SKU {sku} uses {raw_sku or 'the identified raw material'}"
        f"{f' ({raw_name})' if raw_name and raw_name != raw_sku else ''}, "
        f"supplied by {supplier_name or 'an unlisted supplier'}. "
        f"It is {'below' if below else 'not below'} minimum stock"
    )
    if inventory:
        answer += (
            f": {format_number(on_hand)} {unit} on hand vs "
            f"{format_number(minimum)} {unit} minimum."
        )
    else:
        answer += ", but no matching ERP inventory row was found."
    return EvidencePack(
        bool(raw_sku and inventory and supplier_name),
        "erp",
        {
            "answer": answer,
            "bom": component,
            "inventory": inventory,
            "supplier": supplier_name,
            "below_minimum": below,
        },
        ["erp/bom", "erp/inventory", "erp/suppliers"],
        missing=[] if supplier_name else ["supplier"],
        confidence=0.96 if raw_sku and inventory and supplier_name else 0.62,
    )


def _find_lot(question: str, ctx: Context) -> tuple[str | None, dict[str, Any] | None]:
    ids = extract_ids(question)
    lot_id = ids["lot_ids"][0] if ids["lot_ids"] else None
    filters: dict[str, Any] = {}
    if ids["skus"]:
        filters["sku"] = ids["skus"][0]
    resolved = None
    if (
        not ids["order_ids"]
        and (
            ids["customer_ids"]
            or "customer" in normalize_text(question)
            or extract_customer_phrase(question)
        )
    ):
        resolved = resolve_customer(question, ctx)
        if resolved.record:
            filters["customer_id"] = customer_id(resolved.record)
    if lot_id:
        lot = ctx.api.find_production_order_by_lot(
            lot_id,
            customer_id=filters.get("customer_id"),
            sku=filters.get("sku"),
        )
        if lot and ids["order_ids"]:
            if str(first_value(lot, "order_id", default="")) != ids["order_ids"][0]:
                lot = None
        return lot_id, lot

    lots = ctx.api.list_production_orders(**filters)
    if ids["order_ids"]:
        lots = [
            row
            for row in lots
            if str(first_value(row, "order_id", default="")) == ids["order_ids"][0]
        ]
    lots = sort_records_newest(lots)
    return (record_id(lots[0], "lot_id"), lots[0]) if lots else (None, None)


def handle_lot_status(question: str, ctx: Context) -> EvidencePack:
    lot_id, lot = _find_lot(question, ctx)
    if not lot:
        requested = lot_id or "the requested criteria"
        answer = (
            f"Lot {lot_id} was not found in the production orders available."
            if lot_id
            else f"No production lot was found for {requested}."
        )
        return EvidencePack(
            False,
            "erp",
            {"answer": answer},
            ["erp/production-orders"],
            confidence=0.97,
        )
    status = str(first_value(lot, "status", default="unknown")).replace("_", " ")
    sku = str(first_value(lot, "sku", "product_sku", default="unknown SKU"))
    order_id = str(first_value(lot, "order_id", default=""))
    answer = f"Lot {lot_id} is {status} and produces SKU {sku}"
    if order_id:
        answer += f" for order {order_id}"
    answer += "."
    return EvidencePack(
        True,
        "erp",
        {"answer": answer, "lot": lot},
        ["erp/production-orders"],
        confidence=0.98,
    )


def handle_margin_trap(question: str, ctx: Context) -> EvidencePack:
    lot_id, lot = _find_lot(question, ctx)
    if extract_ids(question)["lot_ids"] and not lot:
        return EvidencePack(
            False,
            "erp",
            {"answer": f"I could not find lot {lot_id} in ERP production data."},
            ["erp/production-orders"],
            confidence=0.97,
        )
    subject = f" for lot {lot_id}" if lot_id else ""
    return EvidencePack(
        False,
        "erp",
        {
            "answer": (
                f"Not available: cost and profit margin are not stored on production lots "
                f"or in the provided sources{subject}."
            )
        },
        ["erp/production-orders"] if lot_id else [],
        missing=["cost", "profit margin"],
        confidence=0.99,
    )


def handle_supplier_materials(question: str, ctx: Context) -> EvidencePack:
    ids = extract_ids(question)
    supplier_id = ids["supplier_ids"][0] if ids["supplier_ids"] else None
    search = supplier_id
    if not search:
        match = re.search(
            r"supplier\s+([A-Z][\w&'. -]{2,70}?)(?=\s+(?:provide|supplies|material)|[?.]|$)",
            question,
            re.I,
        )
        search = match.group(1).strip() if match else None
    if not search:
        return EvidencePack(False, "erp", {"answer": "I could not identify the supplier."}, confidence=0.9)
    suppliers = (
        [
            row
            for row in ctx.api.list_suppliers()
            if record_id(row, "supplier_id") == supplier_id
        ]
        if supplier_id
        else ctx.api.list_suppliers(search=search)
    )
    supplier = next(
        (row for row in suppliers if record_id(row, "supplier_id") == supplier_id),
        suppliers[0] if len(suppliers) == 1 else None,
    )
    if not supplier:
        return EvidencePack(
            False,
            "erp",
            {"answer": f"No unique supplier matching {search} was found in ERP."},
            ["erp/suppliers"],
            confidence=0.95,
        )
    sid = record_id(supplier, "supplier_id")
    name = str(first_value(supplier, "name", "supplier_name", default=sid))
    inventory = ctx.api.list_inventory()
    materials = [
        row
        for row in inventory
        if str(first_value(row, "supplier_id", default="")) == sid
        or normalize_text(str(first_value(row, "supplier_name", default="")))
        == normalize_text(name)
    ]
    labels = [
        f"{first_value(row, 'sku', 'item_sku', default='unknown SKU')} ({first_value(row, 'name', 'description', default='unnamed material')})"
        for row in materials
    ]
    answer = (
        f"{name} ({sid}) provides {', '.join(labels)}."
        if labels
        else f"{name} ({sid}) is in ERP, but no inventory materials reference that supplier."
    )
    return EvidencePack(
        True,
        "erp",
        {"answer": answer, "supplier": supplier, "materials": materials},
        ["erp/suppliers", "erp/inventory"],
        confidence=0.9,
    )
