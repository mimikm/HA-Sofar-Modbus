"""Home Assistant-driven charge/discharge slots (pure logic, no HA imports).

A slot is a dict:
    id        str
    action    "charge" | "discharge"
    power     int W
    soc       int | None  – charge: stop at/above, discharge: stop at/below
    daily     bool
    start/end "HH:MM" when daily, ISO datetime (naive local) when one-off
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
import uuid

from .registers import ACTION_CHARGE, ACTION_DISCHARGE, ACTION_NO_DISCHARGE


def _t(s: str) -> time:
    h, m = (int(x) for x in s.split(":")[:2])
    return time(h, m)


def make_slot(action: str, start, end, power: int, soc: int | None, daily: bool,
              now: datetime) -> dict:
    """Build a slot. start/end may be time or datetime (naive local)."""
    slot = {"id": uuid.uuid4().hex[:8], "action": action, "power": int(power),
            "soc": soc, "daily": bool(daily)}
    if daily:
        st = start.time() if isinstance(start, datetime) else start
        en = end.time() if isinstance(end, datetime) else end
        slot["start"], slot["end"] = st.strftime("%H:%M"), en.strftime("%H:%M")
        return slot
    if not isinstance(start, datetime):
        start = datetime.combine(now.date(), start)
    if not isinstance(end, datetime):
        end = datetime.combine(start.date(), end)
        if end <= start:
            end += timedelta(days=1)
        if end <= now:  # whole window already passed today -> tomorrow
            start, end = start + timedelta(days=1), end + timedelta(days=1)
    if end <= start:
        raise ValueError("end must be after start")
    slot["start"], slot["end"] = start.isoformat(timespec="minutes"), end.isoformat(timespec="minutes")
    return slot


def is_active(slot: dict, now: datetime) -> bool:
    if slot["daily"]:
        st, en, t = _t(slot["start"]), _t(slot["end"]), now.time()
        return st <= t < en if st < en else (t >= st or t < en)
    return datetime.fromisoformat(slot["start"]) <= now < datetime.fromisoformat(slot["end"])


def is_expired(slot: dict, now: datetime) -> bool:
    return not slot["daily"] and now >= datetime.fromisoformat(slot["end"])


def active_slot(slots: list[dict], now: datetime) -> dict | None:
    for slot in slots:  # first match wins (order of creation)
        if is_active(slot, now):
            return slot
    return None


def target(slot: dict, soc: int | None) -> tuple[str, int]:
    """Battery action for an active slot. SOC limit reached -> hold (no discharge)."""
    limit = slot.get("soc")
    if slot["action"] == "charge":
        if limit is not None and soc is not None and soc >= limit:
            return ACTION_NO_DISCHARGE, 0
        return ACTION_CHARGE, slot["power"]
    if limit is not None and soc is not None and soc <= limit:
        return ACTION_NO_DISCHARGE, 0
    return ACTION_DISCHARGE, slot["power"]
