"""Sensor platform for Feidee."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMoney
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_ACCOUNTS, ATTR_BOOK_ID, ATTR_BOOK_NAME, ATTR_TOP_CATEGORIES, DOMAIN
from .coordinator import FeideeDataUpdateCoordinator
from .helpers import get_enabled_sensors_from_entry
from .sensor_types import SENSOR_TYPES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: FeideeDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled = get_enabled_sensors_from_entry(entry)

    entities: list[SensorEntity] = [
        FeideeMetricSensor(coordinator, entry, book["id"], sensor_type)
        for book in coordinator.books
        for sensor_type in enabled
        if sensor_type in SENSOR_TYPES
    ]
    async_add_entities(entities)


def _book_device_info(entry: ConfigEntry, book_id: str, book_name: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{book_id}")},
        name=book_name,
        manufacturer="Feidee",
        model="Cloud Book",
    )


class FeideeMetricSensor(CoordinatorEntity, SensorEntity):
    """A user-selected metric sensor for one book."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfMoney.CNY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self,
        coordinator: FeideeDataUpdateCoordinator,
        entry: ConfigEntry,
        book_id: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        spec = SENSOR_TYPES[sensor_type]
        self._entry = entry
        self._book_id = book_id
        self._sensor_type = sensor_type
        self._data_key = spec["data_key"]
        self._extra_attr_keys = spec.get("extra_attributes", frozenset())
        self._attr_translation_key = spec["translation_key"]
        if icon := spec.get("icon"):
            self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{book_id}_{sensor_type}"
        self._book_data: dict = {}

    def _refresh_book_data(self) -> None:
        if self.coordinator.data:
            self._book_data = self.coordinator.data.get("books", {}).get(
                self._book_id, {}
            )
            self._attr_device_info = _book_device_info(
                self._entry,
                self._book_id,
                self._book_data.get("book_name", self._book_id),
            )

    @property
    def available(self) -> bool:
        self._refresh_book_data()
        return self.coordinator.last_update_success and bool(self._book_data)

    @property
    def native_value(self) -> float | None:
        self._refresh_book_data()
        value = self._book_data.get(self._data_key)
        return float(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict | None:
        self._refresh_book_data()
        if not self._book_data or not self.coordinator.data:
            return None

        attrs: dict = {
            ATTR_BOOK_ID: self._book_id,
            ATTR_BOOK_NAME: self._book_data.get("book_name"),
        }
        period = self.coordinator.data

        if "top_categories" in self._extra_attr_keys:
            attrs[ATTR_TOP_CATEGORIES] = self._book_data.get("top_categories")
        if "month" in self._extra_attr_keys:
            attrs["month"] = period.get("month")
        if "today" in self._extra_attr_keys:
            attrs["date"] = period.get("today")
        if "week" in self._extra_attr_keys:
            attrs["week"] = period.get("week")
        if "year" in self._extra_attr_keys:
            attrs["year"] = period.get("year")
        if "accounts" in self._extra_attr_keys:
            attrs[ATTR_ACCOUNTS] = self._book_data.get("accounts")

        return attrs
