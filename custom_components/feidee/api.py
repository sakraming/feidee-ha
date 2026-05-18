"""Feidee (飞蛋记账) cloud API client."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from typing import Any, Optional

import httpx

_LOGGER = logging.getLogger(__name__)

# --- API signing (reverse-engineered; required for requests) ---
BIZ_CLIENT_KEY = "PiVEoJM9OHFS8xFlnD3CuSrJgRgyVLwS"
BIZ_SECRET = "pQhGxs0I84zQgeU8"
LOGIN_CLIENT_KEY = "520BFC1EA31D45678A9B865668A47F40"
LOGIN_SECRET = ""

# --- Service endpoints (fixed infrastructure) ---
AUTH_BASE = "https://auth.feidee.net"
USER_BASE = "https://userapi.feidee.net"
YUN_BASE = "https://yun.feidee.net"

# --- Protocol constants (mimic official web client; not user-configurable) ---
APP_ID = "cab-web"
ORIGIN = "https://www.feidee.com"
REFERER = "https://www.feidee.com/"
LOGIN_TYPE = "MD5-H5"
LOGIN_MINOR_VERSION = "2"
GRANT_TYPE = "password_web"
ENCODE_VERSION = "V4"
OAUTH_SCOPE = "user"
ACCOUNTS_SCENE = "Common"

# --- Client fingerprint defaults (web cab-web profile) ---
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
DEFAULT_DEVICE_MODEL = "os"
DEFAULT_DEVICE_PLATFORM = "MacIntel"
DEFAULT_PRODUCT_NAME = "cab-web"
DEFAULT_PRODUCT_VERSION = "148.0.0.0"
DEFAULT_LOCALE = "zh-CN"
DEFAULT_TIME_ZONE = "Asia/Shanghai"


def build_device_json(device_id: str) -> str:
    """Build Device header JSON; device_id should be stable per HA config entry."""
    return json.dumps(
        {
            "model": DEFAULT_DEVICE_MODEL,
            "platform": DEFAULT_DEVICE_PLATFORM,
            "os_version": "",
            "device_id": device_id,
            "product_name": DEFAULT_PRODUCT_NAME,
            "product_version": DEFAULT_PRODUCT_VERSION,
            "locale": DEFAULT_LOCALE,
            "time_zone": DEFAULT_TIME_ZONE,
        },
        separators=(",", ":"),
    )


class _RequestContext:
    """Per-client request context (device id + cached device JSON)."""

    def __init__(self, device_id: str, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.device_id = device_id
        self.user_agent = user_agent
        self.device_json = build_device_json(device_id)


def _gen_sign(client_key: str, secret: str) -> tuple[str, str, str]:
    nonce = str(random.randint(0, 10**16)).zfill(16)
    timestamp = str(int(time.time() * 1000))
    raw = client_key + nonce + timestamp + secret
    sign = hashlib.md5(raw.encode()).hexdigest()
    return nonce, timestamp, sign


def gen_login_headers(ctx: _RequestContext) -> dict[str, str]:
    nonce, ts, sign = _gen_sign(LOGIN_CLIENT_KEY, LOGIN_SECRET)
    return {
        "App-Id": APP_ID,
        "Type": LOGIN_TYPE,
        "Minor-Version": LOGIN_MINOR_VERSION,
        "Client-Key": LOGIN_CLIENT_KEY,
        "Nonce-Str": nonce,
        "Timestamp": ts,
        "Sign": sign,
        "Content-Type": "application/json",
        "Device": ctx.device_json,
        "Origin": ORIGIN,
        "Referer": REFERER,
        "User-Agent": ctx.user_agent,
    }


def gen_business_headers(
    ctx: _RequestContext,
    access_token: str,
    trading_entity: Optional[str] = None,
) -> dict[str, str]:
    nonce, ts, sign = _gen_sign(BIZ_CLIENT_KEY, BIZ_SECRET)
    headers = {
        "Client-Key": BIZ_CLIENT_KEY,
        "Nonce-Str": nonce,
        "Timestamp": ts,
        "Sign": sign,
        "Authorization": f"Bearer {access_token}",
        "Device": ctx.device_json,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": ORIGIN,
        "Referer": REFERER,
        "User-Agent": ctx.user_agent,
    }
    if trading_entity:
        headers["Trading-Entity"] = trading_entity
    return headers


async def api_login(
    client: httpx.AsyncClient, ctx: _RequestContext, phone: str, password: str
) -> dict[str, Any]:
    password_sha1 = hashlib.sha1(password.encode()).hexdigest()
    params = {
        "grant_type": GRANT_TYPE,
        "encode_version": ENCODE_VERSION,
        "scope": OAUTH_SCOPE,
        "username": phone,
        "password": password_sha1,
        "vcid": "",
        "vid": "",
    }
    response = await client.get(
        f"{AUTH_BASE}/v2/oauth2/authorize",
        params=params,
        headers=gen_login_headers(ctx),
    )
    response.raise_for_status()
    return response.json()


async def api_list_books(
    client: httpx.AsyncClient, ctx: _RequestContext, access_token: str
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{YUN_BASE}/cab-index-ws/v3/book-group/cloud",
        headers=gen_business_headers(ctx, access_token),
    )
    response.raise_for_status()
    return response.json().get("cloud_book_list", [])


async def api_get_rollup_summary(
    client: httpx.AsyncClient,
    ctx: _RequestContext,
    access_token: str,
    book_id: str,
    group_key: str = "TIME_MONTH",
    group_id: Optional[str] = None,
    category_type: str = "Expense",
    group_by: str = "CATEGORY_SECOND",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "group": {"group_by": group_by, "show_all": False},
        "query": {
            "exclude_null_category": True,
            "category_types": [category_type],
        },
        "sort": {"order_by": "DESC", "sort_by": "GROUP_ID"},
    }
    if group_id:
        body["group_filter"] = {"group_key": group_key, "group_id": group_id}

    response = await client.post(
        f"{YUN_BASE}/cab-query-ws/v2/statistics/rollup-groups",
        json=body,
        headers=gen_business_headers(ctx, access_token, trading_entity=book_id),
    )
    response.raise_for_status()
    return response.json()


async def api_get_accounts(
    client: httpx.AsyncClient,
    ctx: _RequestContext,
    access_token: str,
    book_id: str,
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{YUN_BASE}/cab-config-ws/v2/account-book/accounts",
        params={"scene": ACCOUNTS_SCENE},
        headers=gen_business_headers(ctx, access_token, trading_entity=book_id),
    )
    response.raise_for_status()
    return response.json().get("data", [])


def metric_value(summary: dict[str, Any], key: str) -> float:
    for item in summary.get("metric_data", []):
        if item.get("key") == key:
            try:
                return float(item.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def parse_top_categories(summary: dict[str, Any], limit: int = 5) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in summary.get("data", [])[:limit]:
        name = item.get("group_info", {}).get("group_name", "?")
        amount = next(
            (m["value"] for m in item.get("metric_data", []) if m["key"] == "EXPENSE"),
            "0",
        )
        result.append({"name": name, "amount": amount})
    return result


def parse_account_balances(accounts: list[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for group in accounts:
        for account in group.get("accounts", []):
            account_id = account.get("id")
            if not account_id:
                continue
            result.append(
                {
                    "id": str(account_id),
                    "name": account.get("name", "?"),
                    "balance": account.get("balance", "0"),
                    "type": account.get("type", "?"),
                    "group": group.get("name", ""),
                }
            )
    return result


def sum_account_balances(accounts: list[dict[str, Any]]) -> float:
    total = 0.0
    for item in parse_account_balances(accounts):
        try:
            total += float(item["balance"])
        except (TypeError, ValueError):
            continue
    return total


class FeideeClient:
    """Async Feidee API client with automatic re-login on 401."""

    def __init__(self, phone: str, password: str, device_id: str) -> None:
        self.phone = phone
        self.password = password
        self._ctx = _RequestContext(device_id=device_id)
        self.access_token: Optional[str] = None
        self._http = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    async def login(self) -> None:
        result = await api_login(self._http, self._ctx, self.phone, self.password)
        self.access_token = result["access_token"]
        _LOGGER.debug("Feidee login successful")

    async def _call(self, func, *args, **kwargs):
        if not self.access_token:
            await self.login()
        try:
            return await func(self._http, self._ctx, self.access_token, *args, **kwargs)
        except httpx.HTTPStatusError as err:
            if err.response.status_code == 401:
                _LOGGER.warning("Feidee token expired, re-logging in")
                await self.login()
                return await func(
                    self._http, self._ctx, self.access_token, *args, **kwargs
                )
            raise

    async def list_books(self) -> list[dict[str, Any]]:
        return await self._call(api_list_books)

    async def get_rollup_summary(self, book_id: str, **kwargs) -> dict[str, Any]:
        return await self._call(api_get_rollup_summary, book_id, **kwargs)

    async def get_accounts(self, book_id: str) -> list[dict[str, Any]]:
        return await self._call(api_get_accounts, book_id)
