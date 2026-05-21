"""Feidee (飞蛋记账) cloud API client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import tempfile
import time
from pathlib import Path
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

# Must match the working cab-web device_id from 随手记.py demo
DEFAULT_DEVICE_ID = "fed-8e89c1f1-183f-4829-8c95-179232e50a02"
DEVICE_JSON = json.dumps(
    {
        "model": DEFAULT_DEVICE_MODEL,
        "platform": DEFAULT_DEVICE_PLATFORM,
        "os_version": "",
        "device_id": DEFAULT_DEVICE_ID,
        "product_name": DEFAULT_PRODUCT_NAME,
        "product_version": DEFAULT_PRODUCT_VERSION,
        "locale": DEFAULT_LOCALE,
        "time_zone": DEFAULT_TIME_ZONE,
    },
    separators=(",", ":"),
)

# Feidee API error codes (auth)
ERR_INVALID_CREDENTIALS = 4112
ERR_CLIENT_PARAMS = 4099
CAPTCHA_BASE_URL = "https://cloud.feidee.com/"
CAPTCHA_VERIFY_BASE = "https://verification.feidee.net/v1/captcha/session"


class FeideeApiError(Exception):
    """Feidee API returned an error response."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.response_body = response_body


class FeideeAuthError(FeideeApiError):
    """Authentication failed."""


def normalize_phone(phone: str) -> str:
    """Normalize phone for Feidee login (same as 随手记.py: 11-digit mobile, no 86 prefix)."""
    cleaned = re.sub(r"\D", "", phone.strip())
    if cleaned.startswith("86") and len(cleaned) > 11:
        cleaned = cleaned[2:]
    return cleaned


def normalize_password(password: str) -> str:
    return password.strip()


def resolve_device_id(device_id: str | None = None) -> str:
    return device_id or DEFAULT_DEVICE_ID


class _RequestContext:
    def __init__(self, device_id: str | None = None, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.device_id = resolve_device_id(device_id)
        self.user_agent = user_agent
        # Login/business headers use the same fixed DEVICE_JSON as 随手记.py
        self.device_json = DEVICE_JSON if self.device_id == DEFAULT_DEVICE_ID else json.dumps(
            {
                "model": DEFAULT_DEVICE_MODEL,
                "platform": DEFAULT_DEVICE_PLATFORM,
                "os_version": "",
                "device_id": self.device_id,
                "product_name": DEFAULT_PRODUCT_NAME,
                "product_version": DEFAULT_PRODUCT_VERSION,
                "locale": DEFAULT_LOCALE,
                "time_zone": DEFAULT_TIME_ZONE,
            },
            separators=(",", ":"),
        )


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


def _parse_error_response(response: httpx.Response) -> tuple[int | None, str]:
    try:
        data = response.json()
        if isinstance(data, dict):
            code = data.get("code")
            message = data.get("message") or data.get("msg") or response.text
            return (int(code) if code is not None else None, str(message))
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return (None, response.text[:500])


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return _first_text(value[0])
    if isinstance(value, dict):
        for key in ("url", "image_url", "img_url", "src", "code", "value", "data"):
            if key in value:
                return _first_text(value[key])
    return ""


def _extract_captcha_image_url(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("image_url", "url", "image", "img", "captcha_url", "base_url"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                if value.startswith("http"):
                    return value
                if key == "base_url":
                    continue
                return f"{CAPTCHA_BASE_URL}{value.lstrip('/')}"
        for value in payload.values():
            found = _extract_captcha_image_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_captcha_image_url(item)
            if found:
                return found
    elif isinstance(payload, str):
        if payload.startswith("http"):
            return payload
        if "vfcenter/" in payload:
            return f"{CAPTCHA_BASE_URL}{payload.lstrip('/')}"
    return ""


async def _get_captcha_session(client: httpx.AsyncClient, ctx: _RequestContext) -> dict[str, Any]:
    response = await client.get(
        "https://verification.feidee.net/v1/captcha/session/code",
        params={"style": "normal", "t": str(int(time.time() * 1000))},
        headers=gen_login_headers(ctx),
    )
    response.raise_for_status()
    return response.json()


async def _fetch_captcha_image(client: httpx.AsyncClient, image_url: str) -> Path:
    if not image_url.startswith("http"):
        image_url = f"{CAPTCHA_BASE_URL}{image_url.lstrip('/')}"
    response = await client.get(image_url, headers={"Referer": REFERER})
    response.raise_for_status()
    fd, tmp_path = tempfile.mkstemp(prefix="feidee_captcha_", suffix=".png")
    Path(tmp_path).write_bytes(response.content)
    return Path(tmp_path)


async def _verify_captcha(
    client: httpx.AsyncClient, ctx: _RequestContext, vcid: str, captcha_code: str
) -> dict[str, Any]:
    payload = {"s": json.dumps({"code": captcha_code}, ensure_ascii=False)}
    response = await client.post(
        f"{CAPTCHA_VERIFY_BASE}/{vcid}/code/verification",
        params={"t": str(int(time.time() * 1000))},
        json=payload,
        headers=gen_login_headers(ctx),
    )
    response.raise_for_status()
    return response.json()


async def api_prepare_login(
    client: httpx.AsyncClient, ctx: _RequestContext
) -> dict[str, Any]:
    session = await _get_captcha_session(client, ctx)
    vcid = str(session.get("vcid") or session.get("data", {}).get("vcid") or "")
    image_url = _extract_captcha_image_url(session)
    image_path: str | None = None
    if image_url:
        try:
            image_path = str(await _fetch_captcha_image(client, image_url))
        except Exception as exc:
            _LOGGER.warning("Failed to fetch captcha image: %s", exc)
    return {
        "vcid": vcid,
        "image_url": image_url,
        "image_path": image_path,
        "raw": session,
    }


async def api_verify_captcha(
    client: httpx.AsyncClient, ctx: _RequestContext, vcid: str, captcha_code: str
) -> dict[str, Any]:
    try:
        verified = await _verify_captcha(client, ctx, vcid, captcha_code)
    except httpx.HTTPStatusError as exc:
        raise FeideeAuthError(
            f"Captcha verification failed (HTTP {exc.response.status_code})",
            status_code=exc.response.status_code,
            response_body=exc.response.text[:500],
        ) from exc
    vid = str(
        verified.get("vid")
        or verified.get("data", {}).get("vid")
        or verified.get("token")
        or ""
    )
    if not vid:
        raise FeideeAuthError(
            "Captcha verification succeeded but no vid was returned",
            response_body=json.dumps(verified, ensure_ascii=False)[:500],
        )
    return {"vid": vid, "raw": verified}


async def api_login(
    client: httpx.AsyncClient, ctx: _RequestContext, phone: str, password: str
) -> dict[str, Any]:
    phone = normalize_phone(phone)
    password = normalize_password(password)
    password_sha1 = hashlib.sha1(password.encode()).hexdigest()
    vcid = getattr(ctx, "vcid", "")
    vid = getattr(ctx, "vid", "")

    params = {
        "grant_type": GRANT_TYPE,
        "encode_version": ENCODE_VERSION,
        "scope": OAUTH_SCOPE,
        "username": phone,
        "password": password_sha1,
        "vcid": vcid,
        "vid": vid,
    }
    response = await client.get(
        f"{AUTH_BASE}/v2/oauth2/authorize",
        params=params,
        headers=gen_login_headers(ctx),
    )

    try:
        data = response.json()
    except json.JSONDecodeError as err:
        raise FeideeAuthError(
            f"Invalid login response (HTTP {response.status_code})",
            status_code=response.status_code,
            response_body=response.text[:500],
        ) from err

    if response.is_success and isinstance(data, dict) and data.get("access_token"):
        return data

    code, message = _parse_error_response(response)
    if code in {5126} or response.status_code in {401, 403}:
        raise FeideeAuthError(
            message or "Captcha or login required",
            code=code,
            status_code=response.status_code,
            response_body=response.text[:500],
        )
    _LOGGER.warning(
        "Feidee login failed: HTTP %s code=%s message=%s phone=%s device_id=%s",
        response.status_code,
        code,
        message,
        phone[:3] + "****",
        ctx.device_id,
    )
    raise FeideeAuthError(
        message or "Login failed",
        code=code,
        status_code=response.status_code,
        response_body=response.text[:500],
    )


async def api_list_books(
    client: httpx.AsyncClient, ctx: _RequestContext, access_token: str
) -> list[dict[str, Any]]:
    response = await client.get(
        f"{YUN_BASE}/cab-index-ws/v3/book-group/cloud",
        headers=gen_business_headers(ctx, access_token),
    )
    if not response.is_success:
        code, message = _parse_error_response(response)
        raise FeideeApiError(
            message or "Failed to list books",
            code=code,
            status_code=response.status_code,
            response_body=response.text[:500],
        )
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

    def __init__(
        self,
        phone: str,
        password: str,
        device_id: str | None = None,
        vcid: str | None = None,
        vid: str | None = None,
    ) -> None:
        self.phone = normalize_phone(phone)
        self.password = normalize_password(password)
        self._ctx = _RequestContext(device_id)
        self._ctx.vcid = vcid or ""
        self._ctx.vid = vid or ""
        self.access_token: Optional[str] = None
        self._http: httpx.AsyncClient | None = None

    async def _ensure_http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = await asyncio.to_thread(httpx.AsyncClient, timeout=30.0)
        return self._http

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self) -> FeideeClient:
        await self.login()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def login(self) -> dict[str, Any]:
        http = await self._ensure_http()
        result = await api_login(http, self._ctx, self.phone, self.password)
        self.access_token = result["access_token"]
        _LOGGER.debug("Feidee login successful for device_id=%s", self._ctx.device_id)
        return result

    async def prepare_captcha(self) -> dict[str, Any]:
        http = await self._ensure_http()
        return await api_prepare_login(http, self._ctx)

    async def verify_captcha(self, vcid: str, captcha_code: str) -> dict[str, Any]:
        http = await self._ensure_http()
        verified = await api_verify_captcha(http, self._ctx, vcid, captcha_code)
        self._ctx.vcid = vcid
        self._ctx.vid = verified["vid"]
        return verified

    async def _call(self, func, *args, **kwargs):
        http = await self._ensure_http()
        if not self.access_token:
            await self.login()
        try:
            return await func(http, self._ctx, self.access_token, *args, **kwargs)
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
