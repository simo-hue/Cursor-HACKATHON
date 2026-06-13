from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .cache import TTLCache
from .config import Settings, get_settings


class APIError(RuntimeError):
    def __init__(self, path: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.status_code = status_code


class APIConfigurationError(APIError):
    pass


class AlDenteAPI:
    def __init__(
        self,
        settings: Settings | None = None,
        cache: TTLCache[dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or TTLCache(
            self.settings.cache_ttl_seconds, self.settings.cache_max_entries
        )
        self._client = httpx.Client(
            base_url=self.settings.mock_api_base_url,
            timeout=httpx.Timeout(self.settings.request_timeout_seconds),
            headers={"Accept": "application/json"},
        )

    @staticmethod
    def source(path: str) -> str:
        return path.strip("/")

    def _cache_key(self, path: str, params: dict[str, Any] | None) -> str:
        clean = {key: value for key, value in (params or {}).items() if value is not None}
        return f"{path}?{json.dumps(clean, sort_keys=True, default=str)}"

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.settings.mock_api_token:
            raise APIConfigurationError(
                path,
                "MOCK_API_TOKEN is not configured.",
            )
        key = self._cache_key(path, params)
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        headers = {"Authorization": f"Bearer {self.settings.mock_api_token}"}
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._client.get(path, params=params, headers=headers)
                if response.status_code >= 500 and attempt == 0:
                    time.sleep(0.2)
                    continue
                if response.status_code >= 400:
                    detail = response.text[:300]
                    raise APIError(path, detail, response.status_code)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise APIError(path, "API returned a non-object JSON response.")
                self.cache.set(key, payload)
                return payload
            except (httpx.HTTPError, ValueError, APIError) as exc:
                last_error = exc
                if isinstance(exc, APIError) and exc.status_code and exc.status_code < 500:
                    break
                if attempt == 0:
                    time.sleep(0.2)
        if isinstance(last_error, APIError):
            raise last_error
        raise APIError(path, f"API request failed: {last_error}")

    def list_page(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = dict(params or {})
        query.update(limit=min(max(limit, 1), 200), offset=max(offset, 0))
        return self.get(path, query)

    def list_all(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        offset = 0
        page_count = 0
        while True:
            payload = self.list_page(path, params=params, limit=200, offset=offset)
            page = payload.get("data", [])
            if not isinstance(page, list):
                raise APIError(path, "Paginated API response is missing a data list.")
            rows.extend(item for item in page if isinstance(item, dict))
            pagination = payload.get("pagination") or {}
            total = int(pagination.get("total", len(rows)))
            page_count += 1
            if len(rows) >= total or not page:
                break
            if max_pages is not None and page_count >= max_pages:
                break
            offset += len(page)
        return rows

    def search_customers(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/customers", filters)

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self.get(f"/crm/customers/{customer_id}")

    def list_opportunities(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/opportunities", filters)

    def list_orders(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/orders", filters)

    def list_invoices(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/crm/invoices", filters)

    def list_calls(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/calls", filters)

    def get_call(self, call_id: str) -> dict[str, Any]:
        return self.get(f"/calls/{call_id}")

    def search_transcript(
        self,
        call_id: str,
        search: str | None = None,
        speaker: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        payload = self.get(
            f"/calls/{call_id}/transcript",
            {
                "search": search,
                "speaker": speaker,
                "limit": min(limit, 200),
                "offset": offset,
            },
        )
        segments = payload.get("segments", [])
        return [item for item in segments if isinstance(item, dict)]

    def list_production_orders(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/production-orders", filters)

    def find_production_order_by_lot(
        self,
        lot_id: str,
        customer_id: str | None = None,
        sku: str | None = None,
    ) -> dict[str, Any] | None:
        filters = {
            key: value
            for key, value in {"customer_id": customer_id, "sku": sku}.items()
            if value
        }
        rows = self.list_all(
            "/erp/production-orders",
            filters,
            max_pages=None if filters else 5,
        )
        return next(
            (
                row
                for row in rows
                if str(row.get("lot_id") or row.get("id") or "") == lot_id
            ),
            None,
        )

    def list_inventory(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/inventory", filters)

    def list_suppliers(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/suppliers", filters)

    def get_bom(self, sku: str) -> list[dict[str, Any]]:
        rows = self.list_all("/erp/bom", {"sku": sku})
        components: list[dict[str, Any]] = []
        for row in rows:
            nested = row.get("components")
            if not isinstance(nested, list):
                components.append(row)
                continue
            for component in nested:
                if not isinstance(component, dict):
                    continue
                components.append(
                    {
                        **component,
                        "product_sku": row.get("sku", sku),
                        "product_name": row.get("product_name"),
                    }
                )
        return components

    def list_shipments(self, **filters: Any) -> list[dict[str, Any]]:
        return self.list_all("/erp/shipments", filters)
