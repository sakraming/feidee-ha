#!/usr/bin/env python3
"""Interactive Feidee login debug test.

Run from repo root:
  .venv/bin/python scripts/test_login.py

This version prints detailed request/response diagnostics for:
- captcha session
- captcha verification
- login
- book listing
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components/feidee"))

from api import FeideeApiError, FeideeAuthError, FeideeClient, normalize_password, normalize_phone


def _prompt(label: str) -> str:
    value = input(label).strip()
    if not value:
        raise SystemExit(f"{label} cannot be empty")
    return value


def _pretty(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


async def main() -> int:
    phone = normalize_phone(_prompt("Phone number: "))
    password = normalize_password(_prompt("Password: "))
    client = FeideeClient(phone, password)
    print("\n=== Feidee debug test start ===")
    print(f"Phone (normalized): {phone[:3]}****{phone[-4:]}  len={len(phone)}")
    print(f"Device ID: {client._ctx.device_id}")
    try:
        print("\n--- Step 1: login() direct ---")
        token = await client.login()
        print("login raw token response:")
        print(_pretty(token))
        print(f"Login OK, token prefix: {str(token.get('access_token', ''))[:20]}...")

        print("\n--- Step 2: list_books() ---")
        books = await client.list_books()
        print(f"Books: {len(books)}")
        for b in books:
            print(f"  - [{b.get('id')}] {b.get('name')}")
    except FeideeAuthError as e:
        print("\n=== AUTH ERROR ===")
        print(f"code={e.code} http={e.status_code} msg={e}")
        print(f"body={e.response_body}")
        return 2
    except FeideeApiError as e:
        print("\n=== API ERROR ===")
        print(f"code={e.code} http={e.status_code} msg={e}")
        print(f"body={e.response_body}")
        return 3
    finally:
        await client.close()

    print("\n=== All checks passed ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
