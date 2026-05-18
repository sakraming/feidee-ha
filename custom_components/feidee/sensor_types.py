"""Available sensor metrics and their API fetch requirements."""

from __future__ import annotations

from typing import Any, TypedDict


class SensorTypeSpec(TypedDict, total=False):
    translation_key: str
    icon: str
    data_key: str
    requires: frozenset[str]
    extra_attributes: frozenset[str]


# Fetch task keys used by the coordinator
FETCH_EXPENSE_MONTH = "expense_month"
FETCH_INCOME_MONTH = "income_month"
FETCH_EXPENSE_TODAY = "expense_today"
FETCH_INCOME_TODAY = "income_today"
FETCH_EXPENSE_WEEK = "expense_week"
FETCH_INCOME_WEEK = "income_week"
FETCH_EXPENSE_YEAR = "expense_year"
FETCH_INCOME_YEAR = "income_year"
FETCH_ACCOUNTS = "accounts"

SENSOR_TYPES: dict[str, SensorTypeSpec] = {
    "monthly_expense": {
        "translation_key": "monthly_expense",
        "icon": "mdi:cash-minus",
        "data_key": "monthly_expense",
        "requires": frozenset({FETCH_EXPENSE_MONTH}),
        "extra_attributes": frozenset({"top_categories", "month"}),
    },
    "monthly_income": {
        "translation_key": "monthly_income",
        "icon": "mdi:cash-plus",
        "data_key": "monthly_income",
        "requires": frozenset({FETCH_INCOME_MONTH}),
        "extra_attributes": frozenset({"month"}),
    },
    "monthly_balance": {
        "translation_key": "monthly_balance",
        "icon": "mdi:scale-balance",
        "data_key": "monthly_balance",
        "requires": frozenset({FETCH_EXPENSE_MONTH, FETCH_INCOME_MONTH}),
        "extra_attributes": frozenset({"month"}),
    },
    "today_expense": {
        "translation_key": "today_expense",
        "icon": "mdi:cash-clock",
        "data_key": "today_expense",
        "requires": frozenset({FETCH_EXPENSE_TODAY}),
        "extra_attributes": frozenset({"today"}),
    },
    "today_income": {
        "translation_key": "today_income",
        "icon": "mdi:cash-plus",
        "data_key": "today_income",
        "requires": frozenset({FETCH_INCOME_TODAY}),
        "extra_attributes": frozenset({"today"}),
    },
    "weekly_expense": {
        "translation_key": "weekly_expense",
        "icon": "mdi:calendar-week",
        "data_key": "weekly_expense",
        "requires": frozenset({FETCH_EXPENSE_WEEK}),
        "extra_attributes": frozenset({"week"}),
    },
    "weekly_income": {
        "translation_key": "weekly_income",
        "icon": "mdi:calendar-week",
        "data_key": "weekly_income",
        "requires": frozenset({FETCH_INCOME_WEEK}),
        "extra_attributes": frozenset({"week"}),
    },
    "yearly_expense": {
        "translation_key": "yearly_expense",
        "icon": "mdi:calendar",
        "data_key": "yearly_expense",
        "requires": frozenset({FETCH_EXPENSE_YEAR}),
        "extra_attributes": frozenset({"year"}),
    },
    "yearly_income": {
        "translation_key": "yearly_income",
        "icon": "mdi:calendar",
        "data_key": "yearly_income",
        "requires": frozenset({FETCH_INCOME_YEAR}),
        "extra_attributes": frozenset({"year"}),
    },
    "total_balance": {
        "translation_key": "total_balance",
        "icon": "mdi:wallet",
        "data_key": "total_balance",
        "requires": frozenset({FETCH_ACCOUNTS}),
        "extra_attributes": frozenset({"accounts"}),
    },
}

# Used when migrating older config entries without explicit selection
DEFAULT_ENABLED_SENSORS: list[str] = [
    "monthly_expense",
    "monthly_income",
    "monthly_balance",
    "today_expense",
    "total_balance",
]


# Labels shown in config/options flow (entity names use translations)
SENSOR_TYPE_LABELS: dict[str, str] = {
    "monthly_expense": "本月支出",
    "monthly_income": "本月收入",
    "monthly_balance": "本月结余",
    "today_expense": "今日支出",
    "today_income": "今日收入",
    "weekly_expense": "本周支出",
    "weekly_income": "本周收入",
    "yearly_expense": "今年支出",
    "yearly_income": "今年收入",
    "total_balance": "账本总余额",
}


def sensor_selector_options() -> list[dict[str, str]]:
    return [
        {"value": key, "label": SENSOR_TYPE_LABELS[key]}
        for key in SENSOR_TYPES
    ]


def get_required_fetches(enabled_sensors: list[str]) -> frozenset[str]:
    required: set[str] = set()
    for key in enabled_sensors:
        spec = SENSOR_TYPES.get(key)
        if spec:
            required.update(spec.get("requires", ()))
    return frozenset(required)


def validate_enabled_sensors(enabled: list[str]) -> list[str]:
    """Return only known sensor type keys."""
    return [k for k in enabled if k in SENSOR_TYPES]
