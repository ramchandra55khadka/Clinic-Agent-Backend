"""Weekday names shared by the schedule schema, model and availability rules.

A schedule's ``working_days`` column stores a comma-separated subset of
``WEEKDAYS``. ``NULL`` (or a value that no longer parses) means the doctor works
every day, which is how schedules created before this concept existed behave.
"""

from __future__ import annotations

#: Weekday names as the clinic writes them (Sunday-first week, matching the UI).
WEEKDAYS: tuple[str, ...] = (
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
)


def normalize_days(days: list[str] | None) -> list[str] | None:
    """Validate, de-duplicate and canonically order a submitted day list.

    ``None`` stays ``None`` (= every day). An empty list or an unknown weekday
    raises ``ValueError`` so the Pydantic field validator reports a 422.
    """
    if days is None:
        return None
    unknown = [day for day in days if day not in WEEKDAYS]
    if unknown:
        raise ValueError(f"Unknown weekday: {', '.join(unknown)}")
    if not days:
        raise ValueError("At least one weekday is required")
    selected = set(days)
    return [day for day in WEEKDAYS if day in selected]


def days_to_column(days: list[str] | None) -> str | None:
    """``["Monday", "Sunday"]`` -> ``"Sunday,Monday"`` (canonical order)."""
    normalized = normalize_days(days)
    if normalized is None:
        return None
    return ",".join(normalized)


def column_to_days(value: str | None) -> list[str]:
    """Reads the stored column; empty/NULL means the doctor works every day."""
    if not value:
        return list(WEEKDAYS)
    selected = {part for part in value.split(",") if part in WEEKDAYS}
    if not selected:
        return list(WEEKDAYS)
    return [day for day in WEEKDAYS if day in selected]
