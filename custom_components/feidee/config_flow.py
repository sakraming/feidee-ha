"""Config flow for Feidee."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import (
    ERR_CLIENT_PARAMS,
    ERR_INVALID_CREDENTIALS,
    FeideeApiError,
    FeideeAuthError,
    FeideeClient,
    normalize_password,
    normalize_phone,
)
from .const import (
    CONF_BOOKS,
    CONF_ENABLED_SENSORS,
    CONF_PASSWORD,
    CONF_PHONE,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .sensor_types import sensor_selector_options, validate_enabled_sensors

_LOGGER = logging.getLogger(__name__)
CONF_BOOK_IDS = "book_ids"
CONF_SENSOR_KEYS = "sensor_keys"

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PHONE): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _sensor_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=sensor_selector_options(),
            mode=selector.SelectSelectorMode.LIST,
            multiple=True,
        )
    )


def _map_login_error(err: Exception) -> str:
    if isinstance(err, FeideeAuthError):
        body = (getattr(err, "response_body", "") or "").lower()
        if err.code == ERR_INVALID_CREDENTIALS:
            return "invalid_auth"
        if err.code == ERR_CLIENT_PARAMS:
            return "client_error"
        if err.status_code == 500 and ("captcha" in body or "verification" in body):
            return "captcha_failed"
        if err.status_code in {429, 403} and ("captcha" in body or "vcid" in body or "vid" in body):
            return "captcha_required"
    if isinstance(err, FeideeApiError):
        return "cannot_connect"
    if isinstance(err, httpx.RequestError):
        return "cannot_connect"
    return "unknown"


async def _validate_login(phone: str, password: str) -> list[dict[str, Any]]:
    phone = normalize_phone(phone)
    password = normalize_password(password)
    client = FeideeClient(phone, password)
    try:
        await client.login()
        books = await client.list_books()
    finally:
        await client.close()
    return books


class FeideeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Feidee."""

    VERSION = 3

    def __init__(self) -> None:
        self._phone: str = ""
        self._password: str = ""
        self._books: list[dict[str, Any]] = []
        self._selected_books: list[dict[str, str]] = []
        self._captcha_vcid: str = ""
        self._captcha_image_url: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = normalize_phone(user_input[CONF_PHONE])
            password = normalize_password(user_input[CONF_PASSWORD])
            client = FeideeClient(phone, password)
            try:
                login_result = await client.prepare_captcha()
            except httpx.RequestError as err:
                _LOGGER.error("Connection error: %s", err)
                await client.close()
                errors["base"] = "cannot_connect"
            except FeideeAuthError as err:
                _LOGGER.error(
                    "Feidee auth flow failed: %s (code=%s http=%s body=%s)",
                    err,
                    getattr(err, "code", None),
                    getattr(err, "status_code", None),
                    getattr(err, "response_body", None),
                )
                await client.close()
                errors["base"] = _map_login_error(err)
            except FeideeApiError as err:
                _LOGGER.error(
                    "Feidee API failed: %s (code=%s http=%s body=%s)",
                    err,
                    getattr(err, "code", None),
                    getattr(err, "status_code", None),
                    getattr(err, "response_body", None),
                )
                await client.close()
                errors["base"] = _map_login_error(err)
            else:
                self._phone = phone
                self._password = password
                self._books = []
                self._captcha_vcid = str(login_result.get("vcid", ""))
                self._captcha_image_url = str(login_result.get("image_url", ""))
                await client.close()
                return await self.async_step_captcha()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_captcha(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            captcha_code = user_input.get("captcha_code", "").strip()
            if not captcha_code:
                errors["base"] = "captcha_required"
            else:
                client = FeideeClient(self._phone, self._password)
                try:
                    await client.verify_captcha(self._captcha_vcid, captcha_code)
                    await client.login()
                    books = await client.list_books()
                except httpx.RequestError as err:
                    _LOGGER.error("Connection error during captcha flow: %s", err)
                    errors["base"] = "cannot_connect"
                except FeideeAuthError as err:
                    _LOGGER.error(
                        "Captcha/login failed: %s (code=%s http=%s body=%s)",
                        err,
                        getattr(err, "code", None),
                        getattr(err, "status_code", None),
                        getattr(err, "response_body", None),
                    )
                    errors["base"] = _map_login_error(err)
                except FeideeApiError as err:
                    _LOGGER.error(
                        "Captcha/API failed: %s (code=%s http=%s body=%s)",
                        err,
                        getattr(err, "code", None),
                        getattr(err, "status_code", None),
                        getattr(err, "response_body", None),
                    )
                    errors["base"] = _map_login_error(err)
                else:
                    await client.close()
                    if not books:
                        errors["base"] = "no_books"
                    else:
                        self._books = books
                        return await self.async_step_book()
                finally:
                    await client.close()

        schema = vol.Schema({vol.Required("captcha_code"): str})
        description_placeholders = {"image_url": self._captcha_image_url or ""}
        return self.async_show_form(
            step_id="captcha",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )

    async def async_step_book(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            selected_ids: list[str] = user_input[CONF_BOOK_IDS]
            if not selected_ids:
                return self.async_show_form(
                    step_id="book",
                    data_schema=self._book_schema(),
                    errors={"base": "no_books_selected"},
                )

            books_by_id = {b["id"]: b for b in self._books}
            selected_books = []
            for book_id in selected_ids:
                book = books_by_id.get(book_id)
                if book is None:
                    return self.async_abort(reason="book_not_found")
                selected_books.append({"id": book["id"], "name": book["name"]})

            self._selected_books = selected_books
            return await self.async_step_sensors()

        return self.async_show_form(
            step_id="book",
            data_schema=self._book_schema(),
        )

    async def async_step_sensors(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            enabled = validate_enabled_sensors(user_input[CONF_SENSOR_KEYS])
            if not enabled:
                return self.async_show_form(
                    step_id="sensors",
                    data_schema=self._sensors_schema(),
                    errors={"base": "no_sensors_selected"},
                )

            await self.async_set_unique_id(self._phone)
            self._abort_if_unique_id_configured()

            title = (
                self._selected_books[0]["name"]
                if len(self._selected_books) == 1
                else f"飞蛋记账 ({self._phone})"
            )

            return self.async_create_entry(
                title=title,
                data={
                    CONF_PHONE: self._phone,
                    CONF_PASSWORD: self._password,
                    CONF_BOOKS: self._selected_books,
                    CONF_ENABLED_SENSORS: enabled,
                },
                options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
            )

        return self.async_show_form(
            step_id="sensors",
            data_schema=self._sensors_schema(),
        )

    def _book_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_BOOK_IDS): selector.selector(
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": b["id"], "label": b["name"]}
                                for b in self._books
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                            multiple=True,
                        )
                    )
                )
            }
        )

    def _sensors_schema(self) -> vol.Schema:
        return vol.Schema({vol.Required(CONF_SENSOR_KEYS): selector.selector(_sensor_selector())})



@callback
def async_get_options_flow(
    config_entry: config_entries.ConfigEntry,
) -> FeideeOptionsFlowHandler:
    return FeideeOptionsFlowHandler(config_entry)


class FeideeOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Feidee."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            enabled = validate_enabled_sensors(
                user_input.get(CONF_SENSOR_KEYS, self.config_entry.data.get(CONF_ENABLED_SENSORS, []))
            )
            if not enabled:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(),
                    errors={"base": "no_sensors_selected"},
                )

            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    **self.config_entry.data,
                    CONF_ENABLED_SENSORS: enabled,
                },
                options={
                    **self.config_entry.options,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                },
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        current = self.config_entry.data.get(CONF_ENABLED_SENSORS, [])
        return vol.Schema(
            {
                vol.Required(CONF_SENSOR_KEYS, default=current): selector.selector(
                    _sensor_selector()
                ),
                vol.Required(CONF_SCAN_INTERVAL, default=interval): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=300, max=3600),
                ),
            }
        )
