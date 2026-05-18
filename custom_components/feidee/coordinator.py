"""Data update coordinator for Feidee."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    FeideeClient,
    metric_value,
    parse_account_balances,
    parse_top_categories,
    sum_account_balances,
)
from .const import CONF_PASSWORD, CONF_PHONE, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .helpers import device_id_for_entry, get_books_from_entry, get_enabled_sensors_from_entry
from .sensor_types import (
    FETCH_ACCOUNTS,
    FETCH_EXPENSE_MONTH,
    FETCH_EXPENSE_TODAY,
    FETCH_EXPENSE_WEEK,
    FETCH_EXPENSE_YEAR,
    FETCH_INCOME_MONTH,
    FETCH_INCOME_TODAY,
    FETCH_INCOME_WEEK,
    FETCH_INCOME_YEAR,
    get_required_fetches,
)

_LOGGER = logging.getLogger(__name__)


def _period_ids(now: datetime) -> dict[str, str]:
    year, week, _ = now.isocalendar()
    return {
        "month": now.strftime("%Y%m"),
        "today": now.strftime("%Y%m%d"),
        "week": f"{year}_{week}",
        "year": str(year),
    }


async def _fetch_book_data(
    client: FeideeClient,
    book_id: str,
    book_name: str,
    periods: dict[str, str],
    required: frozenset[str],
) -> dict[str, Any]:
    coros: dict[str, Any] = {}

    if FETCH_EXPENSE_MONTH in required:
        coros[FETCH_EXPENSE_MONTH] = client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=periods["month"],
            category_type="Expense",
        )
    if FETCH_INCOME_MONTH in required:
        coros[FETCH_INCOME_MONTH] = client.get_rollup_summary(
            book_id,
            group_key="TIME_MONTH",
            group_id=periods["month"],
            category_type="Income",
        )
    if FETCH_EXPENSE_TODAY in required:
        coros[FETCH_EXPENSE_TODAY] = client.get_rollup_summary(
            book_id,
            group_key="TIME_DAY",
            group_id=periods["today"],
            category_type="Expense",
        )
    if FETCH_INCOME_TODAY in required:
        coros[FETCH_INCOME_TODAY] = client.get_rollup_summary(
            book_id,
            group_key="TIME_DAY",
            group_id=periods["today"],
            category_type="Income",
        )
    if FETCH_EXPENSE_WEEK in required:
        coros[FETCH_EXPENSE_WEEK] = client.get_rollup_summary(
            book_id,
            group_key="TIME_WEEK",
            group_id=periods["week"],
            category_type="Expense",
        )
    if FETCH_INCOME_WEEK in required:
        coros[FETCH_INCOME_WEEK] = client.get_rollup_summary(
            book_id,
            group_key="TIME_WEEK",
            group_id=periods["week"],
            category_type="Income",
        )
    if FETCH_EXPENSE_YEAR in required:
        coros[FETCH_EXPENSE_YEAR] = client.get_rollup_summary(
            book_id,
            group_key="TIME_YEAR",
            group_id=periods["year"],
            category_type="Expense",
        )
    if FETCH_INCOME_YEAR in required:
        coros[FETCH_INCOME_YEAR] = client.get_rollup_summary(
            book_id,
            group_key="TIME_YEAR",
            group_id=periods["year"],
            category_type="Income",
        )
    if FETCH_ACCOUNTS in required:
        coros[FETCH_ACCOUNTS] = client.get_accounts(book_id)

    keys = list(coros.keys())
    results_list = await asyncio.gather(*coros.values()) if keys else []
    raw = dict(zip(keys, results_list, strict=True))

    expense_month = raw.get(FETCH_EXPENSE_MONTH, {})
    income_month = raw.get(FETCH_INCOME_MONTH, {})
    accounts_raw = raw.get(FETCH_ACCOUNTS, [])

    monthly_expense = metric_value(expense_month, "EXPENSE")
    monthly_income = metric_value(income_month, "INCOME")
    monthly_balance = metric_value(expense_month, "BALANCE")
    if monthly_balance == 0.0 and (expense_month or income_month):
        monthly_balance = monthly_income - monthly_expense

    data: dict[str, Any] = {
        "book_id": book_id,
        "book_name": book_name,
        "monthly_expense": monthly_expense,
        "monthly_income": monthly_income,
        "monthly_balance": monthly_balance,
        "today_expense": metric_value(raw.get(FETCH_EXPENSE_TODAY, {}), "EXPENSE"),
        "today_income": metric_value(raw.get(FETCH_INCOME_TODAY, {}), "INCOME"),
        "weekly_expense": metric_value(raw.get(FETCH_EXPENSE_WEEK, {}), "EXPENSE"),
        "weekly_income": metric_value(raw.get(FETCH_INCOME_WEEK, {}), "INCOME"),
        "yearly_expense": metric_value(raw.get(FETCH_EXPENSE_YEAR, {}), "EXPENSE"),
        "yearly_income": metric_value(raw.get(FETCH_INCOME_YEAR, {}), "INCOME"),
        "total_balance": sum_account_balances(accounts_raw) if accounts_raw else 0.0,
        "top_categories": parse_top_categories(expense_month) if expense_month else [],
        "accounts": parse_account_balances(accounts_raw) if accounts_raw else [],
    }
    return data


class FeideeDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch Feidee statistics for all configured books."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self.books = get_books_from_entry(entry)
        self.enabled_sensors = get_enabled_sensors_from_entry(entry)
        self.required_fetches = get_required_fetches(self.enabled_sensors)
        self.client = FeideeClient(
            entry.data[CONF_PHONE],
            entry.data[CONF_PASSWORD],
            device_id=device_id_for_entry(entry),
        )

        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        now = datetime.now()
        periods = _period_ids(now)

        if not self.books:
            raise UpdateFailed("No books configured")
        if not self.enabled_sensors:
            raise UpdateFailed("No sensors enabled")

        try:
            results = await asyncio.gather(
                *[
                    _fetch_book_data(
                        self.client,
                        book["id"],
                        book["name"],
                        periods,
                        self.required_fetches,
                    )
                    for book in self.books
                ]
            )
        except Exception as err:
            raise UpdateFailed(f"Failed to fetch Feidee data: {err}") from err

        return {
            "month": periods["month"],
            "today": periods["today"],
            "week": periods["week"],
            "year": periods["year"],
            "books": {item["book_id"]: item for item in results},
        }

    async def async_shutdown(self) -> None:
        await self.client.close()
