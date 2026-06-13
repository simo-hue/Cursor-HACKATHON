from __future__ import annotations

from typing import Any

from .api_client import AlDenteAPI, APIError
from .cache import TTLCache
from .kb import KnowledgeBase, extract_product_spec
from .normalizers import first_value, record_id


class GraphBuilder:
    def __init__(
        self,
        api: AlDenteAPI,
        kb: KnowledgeBase,
        cache: TTLCache[dict[str, Any]],
    ) -> None:
        self.api = api
        self.kb = kb
        self.cache = cache

    def build(self) -> dict[str, Any]:
        cached = self.cache.get("representative-graph")
        if cached is not None:
            return cached
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []

        def add_node(identifier: str, label: str, node_type: str, **extra: Any) -> None:
            if not identifier:
                return
            nodes[identifier] = {
                "data": {"id": identifier, "label": label or identifier, "type": node_type, **extra}
            }

        def add_edge(source: str, target: str, label: str) -> None:
            if not source or not target:
                return
            for identifier in (source, target):
                if identifier in nodes:
                    continue
                node_type = next(
                    (
                        kind
                        for prefix, kind in (
                            ("CUST-", "customer"),
                            ("OPP-", "opportunity"),
                            ("ORD-", "order"),
                            ("LOT-", "lot"),
                            ("CALL-", "call"),
                            ("PAS-", "product"),
                            ("RAW-", "raw_material"),
                            ("SUP-", "supplier"),
                            ("DOC-", "kb_doc"),
                        )
                        if identifier.startswith(prefix)
                    ),
                    "hub",
                )
                add_node(identifier, identifier, node_type)
            identifier = f"{source}::{label}::{target}"
            edges[identifier] = {
                "data": {"id": identifier, "source": source, "target": target, "label": label}
            }

        add_node("KB-POLICY", "Policies", "hub")
        product_skus: list[str] = []
        for doc in self.kb.documents:
            add_node(doc.doc_id, doc.title.replace("Product Specification Sheet - ", ""), "kb_doc")
            if doc.sku:
                spec = extract_product_spec(doc.text)
                add_node(doc.sku, spec.get("product") or doc.sku, "product")
                add_edge(doc.doc_id, doc.sku, "specifies")
                product_skus.append(doc.sku)
            else:
                add_edge("KB-POLICY", doc.doc_id, "contains")

        if not self.api.settings.has_mock_api:
            result = {
                "nodes": list(nodes.values()),
                "edges": list(edges.values()),
                "warnings": [
                    "MOCK_API_TOKEN is not configured; showing the local knowledge-base graph."
                ],
            }
            self.cache.set("representative-graph", result)
            return result

        def page(path: str, params: dict[str, Any] | None = None, limit: int = 30) -> list[dict[str, Any]]:
            try:
                payload = self.api.list_page(path, params=params, limit=limit)
                return [row for row in payload.get("data", []) if isinstance(row, dict)]
            except APIError as exc:
                warnings.append(f"{path}: {exc}")
                return []

        customers = page("/crm/customers", {"status": "active"}, 20)
        opportunities = page("/crm/opportunities", {"stage": "negotiation"}, 20)
        opportunities += page("/crm/opportunities", {"stage": "qualification"}, 10)
        orders = page("/crm/orders", None, 20)
        lots = page("/erp/production-orders", None, 20)
        calls = page("/calls", None, 20)
        inventory = page("/erp/inventory", None, 200)
        suppliers = page("/erp/suppliers", None, 20)
        inventory_by_sku = {
            str(first_value(row, "sku", "item_sku", default="")): row
            for row in inventory
        }

        for row in customers:
            cid = record_id(row, "customer_id")
            add_node(cid, str(first_value(row, "name", "company_name", default=cid)), "customer", channel=first_value(row, "channel"))
        for row in opportunities:
            oid = record_id(row, "opportunity_id")
            add_node(oid, str(first_value(row, "name", "title", default=oid)), "opportunity", stage=first_value(row, "stage"))
            add_edge(str(first_value(row, "customer_id", default="")), oid, "has opportunity")
        for row in orders:
            oid = record_id(row, "order_id")
            add_node(oid, oid, "order", status=first_value(row, "status"))
            add_edge(str(first_value(row, "customer_id", default="")), oid, "placed")
        for row in lots:
            lot_id = record_id(row, "lot_id")
            sku = str(first_value(row, "sku", "product_sku", default=""))
            add_node(lot_id, lot_id, "lot", status=first_value(row, "status"))
            add_edge(str(first_value(row, "order_id", default="")), lot_id, "produces")
            if sku:
                add_node(sku, sku, "product")
                add_edge(lot_id, sku, "output")
        for row in calls:
            call_id = record_id(row, "call_id")
            add_node(call_id, call_id, "call", outcome=first_value(row, "outcome"))
            add_edge(str(first_value(row, "customer_id", default="")), call_id, "had call")
        for row in inventory:
            sku = str(first_value(row, "sku", "item_sku", default=""))
            item_type = str(first_value(row, "type", default="product"))
            node_type = "raw_material" if item_type == "raw_material" or sku.startswith("RAW-") else "product"
            add_node(
                sku,
                str(first_value(row, "name", "description", default=sku)),
                node_type,
                below_min=bool(first_value(row, "below_min", default=False)),
            )
            sid = str(first_value(row, "supplier_id", default=""))
            if sid:
                add_edge(sid, sku, "supplies")
        for row in suppliers:
            sid = record_id(row, "supplier_id")
            add_node(sid, str(first_value(row, "name", "supplier_name", default=sid)), "supplier")

        selected_skus = list(dict.fromkeys(
            [
                str(first_value(row, "sku", "item_sku", default=""))
                for row in inventory
                if str(first_value(row, "sku", default="")).startswith("PAS-")
            ]
            + product_skus[:5]
        ))[:5]
        for sku in selected_skus:
            if not sku:
                continue
            try:
                components = self.api.get_bom(sku)
            except APIError as exc:
                warnings.append(f"/erp/bom: {exc}")
                components = []
            for component in components:
                raw_sku = str(
                    first_value(
                        component,
                        "raw_material_sku",
                        "raw_sku",
                        "component_sku",
                        "material_sku",
                        default="",
                    )
                )
                raw_name = str(
                    first_value(component, "raw_material_name", "component_name", "name", default=raw_sku)
                )
                add_node(raw_sku, raw_name, "raw_material")
                add_edge(sku, raw_sku, "uses")
                inventory_row = inventory_by_sku.get(raw_sku, {})
                sid = str(
                    first_value(
                        component,
                        "supplier_id",
                        default=first_value(inventory_row, "supplier_id", default=""),
                    )
                )
                if sid:
                    add_edge(sid, raw_sku, "supplies")

        result = {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "warnings": warnings,
        }
        self.cache.set("representative-graph", result)
        return result
