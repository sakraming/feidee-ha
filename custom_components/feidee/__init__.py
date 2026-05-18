"""The Feidee (飞蛋记账) integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_BOOK_ID, CONF_BOOK_NAME, CONF_BOOKS, CONF_ENABLED_SENSORS, DOMAIN
from .coordinator import FeideeDataUpdateCoordinator
from .sensor_types import DEFAULT_ENABLED_SENSORS

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate config entries to current format."""
    data = dict(entry.data)
    version = entry.version

    if version < 2:
        if CONF_BOOKS not in data and CONF_BOOK_ID in data:
            book_id = data.pop(CONF_BOOK_ID)
            book_name = data.pop(CONF_BOOK_NAME, book_id)
            data[CONF_BOOKS] = [{"id": book_id, "name": book_name}]
        version = 2

    if version < 3:
        if CONF_ENABLED_SENSORS not in data:
            data[CONF_ENABLED_SENSORS] = list(DEFAULT_ENABLED_SENSORS)
        version = 3

    if version != entry.version or data != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=data, version=version)
        _LOGGER.debug("Migrated Feidee config entry %s to version %s", entry.entry_id, version)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = FeideeDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_forward_entry_unloads(
        entry, PLATFORMS
    ):
        coordinator: FeideeDataUpdateCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
