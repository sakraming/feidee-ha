"""Config flow for Feidee."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .api import FeideeClient
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
PROBE_DEVICE_ID = "fed-ha-config-flow-probe"

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


class CannotConnect(HomeAssistantError):
    """Unable to connect to Feidee API."""


class InvalidAuth(HomeAssistantError):
    """Invalid credentials."""


class NoBooks(HomeAssistantError):
    """No cloud books found."""


async def _validate_login(phone: str, password: str) -> list[dict[str, Any]]:
    client = FeideeClient(phone, password, device_id=PROBE_DEVICE_ID)
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            phone = user_input[CONF_PHONE]
            password = user_input[CONF_PASSWORD]
            try:
                books = await _validate_login(phone, password)
            except httpx.HTTPStatusError as err:
                _LOGGER.error("Login failed: %s", err)
                errors["base"] = "invalid_auth"
            except httpx.RequestError as err:
                _LOGGER.error("Connection error: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.exception("Unexpected error during login: %s", err)
                errors["base"] = "unknown"
            else:
                if not books:
                    errors["base"] = "no_books"
                else:
                    self._phone = phone
                    self._password = password
                    self._books = books
                    return await self.async_step_book()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
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

    @staticmethod
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
