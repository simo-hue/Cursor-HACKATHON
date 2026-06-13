"""Temporary diagnostic: verify the mock API is reachable with the configured token.

Prints only status codes and response shapes, never the token itself.
"""
from __future__ import annotations

import sys
import traceback

sys.path.insert(0, ".")

from app.api_client import AlDenteAPI, APIConfigurationError, APIError  # noqa: E402
from app.config import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    print(f"has_mock_api         : {settings.has_mock_api}")
    print(f"mock_api_base_url    : {settings.mock_api_base_url}")
    tok = settings.mock_api_token or ""
    print(f"token configured     : {bool(tok)} (len={len(tok)})")
    print(f"has_llm              : {settings.has_llm}")
    print(f"public_base_url      : {settings.public_base_url}")
    print("-" * 60)

    api = AlDenteAPI(settings)
    probes = [
        ("/crm/customers", {"limit": 2}),
        ("/crm/opportunities", {"limit": 2}),
        ("/calls", {"limit": 2}),
        ("/erp/inventory", {"limit": 2}),
    ]
    for path, params in probes:
        try:
            payload = api.get(path, params)
            data = payload.get("data", [])
            pag = payload.get("pagination", {})
            print(f"OK   {path:28} rows={len(data):<3} total={pag.get('total')}")
        except APIConfigurationError as exc:
            print(f"CFG  {path:28} {exc}")
        except APIError as exc:
            print(f"ERR  {path:28} status={exc.status_code} detail={str(exc)[:120]}")
        except Exception as exc:  # noqa: BLE001
            print(f"EXC  {path:28} {type(exc).__name__}: {exc}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
