#!/usr/bin/env python3
"""Test Feidee login + list books (same code path as HA config flow).

Usage:
  export FEIDEE_PHONE=13800138000
  export FEIDEE_PASSWORD='your_plain_password'
  python3 scripts/test_login.py

Or from repo root with venv:
  .venv/bin/python scripts/test_login.py
"""
from __future__ import annotations

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components/feidee"))

from api import FeideeApiError, FeideeAuthError, FeideeClient, normalize_password, normalize_phone


async def main() -> int:
    phone = os.environ.get("FEIDEE_PHONE", "").strip()
    password = os.environ.get("FEIDEE_PASSWORD", "").strip()
    if not phone or not password:
        print("Set FEIDEE_PHONE and FEIDEE_PASSWORD environment variables.")
        return 1

    phone = normalize_phone(phone)
    password = normalize_password(password)
    client = FeideeClient(phone, password)
    print(f"Phone (normalized): {phone[:3]}****{phone[-4:]}  len={len(phone)}")
    print(f"Device ID: {client._ctx.device_id}")
    try:
        token = await client.login()
        print(f"Login OK, token prefix: {str(token.get('access_token', ''))[:20]}...")
        books = await client.list_books()
        print(f"Books: {len(books)}")
        for b in books:
            print(f"  - [{b.get('id')}] {b.get('name')}")
    except FeideeAuthError as e:
        print(f"LOGIN FAILED: code={e.code} http={e.status_code} msg={e}")
        return 2
    except FeideeApiError as e:
        print(f"API ERROR: code={e.code} http={e.status_code} msg={e}")
        return 3
    finally:
        await client.close()

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
