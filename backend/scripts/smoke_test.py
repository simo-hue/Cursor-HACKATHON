from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings  # noqa: E402
from main import app  # noqa: E402


def assert_schema(payload: dict) -> None:
    assert set(("answer", "sources", "verticale", "artifact_url")) <= payload.keys()
    assert isinstance(payload["answer"], str)
    assert isinstance(payload["sources"], list)
    assert payload["verticale"] in {"crm", "erp", "calls", "kb"}
    assert payload["artifact_url"] is None or isinstance(payload["artifact_url"], str)


def main() -> int:
    client = TestClient(app)
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []

    health = client.get("/health")
    checks.append(("health", health.status_code == 200 and health.json() == {"status": "ok"}, health.text))

    ui = client.get("/")
    checks.append(("ui", ui.status_code == 200 and "Al Dente Company Brain" in ui.text, ui.text[:120]))

    kb = client.post(
        "/ask",
        json={"question": "What is the shelf life and declared allergens for PAS-SPA-500?"},
    )
    kb_payload = kb.json()
    try:
        assert_schema(kb_payload)
        kb_ok = all(term in kb_payload["answer"].lower() for term in ("36 months", "gluten", "soy", "mustard"))
    except AssertionError:
        kb_ok = False
    checks.append(("kb question", kb.status_code == 200 and kb_ok, str(kb_payload)))

    if settings.has_mock_api:
        crm = client.post(
            "/ask",
            json={"question": "How many open opportunities does CUST-0132 have, and what is their total value?"},
        )
        crm_payload = crm.json()
        checks.append(
            (
                "crm question",
                crm.status_code == 200 and crm_payload.get("verticale") == "crm" and "740" in crm_payload.get("answer", ""),
                str(crm_payload),
            )
        )
    else:
        print("SKIP crm question - MOCK_API_TOKEN is not configured")

    artifact = client.post(
        "/ask",
        json={"question": "Generate a PDF summarizing the returns and quality policy."},
    )
    artifact_payload = artifact.json()
    artifact_path = urlparse(artifact_payload.get("artifact_url") or "").path
    artifact_get = client.get(artifact_path) if artifact_path else None
    checks.append(
        (
            "binary artifact",
            bool(
                artifact.status_code == 200
                and artifact_payload.get("artifact_url", "").startswith("http")
                and artifact_get
                and artifact_get.status_code == 200
                and artifact_get.content.startswith(b"%PDF")
            ),
            str(artifact_payload),
        )
    )

    graph = client.get("/graph-data")
    graph_payload = graph.json()
    checks.append(
        (
            "graph",
            graph.status_code == 200
            and isinstance(graph_payload.get("nodes"), list)
            and isinstance(graph_payload.get("edges"), list)
            and len(graph_payload["nodes"]) > 0,
            str({key: len(value) if isinstance(value, list) else value for key, value in graph_payload.items()}),
        )
    )

    failed = 0
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
        if not ok:
            print(f"  {detail}")
            failed += 1
    print(f"\nSummary: {len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
