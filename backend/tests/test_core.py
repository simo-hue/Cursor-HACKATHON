from __future__ import annotations

import unittest
from typing import Any

from fastapi.testclient import TestClient

from app.api_client import AlDenteAPI
from app.config import Settings
from app.router import classify_fast
from main import app


class FakeAPI(AlDenteAPI):
    def __init__(self, pages: dict[int, dict[str, Any]]) -> None:
        self.pages = pages
        self.settings = Settings(mock_api_token="test")

    def list_page(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.pages[offset]


class APIClientTests(unittest.TestCase):
    def test_list_all_uses_pagination_total(self) -> None:
        api = FakeAPI(
            {
                0: {
                    "data": [{"id": "A"}, {"id": "B"}],
                    "pagination": {"offset": 0, "limit": 2, "total": 3},
                },
                2: {
                    "data": [{"id": "C"}],
                    "pagination": {"offset": 2, "limit": 2, "total": 3},
                },
            }
        )

        self.assertEqual([row["id"] for row in api.list_all("/items")], ["A", "B", "C"])

    def test_bom_rows_are_flattened_to_components(self) -> None:
        api = FakeAPI(
            {
                0: {
                    "data": [
                        {
                            "sku": "PAS-SPA-500",
                            "product_name": "Spaghetti",
                            "components": [
                                {
                                    "raw_sku": "RAW-SEM-003",
                                    "description": "Durum semolina",
                                }
                            ],
                        }
                    ],
                    "pagination": {"offset": 0, "limit": 200, "total": 1},
                }
            }
        )

        self.assertEqual(
            api.get_bom("PAS-SPA-500"),
            [
                {
                    "raw_sku": "RAW-SEM-003",
                    "description": "Durum semolina",
                    "product_sku": "PAS-SPA-500",
                    "product_name": "Spaghetti",
                }
            ],
        )


class RouterTests(unittest.TestCase):
    def test_direct_entity_routes(self) -> None:
        self.assertEqual(
            classify_fast("Tell me about customer CUST-0132").handler,
            "crm_customer_lookup",
        )
        self.assertEqual(
            classify_fast("Summarize opportunity OPP-2075").handler,
            "crm_opportunity_lookup",
        )
        self.assertEqual(
            classify_fast("What is the production status for SKU PAS-SPA-500?").handler,
            "erp_lot_status",
        )
        self.assertEqual(
            classify_fast("Does a customer named Supermercati Bianchi exist?").handler,
            "crm_customer_lookup",
        )


class ContractTests(unittest.TestCase):
    client = TestClient(app)

    def assert_contract(self, payload: dict[str, Any]) -> None:
        self.assertEqual(
            set(payload),
            {"answer", "sources", "verticale", "artifact_url"},
        )
        self.assertIsInstance(payload["answer"], str)
        self.assertIsInstance(payload["sources"], list)
        self.assertIn(payload["verticale"], {"crm", "erp", "calls", "kb"})

    def test_invalid_request_still_returns_contract_with_http_200(self) -> None:
        response = self.client.post("/ask", json={})

        self.assertEqual(response.status_code, 200)
        self.assert_contract(response.json())

    def test_inline_html_keeps_artifact_url_null(self) -> None:
        response = self.client.post(
            "/ask",
            json={"question": "Generate an HTML deck summarizing the returns policy."},
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_contract(payload)
        self.assertIn("<html", payload["answer"].lower())
        self.assertIsNone(payload["artifact_url"])

    def test_kb_answer_uses_document_source(self) -> None:
        response = self.client.post(
            "/ask",
            json={"question": "What is the shelf life for SKU PAS-SPA-500?"},
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_contract(payload)
        self.assertIn("DOC-001", payload["sources"])

    def test_returns_policy_uses_authoritative_document(self) -> None:
        response = self.client.post(
            "/ask",
            json={"question": "Summarize the returns and quality policy."},
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assert_contract(payload)
        self.assertEqual(payload["sources"], ["DOC-011"])


if __name__ == "__main__":
    unittest.main()
