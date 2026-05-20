"""Shared helpers for Feidee integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .api import DEFAULT_DEVICE_ID
from .const import CONF_BOOK_ID, CONF_BOOK_NAME, CONF_BOOKS, CONF_ENABLED_SENSORS
from .sensor_types import DEFAULT_ENABLED_SENSORS, validate_enabled_sensors


def get_books_from_entry(entry: ConfigEntry) -> list[dict[str, str]]:
    if CONF_BOOKS in entry.data:
        return [
            {"id": str(b["id"]), "name": str(b["name"])}
            for b in entry.data[CONF_BOOKS]
        ]
    if CONF_BOOK_ID in entry.data:
        return [
            {
                "id": str(entry.data[CONF_BOOK_ID]),
                "name": str(entry.data.get(CONF_BOOK_NAME, entry.data[CONF_BOOK_ID])),
            }
        ]
    return []


def get_enabled_sensors_from_entry(entry: ConfigEntry) -> list[str]:
    """Return user-selected sensor types for this config entry."""
    enabled = entry.data.get(CONF_ENABLED_SENSORS)
    if not enabled:
        return list(DEFAULT_ENABLED_SENSORS)
    validated = validate_enabled_sensors(list(enabled))
    return validated or list(DEFAULT_ENABLED_SENSORS)


def device_id_for_entry(entry: ConfigEntry) -> str:
    """Use the same device fingerprint as the verified 随手记.py demo."""
    return DEFAULT_DEVICE_ID
