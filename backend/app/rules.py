from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

DETROIT = ZoneInfo("America/Detroit")

CATEGORIES = ("produce", "dairy", "bakery", "shelf_stable", "frozen")
UNITS = ("crate", "case", "pound")
STORAGE = ("ambient", "refrigerated", "frozen")
HOLDING = ("reserved", "delivered")
ACTIVE = ("draft", "reserved")

CATEGORY_LABELS = {
    "produce": "produce",
    "dairy": "dairy",
    "bakery": "bakery",
    "shelf_stable": "shelf-stable food",
    "frozen": "frozen food",
}


class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def require_choice(value: str, options: tuple[str, ...], label: str) -> None:
    if value not in options:
        raise DomainError(f"{label} must be one of: {', '.join(options)}")


def unit_phrase(quantity: int, unit: str) -> str:
    word = unit
    if quantity != 1:
        word = {"case": "cases", "crate": "crates", "pound": "pounds"}.get(unit, f"{unit}s")
    return f"{quantity} {word}"


def format_clock(moment: datetime) -> str:
    local = moment.astimezone(DETROIT)
    hour = local.hour % 12 or 12
    suffix = "a.m." if local.hour < 12 else "p.m."
    if local.minute:
        return f"{hour}:{local.minute:02d} {suffix}"
    return f"{hour} {suffix}"


def window_problem(start: datetime, end: datetime, deadline: datetime, now: datetime) -> Optional[str]:
    if end <= start:
        return "Receiving window is not a real time range."
    if end <= now:
        return f"Receiving window ended at {format_clock(end)}."
    if start > deadline:
        return f"Receiving window starts after the distribution deadline ({format_clock(deadline)})."
    return None


def eligible_explanation(category: str, unit: str, room: int, receiving_end: datetime) -> str:
    label = CATEGORY_LABELS[category]
    return (
        f"Requested {label}, has room for {unit_phrase(room, unit)}, "
        f"and can receive before {format_clock(receiving_end)}"
    )
